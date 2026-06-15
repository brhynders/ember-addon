"""Addon-side List and Item types — build the rows the framework renders.

The framework is generic; the domain lives here. An *Item* builds one row dict
(via `.row()`); a *List* collects Items, carries its Kodi content type, and
renders the whole directory in one call:

    Episodes(Episode(ep, show_info, show_art, url) for ep in episodes).render()
    Menu([Directory("Movies", plugin.url_for("/movies"), icon="...")]).render()

Route handlers build the target URLs themselves (plugin.url_for) and pass them
in — Items don't know the route map. Movie/Show/Episode wrap the TMDB mappers so
a handler just feeds raw API dicts plus the link to follow.
"""
from resources import tmdb
from resources.framework import plugin


# ===========================================================================
# Item types — each builds a single row dict
# ===========================================================================
class Item:
    """One list item. Subclasses set the folder/playable/media-type defaults."""
    is_folder = True
    is_playable = False
    media_type = "video"

    def __init__(self, label, url, icon=None, info=None, art=None,
                 media_type=None, is_folder=None, is_playable=None,
                 properties=None, context_menu=None):
        self.label = label
        self.url = url
        self.icon = icon
        self.info = info
        self.art = art
        self.properties = properties
        self.context_menu = context_menu
        if media_type is not None:
            self.media_type = media_type
        if is_folder is not None:
            self.is_folder = is_folder
        if is_playable is not None:
            self.is_playable = is_playable

    def row(self):
        return {
            "label": self.label, "url": self.url, "icon": self.icon,
            "is_folder": self.is_folder, "is_playable": self.is_playable,
            "info": self.info, "art": self.art, "media_type": self.media_type,
            "properties": self.properties, "context_menu": self.context_menu,
        }


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
# List types — collect Items, carry a content type, render the directory
# ===========================================================================
class List:
    """A directory listing: a content type + a collection of Items."""
    content = ""

    def __init__(self, items=()):
        self.items = []
        for item in items:
            self.add(item)

    def add(self, item):
        """Append an Item, skipping anything without a label (e.g. title-less)."""
        if item is not None and item.label:
            self.items.append(item)
        return self

    def next_page(self, url):
        """Append a 'Next Page' folder entry pointing at `url`."""
        self.items.append(Directory("Next Page >>", url, icon=plugin.icon))
        return self

    def render(self):
        plugin.finish([item.row() for item in self.items], content=self.content)


class Menu(List):
    """A navigation menu — plain folder entries, no media content type."""
    content = ""


class Movies(List):
    content = "movies"


class Shows(List):
    content = "tvshows"


class Episodes(List):
    content = "episodes"
