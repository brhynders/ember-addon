"""Ember entry point — the route handlers and the run loop.

Every screen in the add-on is a `@plugin.route(...)` handler here: it fetches
from TMDB (resources/tmdb.py), builds a List of Items (resources/ui.py) linking
to other routes, and renders. The framework (resources/framework.py) only does
routing + rendering; importing `playback` registers its /play routes too.
"""
from datetime import date

from resources import playback, tmdb  # noqa: F401 — playback import registers routes
from resources.framework import plugin
from resources.ui import Directory, Episode, Episodes, Menu, Movie, Movies, Show, Shows, cancel


# ---------------------------------------------------------------------------
# Shared list builder — turn a TMDB list response into a paginated Movies/Shows
# ---------------------------------------------------------------------------
def _media_list(media, data, more_url):
    results = data.get("results", [])
    gmap = tmdb.genre_map(media)
    if media == "movie":
        lst = Movies(Movie(it, plugin.url_for("/play/movie/{0}".format(it["id"])), gmap)
                     for it in results)
    else:
        lst = Shows(Show(it, plugin.url_for("/tv/show/{0}".format(it["id"])), gmap)
                    for it in results)
    if plugin.page < tmdb.total(data):
        lst.next_page(more_url)
    return lst


# ---------------------------------------------------------------------------
# Home + top-level menus
# ---------------------------------------------------------------------------
@plugin.route("/")
def home():
    Menu([
        Directory("Movies", plugin.url_for("/movies"), icon="DefaultMovies.png"),
        Directory("TV Shows", plugin.url_for("/tv"), icon="DefaultTVShows.png"),
        Directory("Tools", plugin.url_for("/tools"), icon="DefaultAddonProgram.png"),
    ]).render()


@plugin.route("/movies")
def movies_menu():
    Menu([
        Directory("Search", plugin.url_for("/search/movie"), icon="DefaultAddonsSearch.png"),
        Directory("Trending", plugin.url_for("/list/movie/trending"), icon="DefaultRecentlyAddedMovies.png"),
        Directory("Popular", plugin.url_for("/list/movie/popular"), icon="DefaultFavourites.png"),
        Directory("In Theaters", plugin.url_for("/list/movie/now_playing"), icon="DefaultInProgressShows.png"),
        Directory("Top Rated", plugin.url_for("/list/movie/top_rated"), icon="DefaultMusicTop100.png"),
        Directory("Upcoming", plugin.url_for("/list/movie/upcoming"), icon="DefaultYear.png"),
        Directory("Premieres", plugin.url_for("/named/movie/premieres"), icon="DefaultRecentlyAddedMovies.png"),
        Directory("Most Voted", plugin.url_for("/named/movie/most_voted"), icon="DefaultMusicTop100.png"),
        Directory("Blockbusters", plugin.url_for("/named/movie/blockbusters"), icon="DefaultMovies.png"),
        Directory("Genres", plugin.url_for("/genres/movie"), icon="DefaultGenre.png"),
        Directory("Years", plugin.url_for("/years/movie"), icon="DefaultYear.png"),
        Directory("Languages", plugin.url_for("/languages/movie"), icon="DefaultAddonLanguage.png"),
    ]).render()


@plugin.route("/tv")
def tv_menu():
    Menu([
        Directory("Search", plugin.url_for("/search/tv"), icon="DefaultAddonsSearch.png"),
        Directory("Trending", plugin.url_for("/list/tv/trending"), icon="DefaultRecentlyAddedMovies.png"),
        Directory("Popular", plugin.url_for("/list/tv/popular"), icon="DefaultFavourites.png"),
        Directory("On The Air", plugin.url_for("/list/tv/on_the_air"), icon="DefaultInProgressShows.png"),
        Directory("Airing Today", plugin.url_for("/list/tv/airing_today"), icon="DefaultInProgressShows.png"),
        Directory("Top Rated", plugin.url_for("/list/tv/top_rated"), icon="DefaultMusicTop100.png"),
        Directory("Most Voted", plugin.url_for("/named/tv/most_voted"), icon="DefaultMusicTop100.png"),
        Directory("Genres", plugin.url_for("/genres/tv"), icon="DefaultGenre.png"),
        Directory("Networks", plugin.url_for("/networks"), icon="DefaultStudios.png"),
        Directory("Years", plugin.url_for("/years/tv"), icon="DefaultYear.png"),
        Directory("Languages", plugin.url_for("/languages/tv"), icon="DefaultAddonLanguage.png"),
    ]).render()


@plugin.route("/tools")
def tools_menu():
    Menu([
        Directory("Settings", plugin.url_for("/settings"), icon="DefaultAddonService.png"),
        Directory("Clear Cache", plugin.url_for("/clear-cache"), icon="DefaultAddonProgram.png"),
    ]).render()


# ---------------------------------------------------------------------------
# Media listings
# ---------------------------------------------------------------------------
@plugin.route("/list/{media}/{category}")
def category_list(media, category):
    data = (tmdb.movies if media == "movie" else tmdb.shows)(category, page=plugin.page)
    more = plugin.url_for("/list/{0}/{1}".format(media, category), page=plugin.page + 1)
    _media_list(media, data, more).render()


@plugin.route("/named/{media}/{key}")
def named_list(media, key):
    disc = dict(tmdb.NAMED.get((media, key), {}))
    if key == "premieres":
        disc["release_date.lte"] = date.today().isoformat()
    data = tmdb.discover(media, page=plugin.page, **disc)
    more = plugin.url_for("/named/{0}/{1}".format(media, key), page=plugin.page + 1)
    _media_list(media, data, more).render()


@plugin.route("/discover/{media}")
def discover_list(media):
    filters = dict(plugin.params)  # genre / year / language / network filters
    data = tmdb.discover(media, page=plugin.page, **filters)
    more = plugin.url_for("/discover/{0}".format(media), page=plugin.page + 1, **filters)
    _media_list(media, data, more).render()


@plugin.route("/search/{media}")
def search_list(media):
    query = plugin.params.get("query") or plugin.keyboard("Search")
    if not query:
        return cancel()
    data = tmdb.search(media, query, page=plugin.page)
    more = plugin.url_for("/search/{0}".format(media), query=query, page=plugin.page + 1)
    _media_list(media, data, more).render()


# ---------------------------------------------------------------------------
# Browse sub-menus (genres / years / languages / networks)
# ---------------------------------------------------------------------------
@plugin.route("/genres/{media}")
def genres_menu(media):
    Menu(Directory(g["name"], plugin.url_for("/discover/{0}".format(media), with_genres=g["id"]),
                   icon="DefaultGenre.png")
         for g in tmdb.genres(media)).render()


@plugin.route("/years/{media}")
def years_menu(media):
    field = "primary_release_year" if media == "movie" else "first_air_date_year"
    Menu(Directory(str(y), plugin.url_for("/discover/{0}".format(media), **{field: y}),
                   icon="DefaultYear.png")
         for y in range(date.today().year, 1969, -1)).render()


@plugin.route("/languages/{media}")
def languages_menu(media):
    Menu(Directory(name, plugin.url_for("/discover/{0}".format(media), with_original_language=code),
                   icon="DefaultAddonLanguage.png")
         for name, code in tmdb.LANGUAGES).render()


@plugin.route("/networks")
def networks_menu():
    Menu(Directory(name, plugin.url_for("/discover/tv", with_networks=nid),
                   icon="DefaultStudios.png")
         for name, nid in tmdb.NETWORKS).render()


# ---------------------------------------------------------------------------
# TV drill-down — seasons of a show, episodes of a season
# ---------------------------------------------------------------------------
@plugin.route("/tv/show/{id}")
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
        url = plugin.url_for("/tv/show/{0}/season/{1}".format(id, num),
                             show_title=show_info["title"],
                             year=show_info.get("year", ""), imdb=imdb)
        menu.add(Directory("Season {0}".format(num), url, info=info, art=art,
                           media_type="season"))
    menu.render()


@plugin.route("/tv/show/{id}/season/{season}")
def episodes_list(id, season):
    show_title = plugin.params.get("show_title", "")
    year, imdb = plugin.params.get("year", ""), plugin.params.get("imdb", "")
    details = tmdb.show_details(id)
    show_info, show_art = tmdb.map_show(details, details=details)
    show_info["imdb"] = imdb
    data = tmdb.season_details(id, int(season))
    episodes = Episodes()
    for ep in data.get("episodes", []):
        url = plugin.url_for(
            "/play/episode/{0}/{1}/{2}".format(id, season, ep.get("episode_number")),
            show_title=show_title, year=year, imdb=imdb)
        episodes.add(Episode(ep, show_info, show_art, url))
    episodes.render()


# ---------------------------------------------------------------------------
# Tool actions
# ---------------------------------------------------------------------------
@plugin.route("/settings")
def settings():
    plugin.open_settings()
    cancel()


@plugin.route("/clear-cache")
def clear_cache():
    plugin.clear_cache()
    plugin.notify("Cache cleared")
    cancel()


if __name__ == "__main__":
    plugin.run()
