"""Add-on List and Item types — TMDB-backed subclasses of the framework bases.

The framework owns generic directory rendering (resources/framework.py);
here we subclass its Item/List to wrap raw TMDB result dicts into rows:

    Episodes(Episode(ep, show_info, show_art, url) for ep in episodes).render()
    Menu([MenuItem("Movies", router.url_for("/movies"), icon="...")]).render()

Route handlers build the target URLs themselves (router.url_for) and pass them
in — Items don't know the route map. Movie/Show/Episode wrap the TMDB mappers so
a handler just feeds raw API dicts plus the link to follow. Context-menu entries
are declared by overriding Item.context_menu(), not passed to the constructor.
"""
import xbmcplugin

from resources import tmdb
from resources.framework import Item, List, router


def cancel():
    """End the current navigation without a listing (cancelled action/search)."""
    xbmcplugin.endOfDirectory(router.handle, succeeded=False)


def _ctx(label, path, **params):
    """A context-menu entry: (label, RunPlugin(url)) for a Trakt action route."""
    return (label, "RunPlugin({0})".format(router.url_for(path, **params)))


def _watchlist_ctx(kind, tmdb):
    return [_ctx("Trakt: Add to Watchlist", "/trakt/watchlist-add", type=kind, tmdb=tmdb),
            _ctx("Trakt: Remove from Watchlist", "/trakt/watchlist-remove", type=kind, tmdb=tmdb)]


def _watched_ctx(label, **params):
    label = (label + " ") if label else ""
    return [_ctx("Trakt: Mark {0}Watched".format(label), "/trakt/watched-add", **params),
            _ctx("Trakt: Mark {0}Unwatched".format(label), "/trakt/watched-remove", **params)]


# ===========================================================================
# Item subclasses — each sets folder/playable/media-type and wraps a mapper
# ===========================================================================
class MenuItem(Item):
    """A folder entry that opens another route (menu items, sub-listings)."""
    is_folder = True
    is_playable = False


class Movie(Item):
    """A movie row built from a raw TMDB result dict. A folder: opens its
    sources list (scraped streams), where the actual playback happens."""
    is_folder = True
    is_playable = False
    media_type = "movie"

    def __init__(self, data, url, gmap=None):
        info, art = tmdb.map_movie(data, gmap=gmap)
        self.tmdb = info.get("tmdb")
        super().__init__(info.get("title", ""), url, info=info, art=art)

    def context_menu(self):
        return _watchlist_ctx("movie", self.tmdb) + \
            _watched_ctx("", type="movie", tmdb=self.tmdb)


class Show(Item):
    """A TV show row (a folder of seasons) built from a raw TMDB result dict."""
    is_folder = True
    is_playable = False
    media_type = "tvshow"

    def __init__(self, data, url, gmap=None):
        info, art = tmdb.map_show(data, gmap=gmap)
        self.tmdb = info.get("tmdb")
        super().__init__(info.get("title", ""), url, info=info, art=art)

    def context_menu(self):
        return _watchlist_ctx("show", self.tmdb) + \
            _watched_ctx("Show", type="show", tmdb=self.tmdb)


class Source(Item):
    """A scraped stream row: playable, with no info tag so the row keeps showing
    its source label (Kodi paints a VideoInfoTag title over the list label). The
    url points at /resolve, which turns the infohash into a stream URL on click."""
    is_folder = False
    is_playable = True


class Season(MenuItem):
    """A season folder (opens its episodes). Carries show id + season number
    so it can offer mark-watched/unwatched for the whole season."""

    def __init__(self, label, url, show_tmdb, season, **kwargs):
        super().__init__(label, url, **kwargs)
        self.show_tmdb = show_tmdb
        self.season = season

    def context_menu(self):
        return _watched_ctx("Season", type="season", tmdb=self.show_tmdb,
                            season=self.season)


class Episode(Item):
    """An episode row built from a raw TMDB episode dict + show context. A
    folder: opens its sources list, where the actual playback happens."""
    is_folder = True
    is_playable = False
    media_type = "episode"

    def __init__(self, ep, show_info, show_art, url):
        info, art = tmdb.map_episode(ep, show_info, show_art)
        self.show_tmdb = show_info.get("tmdb")
        self.season = info.get("season")
        self.episode = info.get("episode")
        label = "{0}x{1:02d}. {2}".format(
            info.get("season") or 0, info.get("episode") or 0, info.get("title", ""))
        # Kodi shows the VideoInfoTag title over our list label, so bake the
        # season/episode prefix into the title too (else rows show only the name).
        info["title"] = label
        super().__init__(label, url, info=info, art=art)

    def context_menu(self):
        return _watched_ctx("Episode", type="episode", tmdb=self.show_tmdb,
                            season=self.season, episode=self.episode)


# ===========================================================================
# List subclasses — each just carries its Kodi content type
# ===========================================================================
class Menu(List):
    """A navigation menu — plain folder entries, no media content type."""
    content = ""


class Movies(List):
    content = "movies"


class Shows(List):
    content = "tvshows"


class Episodes(List):
    content = "episodes"


class Sources(List):
    """The scraped-streams directory for one title — playable Source rows."""
    content = "videos"


def _gb(size):
    return "{0:.2f} GB".format(size / 1073741824.0) if size else ""


def source_label(stream):
    """The display string for one scraped source, shown in the picker dialog:

        1080p BluRay HDR  ·  2.45 GB  ·  English/French  ·  Torrentio
    """
    head = " ".join([stream.quality] + stream.tags)
    langs = "/".join(stream.languages[:3]) if stream.languages else ""
    return "  ·  ".join(p for p in (
        head, _gb(stream.size), langs, stream.scraper) if p)
