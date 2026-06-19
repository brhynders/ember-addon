"""Ember route handlers — every `@router.route` in the add-on lives here.

Each handler fetches from TMDB (resources/tmdb.py), builds a List of Items
(resources/ui.py) linking to other routes, and renders. The framework
(resources/framework.py) only does routing + rendering; stream scraping lives in
resources/scrapers.py and Trakt in resources/trakt.py, which the handlers call.

This module is *imported* by addon.py rather than being the entry script: under
reuseLanguageInvoker the entry re-executes every navigation, but imported modules
are cached — so importing this registers all routes exactly once per interpreter,
not once per navigation.
"""
from datetime import date

# `scrapers` (and the ThreadPoolExecutor it pulls in via concurrent.futures) is
# imported lazily inside the few handlers that need it, to keep that weight off
# the menu-browsing path. tmdb/trakt are light and used pervasively, so stay here.
from resources import tmdb, trakt
from resources.framework import (Item, busy, cache, keyboard, notify,
                                  open_settings, router, set_resolved)
from resources.ui import (Episode, Episodes, Menu, MenuItem, Movie, Movies, Season,
                          Seasons, Show, Shows, Source, Sources, cancel, source_label)


# ---------------------------------------------------------------------------
# Shared list builder — turn a TMDB list response into a paginated Movies/Shows
# ---------------------------------------------------------------------------
def _media_list(media, data, more_url):
    results = data.get("results", [])
    gmap = tmdb.genre_map(media)
    if media == "movie":
        lst = Movies(Movie(it, router.url_for("/sources/movie/{0}".format(it["id"])), gmap)
                     for it in results)
    else:
        lst = Shows(Show(it, router.url_for("/tv/show/{0}".format(it["id"])), gmap)
                    for it in results)
    if router.page < tmdb.total(data):
        lst.next_page(more_url)
    return lst


# ---------------------------------------------------------------------------
# Home + top-level menus
# ---------------------------------------------------------------------------
@router.route("/")
def home():
    Menu([
        MenuItem("Movies", router.url_for("/movies"), icon="DefaultMovies.png"),
        MenuItem("TV Shows", router.url_for("/tv"), icon="DefaultTVShows.png"),
        MenuItem("Tools", router.url_for("/tools"), icon="DefaultAddonProgram.png"),
    ]).render()


# Browse menus. Each row is (label, route, icon); a route of None is a
# placeholder that points at /coming-soon (the feature isn't built yet).
_MOVIE_MENU = [
    ("Search", "/search/movie", "DefaultAddonsSearch.png"),
    ("In Progress", "/trakt/progress/movie", "DefaultInProgressShows.png"),
    ("Movie Watchlist", "/trakt/watchlist/movie", "DefaultPlaylist.png"),
    ("Because You Watched", "/trakt/because/movie", "DefaultMovies.png"),
    ("Trakt Recommended", "/trakt/recommended/movie", "DefaultAddonInfoProvider.png"),
    ("Random Because You Watched", "/trakt/because-random/movie", "DefaultMovies.png"),
    ("Trending Recently", "/list/movie/trending", "DefaultRecentlyAddedMovies.png"),
    ("Premieres", "/named/movie/premieres", "DefaultRecentlyAddedMovies.png"),
    ("Latest Releases", "/named/movie/latest_releases", "DefaultRecentlyAddedMovies.png"),
    ("Most Watched", "/trakt/most-watched/movie", "DefaultMusicTop100.png"),
    ("Most Favorited", "/named/movie/most_voted", "DefaultFavourites.png"),
    ("Top 10 Box Office", "/trakt/boxoffice", "DefaultMusicTop100.png"),
    ("Blockbusters", "/named/movie/blockbusters", "DefaultMovies.png"),
    ("In Theaters", "/list/movie/now_playing", "DefaultInProgressShows.png"),
    ("Up Coming", "/list/movie/upcoming", "DefaultYear.png"),
    ("Oscar Winners", None, "DefaultMusicTop100.png"),
    ("Genres", "/genres/movie", "DefaultGenre.png"),
    ("Providers", "/providers/movie", "DefaultStudios.png"),
    ("Languages", "/languages/movie", "DefaultAddonLanguage.png"),
    ("Years", "/years/movie", "DefaultYear.png"),
    ("Decades", "/decades/movie", "DefaultYear.png"),
    ("Certifications", "/certifications/movie", "DefaultGenre.png"),
]

_TV_MENU = [
    ("Search", "/search/tv", "DefaultAddonsSearch.png"),
    ("In Progress", "/trakt/progress/tv", "DefaultInProgressShows.png"),
    ("In Progress Episodes", "/trakt/progress-episodes", "DefaultInProgressShows.png"),
    ("TV Shows Watchlist", "/trakt/watchlist/tv", "DefaultPlaylist.png"),
    ("Because You Watched", "/trakt/because/tv", "DefaultTVShows.png"),
    ("Trakt Recommended", "/trakt/recommended/tv", "DefaultAddonInfoProvider.png"),
    ("Random Because You Watched", "/trakt/because-random/tv", "DefaultTVShows.png"),
    ("Trending Recently", "/list/tv/trending", "DefaultRecentlyAddedMovies.png"),
    ("Premieres", "/named/tv/premieres", "DefaultRecentlyAddedMovies.png"),
    ("Most Watched", "/trakt/most-watched/tv", "DefaultMusicTop100.png"),
    ("Most Favorited", "/named/tv/most_voted", "DefaultFavourites.png"),
    ("Airing Today", "/list/tv/airing_today", "DefaultInProgressShows.png"),
    ("On The Air", "/list/tv/on_the_air", "DefaultInProgressShows.png"),
    ("Up Coming", "/named/tv/upcoming", "DefaultYear.png"),
    ("Genres", "/genres/tv", "DefaultGenre.png"),
    ("Providers", "/providers/tv", "DefaultStudios.png"),
    ("Networks", "/networks", "DefaultStudios.png"),
    ("Languages", "/languages/tv", "DefaultAddonLanguage.png"),
    ("Years", "/years/tv", "DefaultYear.png"),
    ("Decades", "/decades/tv", "DefaultYear.png"),
    ("Certifications", None, "DefaultGenre.png"),  # tmdb tv discover can't filter certs
]


def _menu(rows):
    """Build MenuItems from a browse table; route=None -> a coming-soon stub."""
    return [MenuItem(label,
                     router.url_for(route) if route
                     else router.url_for("/coming-soon", feature=label),
                     icon=icon)
            for label, route, icon in rows]


@router.route("/movies")
def movies_menu():
    Menu(_menu(_MOVIE_MENU)).render()


@router.route("/tv")
def tv_menu():
    Menu(_menu(_TV_MENU)).render()


@router.route("/tools")
def tools_menu():
    trakt_label = "Sign Out of Trakt" if trakt.authorized() else "Authorize Trakt"
    trakt_route = "/trakt/signout" if trakt.authorized() else "/trakt/authorize"
    Menu([
        MenuItem("Settings", router.url_for("/settings"), icon="DefaultAddonService.png"),
        MenuItem(trakt_label, router.url_for(trakt_route), icon="DefaultAddonService.png"),
        MenuItem("Clear Cache", router.url_for("/clear-cache"), icon="DefaultAddonProgram.png"),
    ]).render()


# ---------------------------------------------------------------------------
# Media listings
# ---------------------------------------------------------------------------
@router.route("/list/{media}/{category}")
def category_list(media, category):
    data = (tmdb.movies if media == "movie" else tmdb.shows)(category, page=router.page)
    more = router.url_for("/list/{0}/{1}".format(media, category), page=router.page + 1)
    _media_list(media, data, more).render()


@router.route("/named/{media}/{key}")
def named_list(media, key):
    data = tmdb.discover(media, page=router.page, **tmdb.named_params(media, key))
    more = router.url_for("/named/{0}/{1}".format(media, key), page=router.page + 1)
    _media_list(media, data, more).render()


@router.route("/discover/{media}")
def discover_list(media):
    filters = dict(router.params)  # genre / year / language / network filters
    data = tmdb.discover(media, page=router.page, **filters)
    more = router.url_for("/discover/{0}".format(media), page=router.page + 1, **filters)
    _media_list(media, data, more).render()


@router.route("/search/{media}")
def search_list(media):
    query = router.params.get("query") or keyboard("Search")
    if not query:
        return cancel()
    data = tmdb.search(media, query, page=router.page)
    more = router.url_for("/search/{0}".format(media), query=query, page=router.page + 1)
    _media_list(media, data, more).render()


# ---------------------------------------------------------------------------
# Browse sub-menus (genres / years / languages / networks)
# ---------------------------------------------------------------------------
@router.route("/genres/{media}")
def genres_menu(media):
    Menu(MenuItem(g["name"], router.url_for("/discover/{0}".format(media), with_genres=g["id"]),
                   icon="DefaultGenre.png")
         for g in tmdb.genres(media)).render()


@router.route("/years/{media}")
def years_menu(media):
    field = "primary_release_year" if media == "movie" else "first_air_date_year"
    Menu(MenuItem(str(y), router.url_for("/discover/{0}".format(media), **{field: y}),
                   icon="DefaultYear.png")
         for y in range(date.today().year, 1969, -1)).render()


@router.route("/languages/{media}")
def languages_menu(media):
    Menu(MenuItem(name, router.url_for("/discover/{0}".format(media), with_original_language=code),
                   icon="DefaultAddonLanguage.png")
         for name, code in tmdb.LANGUAGES).render()


@router.route("/networks")
def networks_menu():
    Menu(MenuItem(name, router.url_for("/discover/tv", with_networks=nid),
                   icon="DefaultStudios.png")
         for name, nid in tmdb.NETWORKS).render()


@router.route("/providers/{media}")
def providers_menu(media):
    Menu(MenuItem(name, router.url_for("/discover/{0}".format(media),
                                       with_watch_providers=pid, watch_region="US"),
                  icon="DefaultStudios.png")
         for name, pid in tmdb.PROVIDERS).render()


@router.route("/decades/{media}")
def decades_menu(media):
    gte, lte = (("primary_release_date.gte", "primary_release_date.lte")
                if media == "movie"
                else ("first_air_date.gte", "first_air_date.lte"))
    start = (date.today().year // 10) * 10
    Menu(MenuItem("{0}s".format(d),
                  router.url_for("/discover/{0}".format(media),
                                 **{gte: "{0}-01-01".format(d),
                                    lte: "{0}-12-31".format(d + 9)}),
                  icon="DefaultYear.png")
         for d in range(start, 1899, -10)).render()


@router.route("/certifications/{media}")
def certifications_menu(media):
    Menu(MenuItem(cert, router.url_for("/discover/{0}".format(media),
                                       certification_country="US", certification=cert),
                  icon="DefaultGenre.png")
         for cert in tmdb.CERTIFICATIONS).render()


# ---------------------------------------------------------------------------
# TV drill-down — seasons of a show, episodes of a season
# ---------------------------------------------------------------------------
@router.route("/tv/show/{id}")
def seasons_menu(id):
    details = tmdb.show_details(id)
    show_info, show_art = tmdb.map_show(details, details=details)
    imdb = (details.get("external_ids") or {}).get("imdb_id", "")
    # Per-season watched counts (Trakt) to flag fully-watched seasons; empty when
    # not logged in, so every row falls back to the plain bullet.
    watched = trakt.watched_seasons(int(id)) if trakt.authorized() else {}
    # Seasons (not a plain Menu) so the directory's content type is "seasons" —
    # that's what makes Kodi draw the watched square/checkmark overlay on rows.
    menu = Seasons()
    for season in details.get("seasons", []):
        num = season.get("season_number")
        if not num:  # skip None and 0 ("Specials")
            continue
        aired = season.get("episode_count") or 0
        info = dict(show_info)
        info["season"] = num
        # title defaults to the show name; override so the row reads "Season N"
        # (Kodi shows the VideoInfoTag title over our list label).
        info["title"] = "Season {0}".format(num)
        info["plot"] = season.get("overview") or show_info.get("plot", "")
        # Stamp playcount when the whole season is watched (per Trakt); Kodi then
        # draws the watched checkmark itself, and the unwatched indicator otherwise.
        if aired and watched.get(num, 0) >= aired:
            info["playcount"] = 1
        # Keep poster + fanart for the info panel / background (same as the episode
        # list), but set NO thumb — that's what the list view paints as the row
        # icon, so leaving it out keeps the row free of the poster (Kodi's watched
        # overlay still draws on top).
        art = {"fanart": show_art.get("fanart", ""),
               "poster": (tmdb.image(season["poster_path"])
                          if season.get("poster_path") else show_art.get("poster", ""))}
        url = router.url_for("/tv/show/{0}/season/{1}".format(id, num), imdb=imdb)
        menu.add(Season("Season {0}".format(num), url, id, num,
                        info=info, art=art, media_type="season"))
    menu.render()


@router.route("/tv/show/{id}/season/{season}")
def episodes_list(id, season):
    imdb = router.params.get("imdb", "")
    details = tmdb.show_details(id)
    show_info, show_art = tmdb.map_show(details, details=details)
    show_info["imdb"] = imdb
    data = tmdb.season_details(id, int(season))
    episodes = Episodes()
    for ep in data.get("episodes", []):
        url = router.url_for(
            "/sources/episode/{0}/{1}/{2}".format(id, season, ep.get("episode_number")),
            imdb=imdb)
        episodes.add(Episode(ep, show_info, show_art, url))
    episodes.render()


# ---------------------------------------------------------------------------
# Sources — scrape Stremio add-ons for playable streams, list them as a folder
# ---------------------------------------------------------------------------
def _sources_list(media_type, video_id, resolve_params):
    """Scrape sources for a Stremio id and render them as a playable directory.

    Each row is a Source whose url hits /resolve to turn its infohash into a
    stream URL on click. `resolve_params` (tmdb id, Kodi media type, optional
    season/episode + display title) ride onto every row's url so the played item
    carries the ids the Trakt scrobbler reads off the VideoInfoTag. Rows carry no
    info tag, so Kodi shows the formatted source label instead of a title.
    """
    from resources import scrapers  # lazy — keeps concurrent.futures off the menu path
    if not scrapers.configured():
        notify("Set your TorBox API key in settings")
        return cancel()
    found = scrapers.sources(media_type, video_id)
    if not found:
        notify("No sources found")
        return cancel()
    lst = Sources()
    for s in found:
        label = source_label(s)
        url = router.url_for("/resolve/{0}".format(s.infohash),
                             release=s.title, label=label, **resolve_params)
        lst.add(Source(label, url))
    lst.render()


@router.route("/sources/movie/{id}")
def movie_sources(id):
    details = tmdb.movie_details(id)
    imdb = (details.get("external_ids") or {}).get("imdb_id", "")
    if not imdb:
        notify("No IMDb id for this title")
        return cancel()
    info, _art = tmdb.map_movie(details)
    _sources_list("movie", imdb,
                  {"mediatype": "movie", "tmdb": info.get("tmdb"),
                   "title": info.get("title", "")})


@router.route("/sources/episode/{id}/{season}/{episode}")
def episode_sources(id, season, episode):
    imdb = router.params.get("imdb") or tmdb.imdb_id("tv", id)
    if not imdb:
        notify("No IMDb id for this show")
        return cancel()
    _sources_list("series", "{0}:{1}:{2}".format(imdb, season, episode),
                  {"mediatype": "episode", "tmdb": id,
                   "season": season, "episode": episode})


@router.route("/resolve/{infohash}")
def resolve_source(infohash):
    """Resolve a chosen source's infohash to a stream URL and hand it to Kodi.

    Sources were filtered to TorBox-cached hashes at scrape time, so this is the
    ~1s fast path — resolve on this thread under a spinner so Kodi opens a final
    link instead of freezing; it can still fail if the transfer add/link errors.
    The played item carries the tmdb id (+ season/episode) so the scrobbler can
    identify it; rows passed no title for episodes, so the source label shows.
    """
    p = router.params
    from resources import torbox  # lazy — only needed at play time
    with busy():
        url = torbox.resolve(infohash, p.get("release", ""))
    if not url:
        notify("Couldn't resolve source")
        return set_resolved(None)
    info = {"tmdb": p.get("tmdb")}
    if p.get("title"):
        info["title"] = p["title"]
    if p.get("season"):
        info["season"] = int(p["season"])
        info["episode"] = int(p["episode"])
    item = Item(p.get("label", ""), url, info=info,
                media_type=p.get("mediatype", "video"),
                is_folder=False, is_playable=True)
    set_resolved(item)


# ---------------------------------------------------------------------------
# Trakt — personalised lists (hydrated via TMDB) + watchlist/watched writes
# ---------------------------------------------------------------------------
def _hydrate(media, tmdb_ids):
    """Fetch TMDB details for ids in parallel and build Movie/Show rows,
    stamping a Trakt-backed playcount so watched items render as watched."""
    from concurrent.futures import ThreadPoolExecutor  # lazy — only Trakt lists need it
    fetch = tmdb.movie_details if media == "movie" else tmdb.show_details
    with ThreadPoolExecutor(max_workers=10) as pool:
        details = list(pool.map(fetch, tmdb_ids))
    # One cached Trakt call per render; movies use plays, shows are watched only if complete.
    watched = trakt.watched_movie_plays() if media == "movie" else trakt.watched_show_episodes()
    rows = []
    for data in details:
        if not data:
            continue
        if media == "movie":
            item = Movie(data, router.url_for("/sources/movie/{0}".format(data["id"])))
            plays = watched.get(data["id"])
            if plays:
                item.info["playcount"] = plays
        else:
            item = Show(data, router.url_for("/tv/show/{0}".format(data["id"])))
            # Trakt's watched count carries no aired total — compare against TMDB's.
            # Specials/numbering mismatches can leave a show one short of "complete".
            total = data.get("number_of_episodes") or 0
            if total and watched.get(data["id"], 0) >= total:
                item.info["playcount"] = 1
        rows.append(item)
    return rows


def _trakt_list(media, fetch):
    """Render a Trakt list (a fetch callable) as Movies/Shows, or notify why not."""
    if not trakt.authorized():
        notify("Authorize Trakt in Tools first")
        return cancel()
    rows = _hydrate(media, trakt.tmdb_ids(fetch(), media))
    if not rows:
        notify("Nothing here yet")
        return cancel()
    (Movies if media == "movie" else Shows)(rows).render()


@router.route("/trakt/watchlist/{media}")
def trakt_watchlist(media):
    _trakt_list(media, lambda: trakt.watchlist(media))


@router.route("/trakt/recommended/{media}")
def trakt_recommended(media):
    _trakt_list(media, lambda: trakt.recommendations(media))


@router.route("/trakt/most-watched/{media}")
def trakt_most_watched(media):
    _trakt_list(media, lambda: trakt.most_watched(media))


@router.route("/trakt/progress/{media}")
def trakt_progress(media):
    _trakt_list(media, lambda: trakt.in_progress(media))


@router.route("/trakt/boxoffice")
def trakt_boxoffice():
    _trakt_list("movie", trakt.box_office)


@router.route("/trakt/because/{media}")
def trakt_because(media):
    _trakt_list(media, lambda: trakt.because_you_watched(media))


@router.route("/trakt/because-random/{media}")
def trakt_because_random(media):
    _trakt_list(media, lambda: trakt.because_you_watched(media, shuffle=True))


@router.route("/trakt/progress-episodes")
def trakt_progress_episodes():
    if not trakt.authorized():
        notify("Authorize Trakt in Tools first")
        return cancel()
    rows = Episodes()
    for entry in trakt.in_progress_episodes():
        show, ep = entry.get("show") or {}, entry.get("episode") or {}
        ids = show.get("ids") or {}
        tmdb_id, season, num = ids.get("tmdb"), ep.get("season"), ep.get("number")
        if not (tmdb_id and season and num):
            continue
        label = "{0} - {1}x{2:02d}".format(show.get("title", ""), season, num)
        url = router.url_for("/sources/episode/{0}/{1}/{2}".format(tmdb_id, season, num),
                             imdb=ids.get("imdb", ""))
        rows.add(MenuItem(label, url, icon="DefaultInProgressShows.png"))
    if not rows.items:
        notify("Nothing in progress")
        return cancel()
    rows.render()


# -- Trakt writes (context-menu actions; RunPlugin, no listing) --------------
def _trakt_write(ok_msg, action, *args):
    if not trakt.authorized():
        return notify("Authorize Trakt in Tools first")
    notify(ok_msg if action(*args) else "Trakt action failed")


@router.route("/trakt/watchlist-add")
def trakt_watchlist_add():
    _trakt_write("Added to Trakt watchlist", trakt.set_watchlist, router.params, True)


@router.route("/trakt/watchlist-remove")
def trakt_watchlist_remove():
    _trakt_write("Removed from Trakt watchlist", trakt.set_watchlist, router.params, False)


@router.route("/trakt/watched-add")
def trakt_watched_add():
    _trakt_write("Marked watched on Trakt", trakt.set_watched, router.params, True)


@router.route("/trakt/watched-remove")
def trakt_watched_remove():
    _trakt_write("Marked unwatched on Trakt", trakt.set_watched, router.params, False)


@router.route("/trakt/authorize")
def trakt_authorize():
    trakt.authorize()
    cancel()


@router.route("/trakt/signout")
def trakt_signout():
    trakt.sign_out()
    notify("Signed out of Trakt")
    cancel()


# ---------------------------------------------------------------------------
# Placeholders — menu entries for features not built yet
# ---------------------------------------------------------------------------
@router.route("/coming-soon")
def coming_soon():
    notify("{0}: coming soon".format(router.params.get("feature", "This feature")))
    cancel()


# ---------------------------------------------------------------------------
# Tool actions
# ---------------------------------------------------------------------------
@router.route("/settings")
def settings():
    open_settings()
    cancel()


@router.route("/clear-cache")
def clear_cache():
    cache.clear()
    notify("Cache cleared")
    cancel()
