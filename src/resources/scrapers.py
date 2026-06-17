"""Stream scrapers — query Stremio stream add-ons for torrent sources.

Every provider is just a name + enable-setting + base URL; we call them all
*configless* (the bare Stremio `/stream/...` endpoint, no debrid config), so each
returns raw torrent rows carrying an infoHash rather than a pre-resolved link.
The pipeline then does the rest itself:

    fetch each provider  ->  normalize to {infohash, title, size, seeders}
    merge + dedupe by infohash (same torrent from two providers collapses to one)
    enrich: parse the release name for quality / tags / languages
    filter by settings (min/max resolution, languages, max size)
    keep only hashes TorBox has cached (one batch API call)
    sort

Playback resolves the chosen infohash through TorBox directly (see torbox.py) —
there's no add-on URL to fall back to, which is the point of calling configless.

    sources("movie", "tt0111161")            -> [Stream, ...]
    sources("series", "tt0111161:1:2")       -> [Stream, ...]

Stremio ids: a movie is its IMDb id ("tt…"); an episode is "tt…:season:episode".
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError
from urllib.request import Request, urlopen

from resources.framework import get_bool, get_int, get_setting, log, log_error

_TIMEOUT = 20
# Torrentio/Comet sit behind Cloudflare, which 403s urllib's default UA.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Providers: (display name, settings.xml enable-toggle id, configless base URL).
# Add one by appending a row — every provider speaks the same Stremio schema, so
# no per-provider parsing is needed.
PROVIDERS = [
    ("Torrentio", "scraper_torrentio", "https://torrentio.strem.fun"),
    ("Comet", "scraper_comet", "https://comet.feels.legal"),
]

# Resolution buckets, best-first; the last one is a catch-all.
_RESOLUTIONS = [
    ("4K", re.compile(r"\b(2160p|4k|uhd)\b", re.I)),
    ("1080p", re.compile(r"\b1080p\b", re.I)),
    ("720p", re.compile(r"\b720p\b", re.I)),
    ("480p", re.compile(r"\b480p\b", re.I)),
    ("SD", re.compile(r"")),
]
_QUALITY_RANK = {"4K": 0, "1080p": 1, "720p": 2, "480p": 3, "SD": 4}
# Worst-to-best, for clamping against the min/max resolution settings.
_RES_ORDER = ["SD", "480p", "720p", "1080p", "4K"]
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
# convention Torrentio/Comet use. These are countries, not languages, so a few
# map by dominant language (BR->Portuguese, MX->Spanish).
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
_HASH_RX = re.compile(r"[a-fA-F0-9]{40}")


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
    """One torrent source row, keyed by infohash and resolved via TorBox."""

    def __init__(self, scraper, title, size, seeders, infohash, text):
        self.scraper = scraper      # provider(s) it came from, for display
        self.title = title          # release filename
        self.size = size            # bytes (0 if unknown)
        self.seeders = seeders      # int (0 if unknown)
        self.infohash = infohash    # torrent hash — the key for dedupe + resolve
        self.text = text            # name/title/description, for metadata parsing
        self.providers = {scraper}  # every provider that returned this hash
        self.has_filename = False   # title came from behaviorHints.filename
        self.quality = "SD"         # filled by _enrich
        self.tags = []
        self.languages = []


# ===========================================================================
# Fetch + normalize
# ===========================================================================
def _search(name, base, media_type, video_id):
    """Hit one provider's configless stream endpoint; normalize its rows."""
    url = "{0}/stream/{1}/{2}.json".format(base, media_type, video_id)
    try:
        data = _http_json(url)
    except (URLError, ValueError, OSError) as exc:
        log_error("{0}: {1}".format(name, exc))
        return []
    out = [s for s in (_normalize(name, raw) for raw in data.get("streams", [])) if s]
    log("{0}: {1} sources".format(name, len(out)))
    return out


def _normalize(provider, raw):
    """One Stremio stream object -> Stream, or None if it carries no infohash."""
    bh = raw.get("behaviorHints") or {}
    infohash = (raw.get("infoHash") or "").strip().lower()
    if not _HASH_RX.fullmatch(infohash):    # fall back to the hash in bingeGroup
        m = _HASH_RX.search(bh.get("bingeGroup") or "")
        infohash = m.group(0).lower() if m else ""
    if not infohash:
        return None
    text = " ".join(p for p in (raw.get("name"), raw.get("title"),
                                raw.get("description")) if p)
    filename = bh.get("filename")
    title = filename or _first_line(text) or "Source"
    size = bh.get("videoSize") or _parse_size(text)
    stream = Stream(provider, title, int(size or 0), _parse_seeders(text),
                    infohash, title + " " + text)
    stream.has_filename = bool(filename)
    return stream


# ===========================================================================
# Merge + enrich
# ===========================================================================
def _dedupe(streams):
    """Collapse rows sharing an infohash; merge providers, size, seeders."""
    by_hash = {}
    for s in streams:
        cur = by_hash.get(s.infohash)
        if cur is None:
            by_hash[s.infohash] = s
            continue
        cur.providers |= s.providers
        cur.size = max(cur.size, s.size)
        cur.seeders = max(cur.seeders, s.seeders)
        if s.has_filename and not cur.has_filename:   # prefer a real filename
            cur.title, cur.text, cur.has_filename = s.title, s.text, True
    return list(by_hash.values())


def _enrich(s):
    """Parse quality / tags / languages from the release text (once per hash)."""
    s.quality = next(q for q, rx in _RESOLUTIONS if rx.search(s.text))
    s.tags = _tags(s.text)
    s.languages = _languages(s.text)
    s.scraper = ", ".join(sorted(s.providers))


# ===========================================================================
# Filter by settings
# ===========================================================================
def _passes_filters(s):
    rank = _QUALITY_RANK.get(s.quality, 9)
    if rank > _QUALITY_RANK[_clamp_res("scraper_min_resolution", "SD")]:
        return False                                    # below the resolution floor
    if rank < _QUALITY_RANK[_clamp_res("scraper_max_resolution", "4K")]:
        return False                                    # above the resolution cap
    cap = get_int("scraper_max_size_gb", 0)
    if cap and s.size and s.size > cap * _UNIT["GB"]:
        return False
    prefs = _pref_languages()
    # Keep rows with no detected language — flag detection is too unreliable to
    # drop a source just because it lacked a flag emoji.
    if prefs and s.languages and not prefs.intersection(s.languages):
        return False
    return True


def _clamp_res(setting, default):
    value = get_setting(setting, default)
    return value if value in _QUALITY_RANK else default


def _pref_languages():
    raw = get_setting("scraper_languages", "")
    return {p.strip().title() for p in raw.split(",") if p.strip()}


# ===========================================================================
# Keep only TorBox-cached hashes
# ===========================================================================
def _keep_cached(streams):
    if not streams:
        return streams
    from resources import torbox          # lazy — only needed at scrape time
    cached = torbox.cached_hashes([s.infohash for s in streams])
    kept = [s for s in streams if s.infohash in cached]
    log("TorBox cached: {0}/{1} sources".format(len(kept), len(streams)))
    return kept


# ===========================================================================
# Small parsers
# ===========================================================================
def _first_line(text):
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


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
# Pipeline entry point
# ===========================================================================
def sources(media_type, video_id):
    """Scrape, merge, filter, and cache-check torrent sources for a Stremio id."""
    active = [p for p in PROVIDERS if get_bool(p[1], True)]
    if not configured() or not active:
        return []
    rows = []
    with ThreadPoolExecutor(max_workers=len(active)) as pool:
        for chunk in pool.map(
                lambda p: _search(p[0], p[2], media_type, video_id), active):
            rows.extend(chunk)
    streams = _dedupe(rows)
    for s in streams:
        _enrich(s)
    streams = [s for s in streams if _passes_filters(s)]
    streams = _keep_cached(streams)
    streams.sort(key=lambda s: (_QUALITY_RANK.get(s.quality, 9), -s.size, -s.seeders))
    return streams
