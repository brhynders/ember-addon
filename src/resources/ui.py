"""Add-on List and Item types — TMDB-backed subclasses of the framework bases.

The framework owns generic directory rendering (resources/framework/ui.py);
here we subclass its Item/List to wrap raw TMDB result dicts into rows:

    Episodes(Episode(ep, show_info, show_art, url) for ep in episodes).render()
    Menu([Directory("Movies", router.url_for("/movies"), icon="...")]).render()

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


# ===========================================================================
# Item subclasses — each sets folder/playable/media-type and wraps a mapper
# ===========================================================================
class Directory(Item):
    """A folder entry that opens another route (menu items, sub-listings)."""
    is_folder = True
    is_playable = False


class Movie(Item):
    """A playable movie row built from a raw TMDB result dict."""
    is_folder = False
    is_playable = True
    media_type = "movie"

    def __init__(self, data, url, gmap=None):
        info, art = tmdb.map_movie(data, gmap=gmap)
        super().__init__(info.get("title", ""), url, info=info, art=art)


class Show(Item):
    """A TV show row (a folder of seasons) built from a raw TMDB result dict."""
    is_folder = True
    is_playable = False
    media_type = "tvshow"

    def __init__(self, data, url, gmap=None):
        info, art = tmdb.map_show(data, gmap=gmap)
        super().__init__(info.get("title", ""), url, info=info, art=art)


class Episode(Item):
    """A playable episode row built from a raw TMDB episode dict + show context."""
    is_folder = False
    is_playable = True
    media_type = "episode"

    def __init__(self, ep, show_info, show_art, url):
        info, art = tmdb.map_episode(ep, show_info, show_art)
        label = "{0}x{1:02d}. {2}".format(
            info.get("season") or 0, info.get("episode") or 0, info.get("title", ""))
        super().__init__(label, url, info=info, art=art)


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
