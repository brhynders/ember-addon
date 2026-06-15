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


@router.route("/movies")
def movies_menu():
    Menu([
        MenuItem("Search", router.url_for("/search/movie"), icon="DefaultAddonsSearch.png"),
        MenuItem("Trending", router.url_for("/list/movie/trending"), icon="DefaultRecentlyAddedMovies.png"),
        MenuItem("Popular", router.url_for("/list/movie/popular"), icon="DefaultFavourites.png"),
        MenuItem("In Theaters", router.url_for("/list/movie/now_playing"), icon="DefaultInProgressShows.png"),
        MenuItem("Top Rated", router.url_for("/list/movie/top_rated"), icon="DefaultMusicTop100.png"),
        MenuItem("Upcoming", router.url_for("/list/movie/upcoming"), icon="DefaultYear.png"),
        MenuItem("Premieres", router.url_for("/named/movie/premieres"), icon="DefaultRecentlyAddedMovies.png"),
        MenuItem("Most Voted", router.url_for("/named/movie/most_voted"), icon="DefaultMusicTop100.png"),
        MenuItem("Blockbusters", router.url_for("/named/movie/blockbusters"), icon="DefaultMovies.png"),
        MenuItem("Genres", router.url_for("/genres/movie"), icon="DefaultGenre.png"),
        MenuItem("Years", router.url_for("/years/movie"), icon="DefaultYear.png"),
        MenuItem("Languages", router.url_for("/languages/movie"), icon="DefaultAddonLanguage.png"),
    ]).render()


@router.route("/tv")
def tv_menu():
    Menu([
        MenuItem("Search", router.url_for("/search/tv"), icon="DefaultAddonsSearch.png"),
        MenuItem("Trending", router.url_for("/list/tv/trending"), icon="DefaultRecentlyAddedMovies.png"),
        MenuItem("Popular", router.url_for("/list/tv/popular"), icon="DefaultFavourites.png"),
        MenuItem("On The Air", router.url_for("/list/tv/on_the_air"), icon="DefaultInProgressShows.png"),
        MenuItem("Airing Today", router.url_for("/list/tv/airing_today"), icon="DefaultInProgressShows.png"),
        MenuItem("Top Rated", router.url_for("/list/tv/top_rated"), icon="DefaultMusicTop100.png"),
        MenuItem("Most Voted", router.url_for("/named/tv/most_voted"), icon="DefaultMusicTop100.png"),
        MenuItem("Genres", router.url_for("/genres/tv"), icon="DefaultGenre.png"),
        MenuItem("Networks", router.url_for("/networks"), icon="DefaultStudios.png"),
        MenuItem("Years", router.url_for("/years/tv"), icon="DefaultYear.png"),
        MenuItem("Languages", router.url_for("/languages/tv"), icon="DefaultAddonLanguage.png"),
    ]).render()


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
    disc = dict(tmdb.NAMED.get((media, key), {}))
    if key == "premieres":
        disc["release_date.lte"] = date.today().isoformat()
    data = tmdb.discover(media, page=router.page, **disc)
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
