"""TMDB v3 client, JSON→row mappers, and the registered TMDB providers.

Bottom layer: the client (`_get` + movies/shows/discover/...). Top layer: the
@plugin.provider / @plugin.folder functions that turn it into menu rows/nodes.
Uses stdlib urllib (no 'requests'); responses go through the framework cache.
"""
import json
from datetime import date
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from resources.framework import MediaList, cache_get, cache_set
from resources.plugin import plugin

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
# Public default key (works out of the box); users can override in settings.
DEFAULT_KEY = "1248868d7003f60f2386595db98455ef"

POSTER_SIZE = "w500"
FANART_SIZE = "w1280"
STILL_SIZE = "w780"

# cache TTLs (minutes)
TTL_LIST = 8 * 60
TTL_DETAIL = 7 * 24 * 60
TTL_GENRE = 30 * 24 * 60

LANGUAGES = [("English", "en"), ("Spanish", "es"), ("French", "fr"),
             ("Japanese", "ja"), ("Korean", "ko"), ("German", "de"),
             ("Hindi", "hi"), ("Italian", "it"), ("Mandarin", "zh"),
             ("Russian", "ru"), ("Portuguese", "pt"), ("Turkish", "tr")]

NETWORKS = [("Netflix", 213), ("HBO / Max", 49), ("Disney+", 2739),
            ("Apple TV+", 2552), ("Prime Video", 1024), ("Hulu", 453),
            ("AMC", 174), ("BBC One", 4), ("Paramount+", 4330),
            ("Peacock", 3353), ("FX", 88), ("Showtime", 67), ("NBC", 6),
            ("ABC", 2), ("The CW", 71), ("Adult Swim", 80)]

# Named TMDB-discover lists (FenLight-style browse rows).
NAMED = {
    ("movie", "most_voted"): {"sort_by": "vote_count.desc"},
    ("movie", "blockbusters"): {"sort_by": "revenue.desc"},
    ("movie", "premieres"): {"sort_by": "primary_release_date.desc",
                             "with_release_type": "4|6", "region": "US"},
    ("tv", "most_voted"): {"sort_by": "vote_count.desc"},
}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
def _key():
    return plugin.get_setting("tmdb_api_key") or DEFAULT_KEY


def _lang():
    return plugin.get_setting("tmdb_lang") or "en-US"


def _get(path, ttl=TTL_LIST, **params):
    params.setdefault("api_key", _key())
    params.setdefault("language", _lang())
    ck_params = {k: v for k, v in params.items() if k != "api_key"}
    ck = "tmdb:{0}:{1}".format(path, json.dumps(ck_params, sort_keys=True))
    hit = cache_get(ck)
    if hit is not None:
        return hit
    url = "{0}/{1}?{2}".format(API, path.lstrip("/"), urlencode(params))
    try:
        with urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, ValueError, OSError) as exc:  # surface, never crash the menu
        plugin.log_error("TMDB request failed for {0}: {1}".format(path, exc))
        return {}
    if data:
        cache_set(ck, data, ttl)
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
    return _get("genre/{0}/list".format(media), ttl=TTL_GENRE).get("genres", [])


def genre_map(media):
    return {g["id"]: g["name"] for g in genres(media)}


def search(media, query, page=1):
    return _get("search/{0}".format(media), ttl=60, query=query, page=page,
                include_adult="false")


def show_details(tmdb_id):
    return _get("tv/{0}".format(tmdb_id), ttl=TTL_DETAIL,
                append_to_response="external_ids")


def season_details(tmdb_id, season_number):
    return _get("tv/{0}/season/{1}".format(tmdb_id, season_number), ttl=TTL_DETAIL)


# ---------------------------------------------------------------------------
# Mappers — output only keys the framework's _apply_info consumes
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
# Row helpers
# ---------------------------------------------------------------------------
def _total(data):
    return int(data.get("total_pages", 1) or 1)


def _content_for(media):
    return "movies" if media == "movie" else "tvshows"


def _movie_row(item, gmap):
    info, art = map_movie(item, gmap=gmap)
    if not info["title"]:
        return None
    return {"label": info["title"], "is_playable": True, "media_type": "movie",
            "info": info, "art": art,
            "url": plugin.get_url(route="play.movie", tmdb_id=info["tmdb"])}


def _show_row(item, gmap):
    info, art = map_show(item, gmap=gmap)
    if not info["title"]:
        return None
    return {"label": info["title"], "is_folder": True, "media_type": "tvshow",
            "info": info, "art": art,
            "url": plugin.get_url(route="tmdb.seasons", tmdb_id=info["tmdb"])}


def _media_rows(media, items):
    gmap = genre_map(media)
    build = _movie_row if media == "movie" else _show_row
    return [r for r in (build(it, gmap) for it in items) if r]


# ---------------------------------------------------------------------------
# Media providers  (params, page) -> (rows, has_more)
# ---------------------------------------------------------------------------
@plugin.provider("tmdb.movies")
def movies_list(params, page):
    data = movies(params["category"], page=page)
    return _media_rows("movie", data.get("results", [])), page < _total(data)


@plugin.provider("tmdb.shows")
def shows_list(params, page):
    data = shows(params["category"], page=page)
    return _media_rows("tv", data.get("results", [])), page < _total(data)


@plugin.provider("tmdb.discover")
def discover_list(params, page):
    media = params.pop("media")          # remaining params are discover filters
    data = discover(media, page=page, **params)
    return _media_rows(media, data.get("results", [])), page < _total(data)


@plugin.provider("tmdb.named")
def named_list(params, page):
    media, key = params["media"], params["key"]
    disc = dict(NAMED.get((media, key), {}))
    if key == "premieres":
        disc["release_date.lte"] = date.today().isoformat()
    data = discover(media, page=page, **disc)
    return _media_rows(media, data.get("results", [])), page < _total(data)


@plugin.provider("tmdb.search")
def search_list(params, page):
    media = params["media"]
    data = search(media, params.get("query", ""), page=page)
    return _media_rows(media, data.get("results", [])), page < _total(data)


@plugin.provider("tmdb.episodes")
def episode_list(params, page):
    tmdb_id, season = params["tmdb_id"], int(params["season"])
    show_title = params.get("show_title", "")
    year, imdb = params.get("year", ""), params.get("imdb", "")
    details = show_details(tmdb_id)
    show_info, show_art = map_show(details, details=details)
    show_info["imdb"] = imdb
    data = season_details(tmdb_id, season)
    rows = []
    for ep in data.get("episodes", []):
        epnum = ep.get("episode_number")
        info, art = map_episode(ep, show_info, show_art)
        rows.append({
            "label": "{0}x{1:02d}. {2}".format(season, epnum or 0, info["title"]),
            "is_playable": True, "media_type": "episode", "info": info, "art": art,
            "url": plugin.get_url(route="play.episode", tmdb_id=tmdb_id, season=season,
                                  episode=epnum, show_title=show_title, year=year, imdb=imdb),
        })
    return rows, False


# ---------------------------------------------------------------------------
# Dynamic folders  (params) -> [Node, ...]
# ---------------------------------------------------------------------------
@plugin.folder("tmdb.genres")
def genre_folder(params):
    media = params["media"]
    return [MediaList(g["name"], "tmdb.discover", content=_content_for(media),
                      icon="DefaultGenre.png",
                      params={"media": media, "with_genres": g["id"]})
            for g in genres(media)]


@plugin.folder("tmdb.years")
def year_folder(params):
    media = params["media"]
    field = "primary_release_year" if media == "movie" else "first_air_date_year"
    return [MediaList(str(y), "tmdb.discover", content=_content_for(media),
                      icon="DefaultYear.png", params={"media": media, field: y})
            for y in range(date.today().year, 1969, -1)]


@plugin.folder("tmdb.languages")
def language_folder(params):
    media = params["media"]
    return [MediaList(name, "tmdb.discover", content=_content_for(media),
                      icon="DefaultAddonLanguage.png",
                      params={"media": media, "with_original_language": code})
            for name, code in LANGUAGES]


@plugin.folder("tmdb.networks")
def network_folder(params):
    return [MediaList(name, "tmdb.discover", content="tvshows",
                      icon="DefaultStudios.png",
                      params={"media": "tv", "with_networks": nid})
            for name, nid in NETWORKS]


@plugin.folder("tmdb.seasons")
def season_folder(params):
    tmdb_id = params["tmdb_id"]
    details = show_details(tmdb_id)
    show_info, show_art = map_show(details, details=details)
    imdb = (details.get("external_ids") or {}).get("imdb_id", "")
    nodes = []
    for season in details.get("seasons", []):
        num = season.get("season_number")
        if num is None or num == 0:  # skip "Specials"
            continue
        info = dict(show_info)
        info["season"] = num
        info["plot"] = season.get("overview") or show_info.get("plot", "")
        art = dict(show_art)
        if season.get("poster_path"):
            art["poster"] = art["thumb"] = "{0}/{1}{2}".format(
                IMG, POSTER_SIZE, season["poster_path"])
        nodes.append(MediaList(
            "Season {0}".format(num), "tmdb.episodes", content="episodes",
            info=info, art=art, media_type="season",
            params={"tmdb_id": tmdb_id, "season": num, "show_title": show_info["title"],
                    "year": show_info.get("year", ""), "imdb": imdb}))
    return nodes
