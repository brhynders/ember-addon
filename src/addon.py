"""Ember entry point — defines the menu tree and runs it.

The provider/folder/callback handlers live in their own modules; importing them
here registers their routes on the shared plugin. addon.py only describes the
navigation (the MENU tree) and runs.
"""
from resources import playback, tmdb  # noqa: F401 — imports register the routes
from resources.framework import Action, Folder, MediaList, Search, plugin

MENU = Folder("Home", children=[
    Folder("Movies", icon="DefaultMovies.png", children=[
        Search("Search", "tmdb.search", content="movies", icon="DefaultAddonsSearch.png", params={"media": "movie"}),
        MediaList("Trending", "tmdb.movies", icon="DefaultRecentlyAddedMovies.png", params={"category": "trending"}),
        MediaList("Popular", "tmdb.movies", icon="DefaultFavourites.png", params={"category": "popular"}),
        MediaList("In Theaters", "tmdb.movies", icon="DefaultInProgressShows.png", params={"category": "now_playing"}),
        MediaList("Top Rated", "tmdb.movies", icon="DefaultMusicTop100.png", params={"category": "top_rated"}),
        MediaList("Upcoming", "tmdb.movies", icon="DefaultYear.png", params={"category": "upcoming"}),
        MediaList("Premieres", "tmdb.named", icon="DefaultRecentlyAddedMovies.png", params={"media": "movie", "key": "premieres"}),
        MediaList("Most Voted", "tmdb.named", icon="DefaultMusicTop100.png", params={"media": "movie", "key": "most_voted"}),
        MediaList("Blockbusters", "tmdb.named", icon="DefaultMovies.png", params={"media": "movie", "key": "blockbusters"}),
        Folder("Genres", provider="tmdb.genres", icon="DefaultGenre.png", params={"media": "movie"}),
        Folder("Years", provider="tmdb.years", icon="DefaultYear.png", params={"media": "movie"}),
        Folder("Languages", provider="tmdb.languages", icon="DefaultAddonLanguage.png", params={"media": "movie"}),
    ]),
    Folder("TV Shows", icon="DefaultTVShows.png", children=[
        Search("Search", "tmdb.search", content="tvshows", icon="DefaultAddonsSearch.png", params={"media": "tv"}),
        MediaList("Trending", "tmdb.shows", content="tvshows", icon="DefaultRecentlyAddedMovies.png", params={"category": "trending"}),
        MediaList("Popular", "tmdb.shows", content="tvshows", icon="DefaultFavourites.png", params={"category": "popular"}),
        MediaList("On The Air", "tmdb.shows", content="tvshows", icon="DefaultInProgressShows.png", params={"category": "on_the_air"}),
        MediaList("Airing Today", "tmdb.shows", content="tvshows", icon="DefaultInProgressShows.png", params={"category": "airing_today"}),
        MediaList("Top Rated", "tmdb.shows", content="tvshows", icon="DefaultMusicTop100.png", params={"category": "top_rated"}),
        MediaList("Most Voted", "tmdb.named", content="tvshows", icon="DefaultMusicTop100.png", params={"media": "tv", "key": "most_voted"}),
        Folder("Genres", provider="tmdb.genres", icon="DefaultGenre.png", params={"media": "tv"}),
        Folder("Networks", provider="tmdb.networks", icon="DefaultStudios.png"),
        Folder("Years", provider="tmdb.years", icon="DefaultYear.png", params={"media": "tv"}),
        Folder("Languages", provider="tmdb.languages", icon="DefaultAddonLanguage.png", params={"media": "tv"}),
    ]),
    Folder("Tools", icon="DefaultAddonProgram.png", children=[
        Action("Settings", "settings", icon="DefaultAddonService.png"),
        Action("Clear Cache", "clear_cache", icon="DefaultAddonProgram.png"),
    ]),
])
plugin.menu(MENU)

if __name__ == "__main__":
    plugin.run()
