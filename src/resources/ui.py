"""Addon-side List and Item types — own all directory rendering.

The framework is generic (routing only); everything about *listings* lives
here. An *Item* builds its own xbmcgui.ListItem (and declares its own context
menu); a *List* collects Items, carries its Kodi content type, and renders the
whole directory — addDirectoryItems + endOfDirectory — in one .render() call:

    Episodes(Episode(ep, show_info, show_art, url) for ep in episodes).render()
    Menu([Directory("Movies", plugin.url_for("/movies"), icon="...")]).render()

Route handlers build the target URLs themselves (plugin.url_for) and pass them
in — Items don't know the route map. Movie/Show/Episode wrap the TMDB mappers so
a handler just feeds raw API dicts plus the link to follow. Context-menu entries
are declared by overriding Item.context_menu(), not passed to the constructor.
"""
import xbmcgui
import xbmcplugin

from resources import tmdb
from resources.framework import plugin


def _apply_info(li, info, media_type):
    """Apply a metadata dict via the InfoTagVideo API (setInfo is deprecated)."""
    tag = li.getVideoInfoTag()
    tag.setMediaType(media_type)
    if info.get("title"):
        tag.setTitle(info["title"])
    if info.get("plot"):
        tag.setPlot(info["plot"])
    if info.get("genres"):
        tag.setGenres(info["genres"])
    if info.get("premiered"):
        tag.setPremiered(info["premiered"])
    if info.get("tvshowtitle"):
        tag.setTvShowTitle(info["tvshowtitle"])
    if info.get("year"):
        try:
            tag.setYear(int(info["year"]))
        except (ValueError, TypeError):
            pass
    if info.get("rating"):
        try:
            tag.setRating(float(info["rating"]))
        except (ValueError, TypeError):
            pass
    if info.get("duration"):
        try:
            tag.setDuration(int(info["duration"]))
        except (ValueError, TypeError):
            pass
    if info.get("season") is not None:
        try:
            tag.setSeason(int(info["season"]))
        except (ValueError, TypeError):
            pass
    if info.get("episode") is not None:
        try:
            tag.setEpisode(int(info["episode"]))
        except (ValueError, TypeError):
            pass
    if info.get("imdb"):
        tag.setUniqueID(info["imdb"], "imdb")
    if info.get("tmdb"):
        tag.setUniqueID(str(info["tmdb"]), "tmdb")


def cancel():
    """End the current navigation without a listing (cancelled action/search)."""
    xbmcplugin.endOfDirectory(plugin.handle, succeeded=False)


# ===========================================================================
# Item types — each builds its own ListItem and declares its own context menu
# ===========================================================================
class Item:
    """One list item. Subclasses set the folder/playable/media-type defaults."""
    is_folder = True
    is_playable = False
    media_type = "video"

    def __init__(self, label, url, icon=None, info=None, art=None,
                 media_type=None, is_folder=None, is_playable=None,
                 properties=None):
        self.label = label
        self.url = url
        self.icon = icon
        self.info = info
        self.art = art
        self.properties = properties
        if media_type is not None:
            self.media_type = media_type
        if is_folder is not None:
            self.is_folder = is_folder
        if is_playable is not None:
            self.is_playable = is_playable

    def context_menu(self):
        """Context-menu entries [(label, action), ...]. Override per item type.

        `action` is a Kodi built-in, usually RunPlugin(plugin.url_for("/...")).
        """
        return []

    def listitem(self):
        li = xbmcgui.ListItem(label=self.label)
        art = {}
        if self.icon:
            art["icon"] = art["thumb"] = self.icon
        if self.art:
            art.update(self.art)
        if art:
            li.setArt(art)
        if self.info:
            _apply_info(li, self.info, self.media_type)
        if self.is_playable:
            li.setProperty("IsPlayable", "true")
        for key, value in (self.properties or {}).items():
            li.setProperty(key, str(value))
        menu = self.context_menu()
        if menu:
            li.addContextMenuItems(menu)
        return li


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
        rows = [(item.url, item.listitem(), item.is_folder) for item in self.items]
        if rows:
            xbmcplugin.addDirectoryItems(plugin.handle, rows, len(rows))
        if self.content:
            xbmcplugin.setContent(plugin.handle, self.content)
        xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.endOfDirectory(plugin.handle)


class Menu(List):
    """A navigation menu — plain folder entries, no media content type."""
    content = ""


class Movies(List):
    content = "movies"


class Shows(List):
    content = "tvshows"


class Episodes(List):
    content = "episodes"
