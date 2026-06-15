"""Ember entry point — the route handlers and the run loop.

Every route handler in the add-on lives here (the only module with
`@router.route`): each fetches from TMDB (resources/tmdb.py), builds a List of
Items (resources/ui.py) linking to other routes, and renders. The framework
(resources/framework.py) only does routing + rendering; playback resolution
mechanics live in resources/playback.py, which the /play handlers call.
"""
from datetime import date

from resources import playback, tmdb
from resources.framework import cache, keyboard, notify, open_settings, router
from resources.ui import Episode, Episodes, Menu, MenuItem, Movie, Movies, Show, Shows, cancel


# ---------------------------------------------------------------------------
# Shared list builder — turn a TMDB list response into a paginated Movies/Shows
# ---------------------------------------------------------------------------
def _media_list(media, data, more_url):
    results = data.get("results", [])
    gmap = tmdb.genre_map(media)
    if media == "movie":
        lst = Movies(Movie(it, router.url_for("/play/movie/{0}".format(it["id"])), gmap)
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
    ("In Progress", None, "DefaultInProgressShows.png"),
    ("Movie Watchlist", None, "DefaultPlaylist.png"),
    ("Because You Watched", None, "DefaultMovies.png"),
    ("Trakt Recommended", None, "DefaultAddonInfoProvider.png"),
    ("Random Because You Watched", None, "DefaultMovies.png"),
    ("Trending Recently", "/list/movie/trending", "DefaultRecentlyAddedMovies.png"),
    ("Premieres", "/named/movie/premieres", "DefaultRecentlyAddedMovies.png"),
    ("Latest Releases", "/named/movie/latest_releases", "DefaultRecentlyAddedMovies.png"),
    ("Most Watched", None, "DefaultMusicTop100.png"),
    ("Most Favorited", "/named/movie/most_voted", "DefaultFavourites.png"),
    ("Top 10 Box Office", None, "DefaultMusicTop100.png"),
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
    ("In Progress", None, "DefaultInProgressShows.png"),
    ("In Progress Episodes", None, "DefaultInProgressShows.png"),
    ("TV Shows Watchlist", None, "DefaultPlaylist.png"),
    ("Because You Watched", None, "DefaultTVShows.png"),
    ("Trakt Recommended", None, "DefaultAddonInfoProvider.png"),
    ("Random Because You Watched", None, "DefaultTVShows.png"),
    ("Trending Recently", "/list/tv/trending", "DefaultRecentlyAddedMovies.png"),
    ("Premieres", "/named/tv/premieres", "DefaultRecentlyAddedMovies.png"),
    ("Most Watched", None, "DefaultMusicTop100.png"),
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
    Menu([
        MenuItem("Settings", router.url_for("/settings"), icon="DefaultAddonService.png"),
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
    menu = Menu()
    for season in details.get("seasons", []):
        num = season.get("season_number")
        if not num:  # skip None and 0 ("Specials")
            continue
        info = dict(show_info)
        info["season"] = num
        info["plot"] = season.get("overview") or show_info.get("plot", "")
        art = dict(show_art)
        if season.get("poster_path"):
            art["poster"] = art["thumb"] = tmdb.image(season["poster_path"])
        url = router.url_for("/tv/show/{0}/season/{1}".format(id, num),
                             show_title=show_info["title"],
                             year=show_info.get("year", ""), imdb=imdb)
        menu.add(MenuItem("Season {0}".format(num), url, info=info, art=art,
                           media_type="season"))
    menu.render()


@router.route("/tv/show/{id}/season/{season}")
def episodes_list(id, season):
    show_title = router.params.get("show_title", "")
    year, imdb = router.params.get("year", ""), router.params.get("imdb", "")
    details = tmdb.show_details(id)
    show_info, show_art = tmdb.map_show(details, details=details)
    show_info["imdb"] = imdb
    data = tmdb.season_details(id, int(season))
    episodes = Episodes()
    for ep in data.get("episodes", []):
        url = router.url_for(
            "/play/episode/{0}/{1}/{2}".format(id, season, ep.get("episode_number")),
            show_title=show_title, year=year, imdb=imdb)
        episodes.add(Episode(ep, show_info, show_art, url))
    episodes.render()


# ---------------------------------------------------------------------------
# Playback — resolve a media row's /play URL (placeholder until wired up)
# ---------------------------------------------------------------------------
@router.route("/play/movie/{id}")
def play_movie(id):
    notify("Playback isn't wired up yet")
    playback.resolve(None)


@router.route("/play/episode/{id}/{season}/{episode}")
def play_episode(id, season, episode):
    notify("Playback isn't wired up yet")
    playback.resolve(None)


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


if __name__ == "__main__":
    router.run()
