"""TMDB v3 client and JSON→metadata mappers.

The TMDB knowledge layer: the client (`_get` + movies/shows/discover/...), the
mappers that turn results into the framework's info/art dicts, and the menu
data tables (NAMED/LANGUAGES/NETWORKS). The addon's route handlers (addon.py)
and UI classes (ui.py) consume these; nothing here touches Kodi listings.
Uses stdlib urllib (no 'requests'); responses go through the framework cache.
"""
import json
from datetime import date
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from resources.framework import cache, get_setting, log_error

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
# Hardcoded TMDB v3 API key — not user-configurable.
API_KEY = "1248868d7003f60f2386595db98455ef"

POSTER_SIZE = "w500"
FANART_SIZE = "w1280"
STILL_SIZE = "w780"

# cache TTLs (minutes)
TTL_LIST = 8 * 60
TTL_DETAIL = 7 * 24 * 60

LANGUAGES = [("English", "en"), ("Spanish", "es"), ("French", "fr"),
             ("Japanese", "ja"), ("Korean", "ko"), ("German", "de"),
             ("Hindi", "hi"), ("Italian", "it"), ("Mandarin", "zh"),
             ("Russian", "ru"), ("Portuguese", "pt"), ("Turkish", "tr")]

NETWORKS = [("Netflix", 213), ("HBO / Max", 49), ("Disney+", 2739),
            ("Apple TV+", 2552), ("Prime Video", 1024), ("Hulu", 453),
            ("AMC", 174), ("BBC One", 4), ("Paramount+", 4330),
            ("Peacock", 3353), ("FX", 88), ("Showtime", 67), ("NBC", 6),
            ("ABC", 2), ("The CW", 71), ("Adult Swim", 80)]

# TMDB genre ids are stable, so the genre tables are hardcoded — this also keeps
# genre_map() (used to label every row) from making an API call.
GENRES = {
    "movie": [
        (28, "Action"), (12, "Adventure"), (16, "Animation"), (35, "Comedy"),
        (80, "Crime"), (99, "Documentary"), (18, "Drama"), (10751, "Family"),
        (14, "Fantasy"), (36, "History"), (27, "Horror"), (10402, "Music"),
        (9648, "Mystery"), (10749, "Romance"), (878, "Science Fiction"),
        (10770, "TV Movie"), (53, "Thriller"), (10752, "War"), (37, "Western"),
    ],
    "tv": [
        (10759, "Action & Adventure"), (16, "Animation"), (35, "Comedy"),
        (80, "Crime"), (99, "Documentary"), (18, "Drama"), (10751, "Family"),
        (10762, "Kids"), (9648, "Mystery"), (10763, "News"), (10764, "Reality"),
        (10765, "Sci-Fi & Fantasy"), (10766, "Soap"), (10767, "Talk"),
        (10768, "War & Politics"), (37, "Western"),
    ],
}

# Major US streaming providers (TMDB watch-provider ids; global — the same ids
# work for both movie and tv discover). Curated, not fetched.
PROVIDERS = [("Netflix", 8), ("Amazon Prime Video", 9), ("Disney+", 337),
             ("Max", 1899), ("Hulu", 15), ("Apple TV+", 350),
             ("Paramount+", 2303), ("Peacock", 386), ("Starz", 43),
             ("AMC+", 526), ("Crunchyroll", 283), ("MGM+", 34), ("Tubi", 73),
             ("Pluto TV", 300), ("The CW", 83)]

# US movie certifications, in display order. (TMDB's tv discover can't filter by
# certification, so there's no tv equivalent.)
CERTIFICATIONS = ["G", "PG", "PG-13", "R", "NC-17"]

# Named TMDB-discover lists (FenLight-style browse rows). A "@today" value is
# replaced with today's date at request time (see named_params).
NAMED = {
    ("movie", "most_voted"): {"sort_by": "vote_count.desc"},
    ("movie", "blockbusters"): {"sort_by": "revenue.desc"},
    ("movie", "premieres"): {"sort_by": "primary_release_date.desc",
                             "with_release_type": "4|6", "region": "US",
                             "release_date.lte": "@today"},
    ("movie", "latest_releases"): {"sort_by": "primary_release_date.desc",
                                   "with_release_type": "3", "region": "US",
                                   "release_date.lte": "@today",
                                   "vote_count.gte": "10"},
    ("tv", "most_voted"): {"sort_by": "vote_count.desc"},
    ("tv", "premieres"): {"sort_by": "first_air_date.desc",
                          "first_air_date.lte": "@today", "vote_count.gte": "5"},
    ("tv", "upcoming"): {"sort_by": "first_air_date.asc",
                         "first_air_date.gte": "@today"},
}


def named_params(media, key):
    """Resolved discover params for a NAMED list (expands the @today token)."""
    today = date.today().isoformat()
    return {k: (today if v == "@today" else v)
            for k, v in NAMED.get((media, key), {}).items()}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
def _lang():
    return get_setting("tmdb_lang") or "en-US"


def _get(path, ttl=TTL_LIST, **params):
    params.setdefault("api_key", API_KEY)
    params.setdefault("language", _lang())
    ck_params = {k: v for k, v in params.items() if k != "api_key"}
    ck = "tmdb:{0}:{1}".format(path, json.dumps(ck_params, sort_keys=True))
    hit = cache.get(ck)
    if hit is not None:
        return hit
    url = "{0}/{1}?{2}".format(API, path.lstrip("/"), urlencode(params))
    try:
        with urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, ValueError, OSError) as exc:  # surface, never crash the menu
        log_error("TMDB request failed for {0}: {1}".format(path, exc))
        return {}
    if data:
        cache.set(ck, data, ttl)
    return data


def movies(category, page=1):
    paths = {"trending": "trending/movie/week", "popular": "movie/popular",
             "top_rated": "movie/top_rated", "now_playing": "movie/now_playing",
             "upcoming": "movie/upcoming"}
    return _get(paths.get(category, "movie/popular"), page=page)


def shows(category, page=1):
    paths = {"trending": "trending/tv/week", "popular": "tv/popular",
             "top_rated": "tv/top_rated", "on_the_air": "tv/on_the_air",
             "airing_today": "tv/airing_today"}
    return _get(paths.get(category, "tv/popular"), page=page)


def discover(media, page=1, **params):
    params.setdefault("sort_by", "popularity.desc")
    return _get("discover/{0}".format(media), page=page, **params)


def genres(media):
    return [{"id": gid, "name": name} for gid, name in GENRES.get(media, [])]


def genre_map(media):
    return {gid: name for gid, name in GENRES.get(media, [])}


def search(media, query, page=1):
    return _get("search/{0}".format(media), ttl=60, query=query, page=page,
                include_adult="false")


def show_details(tmdb_id):
    return _get("tv/{0}".format(tmdb_id), ttl=TTL_DETAIL,
                append_to_response="external_ids")


def season_details(tmdb_id, season_number):
    return _get("tv/{0}/season/{1}".format(tmdb_id, season_number), ttl=TTL_DETAIL)


# ---------------------------------------------------------------------------
# Mappers — output only keys the ui module's _apply_info consumes
# ---------------------------------------------------------------------------
def _img(path, size):
    return "{0}/{1}{2}".format(IMG, size, path) if path else ""


def _year(date_str):
    return date_str[:4] if date_str else ""


def map_movie(item, gmap=None):
    info = {
        "title": item.get("title") or item.get("original_title", ""),
        "plot": item.get("overview", ""),
        "year": _year(item.get("release_date", "")),
        "premiered": item.get("release_date", ""),
        "rating": item.get("vote_average", 0),
        "tmdb": item.get("id"),
    }
    if gmap and item.get("genre_ids"):
        info["genres"] = [gmap[g] for g in item["genre_ids"] if g in gmap]
    art = {"poster": _img(item.get("poster_path"), POSTER_SIZE),
           "thumb": _img(item.get("poster_path"), POSTER_SIZE),
           "fanart": _img(item.get("backdrop_path"), FANART_SIZE)}
    return info, art


def map_show(item, gmap=None, details=None):
    info = {
        "title": item.get("name") or item.get("original_name", ""),
        "tvshowtitle": item.get("name") or item.get("original_name", ""),
        "plot": item.get("overview", ""),
        "year": _year(item.get("first_air_date", "")),
        "premiered": item.get("first_air_date", ""),
        "rating": item.get("vote_average", 0),
        "tmdb": item.get("id"),
    }
    if gmap and item.get("genre_ids"):
        info["genres"] = [gmap[g] for g in item["genre_ids"] if g in gmap]
    art = {"poster": _img(item.get("poster_path"), POSTER_SIZE),
           "thumb": _img(item.get("poster_path"), POSTER_SIZE),
           "fanart": _img(item.get("backdrop_path"), FANART_SIZE)}
    if details:
        if details.get("genres"):
            info["genres"] = [g["name"] for g in details["genres"]]
        runtimes = details.get("episode_run_time") or []
        if runtimes:
            info["duration"] = runtimes[0] * 60
        info["imdb"] = (details.get("external_ids") or {}).get("imdb_id", "")
    return info, art


def map_episode(item, show_info, show_art):
    info = {
        "title": item.get("name", ""),
        "tvshowtitle": show_info.get("tvshowtitle", ""),
        "plot": item.get("overview", ""),
        "season": item.get("season_number"),
        "episode": item.get("episode_number"),
        "premiered": item.get("air_date", ""),
        "rating": item.get("vote_average", 0),
        "tmdb": show_info.get("tmdb"),
        "imdb": show_info.get("imdb"),
        "year": show_info.get("year"),
    }
    if item.get("runtime"):
        info["duration"] = item["runtime"] * 60
    still = _img(item.get("still_path"), STILL_SIZE)
    art = {"poster": show_art.get("poster", ""),
           "thumb": still or show_art.get("poster", ""),
           "fanart": show_art.get("fanart", "")}
    return info, art


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------
def total(data):
    """Total page count of a TMDB list response (for pagination)."""
    return int(data.get("total_pages", 1) or 1)


def image(path, size=POSTER_SIZE):
    """Absolute TMDB image URL for a poster/still path (or "" if missing)."""
    return _img(path, size)
