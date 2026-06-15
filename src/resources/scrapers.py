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


def _torbox_key():
    return get_setting("torbox_api_key")


def configured():
    """True if a TorBox key is set (without it, sources can't be resolved)."""
    return bool(_torbox_key())


def _http_json(url, data=None, headers=None):
    with urlopen(Request(url, data=data, headers=headers or {}), timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Stream:
    """One playable source row — already resolved to an HTTP URL by debrid."""

    def __init__(self, scraper, title, url, quality, size, seeders):
        self.scraper = scraper      # originating add-on name
        self.title = title          # release filename/description
        self.url = url              # directly-playable URL
        self.quality = quality      # "4K" / "1080p" / ...
        self.size = size            # bytes (0 if unknown)
        self.seeders = seeders      # int (0 if unknown)


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
        return Stream(self.name, _filename(raw), url, quality, size, _parse_seeders(text))


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
