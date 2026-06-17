"""Stream scrapers — query Stremio stream add-ons for playable sources.

Every scraper is a thin subclass of Scraper that only knows how to build its
add-on's configured base URL (everything before `/stream/...`). The shared base
does the rest: hit the Stremio stream endpoint, parse the standard stream
objects into Stream rows, and keep only the ones with a directly-playable URL —
we rely on the configured TorBox debrid links, since native Kodi can't play a
raw magnet. Add a scraper by subclassing Scraper and listing it in SCRAPERS.

    sources("movie", "tt0111161")            -> [Stream, ...]
    sources("series", "tt0111161:1:2")       -> [Stream, ...]

Stremio ids: a movie is its IMDb id ("tt…"); an episode is "tt…:season:episode".
"""
import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError
from urllib.request import Request, urlopen

from resources.framework import get_bool, get_setting, log, log_error

_TIMEOUT = 20
# Torrentio/Comet sit behind Cloudflare, which 403s urllib's default UA.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Resolution buckets, best-first; the last one is a catch-all.
_RESOLUTIONS = [
    ("4K", re.compile(r"\b(2160p|4k|uhd)\b", re.I)),
    ("1080p", re.compile(r"\b1080p\b", re.I)),
    ("720p", re.compile(r"\b720p\b", re.I)),
    ("480p", re.compile(r"\b480p\b", re.I)),
    ("SD", re.compile(r"")),
]
_QUALITY_RANK = {"4K": 0, "1080p": 1, "720p": 2, "480p": 3, "SD": 4}
_UNIT = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}

# Release source (first match wins) + additive markers, so a row can lead with
# how it was ripped instead of the raw filename.
_SOURCE = [
    ("BluRay", re.compile(r"\b(blu-?ray|bdrip|brrip)\b", re.I)),
    ("WEB-DL", re.compile(r"\bweb-?dl\b", re.I)),
    ("WEBRip", re.compile(r"\bweb-?rip\b", re.I)),
    ("WEB", re.compile(r"\bweb\b", re.I)),
    ("HDTV", re.compile(r"\bhdtv\b", re.I)),
    ("DVD", re.compile(r"\bdvd(rip)?\b", re.I)),
    ("CAM", re.compile(r"\b(hd-?cam|cam|telesync|ts)\b", re.I)),
]
_MARKERS = [
    ("REMUX", re.compile(r"\bremux\b", re.I)),
    ("DV", re.compile(r"\b(dolby[\s._-]?vision|dovi|dv)\b", re.I)),
    ("HDR", re.compile(r"\bhdr(10)?(\+|plus)?\b", re.I)),
]

# Flag emoji (regional-indicator pairs) -> spoken language, per the Stremio
# convention Torrentio/Comet/MediaFusion use. These are countries, not
# languages, so a few map by dominant language (BR->Portuguese, MX->Spanish).
_FLAG_LANG = {
    "US": "English", "GB": "English", "AU": "English", "CA": "English",
    "ES": "Spanish", "MX": "Spanish", "AR": "Spanish",
    "FR": "French", "DE": "German", "IT": "Italian",
    "PT": "Portuguese", "BR": "Portuguese",
    "RU": "Russian", "JP": "Japanese", "KR": "Korean",
    "CN": "Chinese", "TW": "Chinese", "HK": "Chinese",
    "IN": "Hindi", "NL": "Dutch", "PL": "Polish", "TR": "Turkish",
    "SE": "Swedish", "NO": "Norwegian", "DK": "Danish", "FI": "Finnish",
    "GR": "Greek", "CZ": "Czech", "HU": "Hungarian", "RO": "Romanian",
    "TH": "Thai", "VN": "Vietnamese", "ID": "Indonesian", "UA": "Ukrainian",
    "SA": "Arabic", "EG": "Arabic", "IL": "Hebrew", "IR": "Persian",
}
_FLAG_RX = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")


def _torbox_key():
    return get_setting("torbox_api_key")


def configured():
    """True if a TorBox key is set (without it, sources can't be resolved)."""
    return bool(_torbox_key())


def _http_json(url, data=None, headers=None):
    head = {"User-Agent": _UA}
    head.update(headers or {})
    with urlopen(Request(url, data=data, headers=head), timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Stream:
    """One playable source row — already resolved to an HTTP URL by debrid."""

    def __init__(self, scraper, title, url, quality, size, seeders,
                 tags=None, languages=None, infohash=""):
        self.scraper = scraper      # originating add-on name
        self.title = title          # release filename/description
        self.url = url              # add-on resolve/playback URL (slow redirect)
        self.quality = quality      # "4K" / "1080p" / ...
        self.size = size            # bytes (0 if unknown)
        self.seeders = seeders      # int (0 if unknown)
        self.tags = tags or []      # ["BluRay", "HDR", ...] source/format tags
        self.languages = languages or []   # spoken languages, in order
        self.infohash = infohash    # torrent hash, for direct TorBox resolve


class Scraper:
    """Base Stremio stream scraper. Subclasses set `name`/`setting` + base_url()."""
    name = ""
    setting = ""        # settings.xml bool id; "" -> always enabled

    def enabled(self):
        return configured() and (get_bool(self.setting, True) if self.setting else True)

    def base_url(self, key):
        """Add-on root incl. config, no trailing slash (or None on failure)."""
        raise NotImplementedError

    def search(self, media_type, video_id):
        """Fetch + parse this add-on's streams for a Stremio id."""
        base = self.base_url(_torbox_key())
        if not base:
            return []
        url = "{0}/stream/{1}/{2}.json".format(base, media_type, video_id)
        try:
            data = _http_json(url)
        except (URLError, ValueError, OSError) as exc:
            log_error("{0}: {1}".format(self.name, exc))
            return []
        out = [s for s in (self._parse(raw) for raw in data.get("streams", [])) if s]
        log("{0}: {1} playable sources".format(self.name, len(out)))
        return out

    def _parse(self, raw):
        """Turn one Stremio stream object into a Stream (None if not playable)."""
        url = raw.get("url")
        if not url:                 # infoHash/magnet only — native Kodi can't play it
            return None
        text = "{0} {1}".format(raw.get("name", ""),
                                raw.get("title") or raw.get("description") or "")
        quality = next(q for q, rx in _RESOLUTIONS if rx.search(text))
        size = (raw.get("behaviorHints") or {}).get("videoSize") or _parse_size(text)
        return Stream(self.name, _filename(raw), url, quality, size,
                      _parse_seeders(text), _tags(text), _languages(text),
                      _infohash(raw, url))


_HASH_RX = re.compile(r"[a-fA-F0-9]{40}")


def _infohash(raw, url):
    """A torrent infohash from a stream, for direct TorBox resolve, or "".

    Torrentio puts it in the resolve URL path; Comet puts it in the bingeGroup
    ("comet|torbox|<hash>"). bingeGroup is checked first — Torrentio's holds no
    hash, so we fall through to its URL, while Comet's URL is opaque base64.
    """
    bh = raw.get("behaviorHints") or {}
    for text in (bh.get("bingeGroup") or "", url or ""):
        m = _HASH_RX.search(text)
        if m:
            return m.group(0).lower()
    return ""


def _filename(raw):
    bh = raw.get("behaviorHints") or {}
    if bh.get("filename"):
        return bh["filename"]
    text = raw.get("title") or raw.get("description") or raw.get("name") or "Source"
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "Source")


def _parse_size(text):
    m = re.search(r"([\d.]+)\s*(KB|MB|GB|TB)", text, re.I)
    return int(float(m.group(1)) * _UNIT[m.group(2).upper()]) if m else 0


def _parse_seeders(text):
    m = re.search(r"(?:👤|seeders?[:\s])\s*(\d+)", text, re.I)
    return int(m.group(1)) if m else 0


def _tags(text):
    """Source/format tags from a stream's text: one source + any markers."""
    tags = [label for label, rx in _SOURCE if rx.search(text)][:1]
    tags += [label for label, rx in _MARKERS if rx.search(text)]
    return tags


def _languages(text):
    """Spoken languages from flag emojis in a stream's text, in order."""
    langs = []
    for flag in _FLAG_RX.findall(text):
        cc = "".join(chr(ord("A") + ord(ch) - 0x1F1E6) for ch in flag)
        lang = _FLAG_LANG.get(cc)
        if lang and lang not in langs:
            langs.append(lang)
    return langs


# ===========================================================================
# Concrete scrapers — each only builds its configured base URL
# ===========================================================================
class Torrentio(Scraper):
    name = "Torrentio"
    setting = "scraper_torrentio"

    def base_url(self, key):
        return "https://torrentio.strem.fun/torbox=" + key


class Comet(Scraper):
    name = "Comet"
    setting = "scraper_comet"

    def base_url(self, key):
        config = {
            "maxResultsPerResolution": 0,
            "maxSize": 0,
            "cachedOnly": False,
            "removeTrash": True,
            "resultFormat": ["all"],
            "debridServices": [{"service": "torbox", "apiKey": key}],
            "languages": {"required": [], "exclude": [], "preferred": []},
        }
        blob = base64.urlsafe_b64encode(json.dumps(config).encode()).decode()
        return "https://comet.feels.legal/" + blob


class MediaFusion(Scraper):
    name = "MediaFusion"
    setting = "scraper_mediafusion"
    _HOST = "https://mediafusion.elfhosted.com"

    def __init__(self):
        self._cache = (None, None)   # (token, encrypted config str)

    def base_url(self, key):
        token, encoded = self._cache
        if token != key or not encoded:
            encoded = self._encrypt(key)
            self._cache = (key, encoded)
        return "{0}/{1}".format(self._HOST, encoded) if encoded else None

    def _encrypt(self, key):
        """MediaFusion stores config server-side; POST it to get the URL token."""
        body = json.dumps(
            {"streaming_provider": {"service": "torbox", "token": key}}).encode()
        try:
            resp = _http_json(self._HOST + "/encrypt-user-data", data=body,
                              headers={"Content-Type": "application/json"})
        except (URLError, ValueError, OSError) as exc:
            log_error("MediaFusion config: {0}".format(exc))
            return None
        if resp.get("status") != "success" or not resp.get("encrypted_str"):
            log_error("MediaFusion config: {0}".format(resp.get("message", "failed")))
            return None
        return resp["encrypted_str"]


SCRAPERS = [Torrentio(), Comet(), MediaFusion()]


def resolve(url):
    """Follow a source URL's redirect to the final, directly-playable CDN link.

    The Stremio add-ons hand back a redirect endpoint that performs the TorBox
    debrid lookup on access. Resolving it here — on the add-on's own thread,
    not Kodi's player thread — means Kodi is handed a direct URL that opens at
    once, instead of stalling the UI while it chases the redirect itself.
    Returns the original url unchanged if resolution fails.
    """
    try:    # GET (not HEAD — these endpoints 403 a HEAD); read no body, just the
            # post-redirect URL, then drop the connection.
        with urlopen(Request(url, headers={"User-Agent": _UA}),
                     timeout=_TIMEOUT) as resp:
            return resp.geturl()
    except (URLError, OSError) as exc:
        log_error("resolve: {0}".format(exc))
        return url


def sources(media_type, video_id):
    """Query every enabled scraper in parallel; merge + sort the results."""
    active = [s for s in SCRAPERS if s.enabled()]
    found = []
    if active:
        with ThreadPoolExecutor(max_workers=len(active)) as pool:
            for chunk in pool.map(lambda sc: sc.search(media_type, video_id), active):
                found.extend(chunk)
    found.sort(key=lambda s: (_QUALITY_RANK.get(s.quality, 9), -s.size, -s.seeders))
    return found
