"""Minimal Kodi plugin framework — routing, response cache, base list UI, helpers.

Generic and video-add-on agnostic. One module, four concerns:

    helpers   log/notify/get_setting/keyboard/...  (module-level functions)
    cache     TTL response cache (SQLite)          -> the `cache` singleton
    router    path-based routing + the run loop    -> the `router` singleton
    Item/List base directory-rendering classes

The add-on imports what it needs:

    from resources.framework import router, cache, notify, get_setting, Item, List

    @router.route("/movies/{category}")     # {name} -> a path segment
    def movie_category(category):
        Movies(...).render()                # rendering lives in the add-on

    router.url_for("/movies/trending")              # -> plugin://<id>/movies/trending
    router.url_for("/play/movie/603", autoplay=1)   # leftover kwargs -> ?autoplay=1
    router.run()

Routing is by the URL path (read from sys.argv[0]); the handle, query params,
and page are read fresh each navigation, so they stay correct across
reuseLanguageInvoker re-runs. Settings are likewise kept fresh by reloading the
Addon only when settings.xml's mtime advances. The router owns no rendering:
handlers build their listings with the List/Item classes (which call xbmcplugin
themselves) and read `router.handle` for playback resolution; the router only
ends a directory itself when a dispatch fails, so Kodi doesn't hang.

Video-only by charter: Item applies metadata via the InfoTagVideo API.
"""
import functools
import json
import os
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs


# ===========================================================================
# Helpers — add-on identity + stateless utilities (log, notify, settings, dialogs)
#
# Add-on identity (id/name/icon) never changes during a session, so it's read
# once at import. Settings *can* change mid-session (the user opens the settings
# dialog), so we keep one Addon instance and rebuild it only when settings.xml's
# mtime advances — cheaper than a fresh Addon() on every read, yet still fresh
# under reuseLanguageInvoker, where this module is a long-lived singleton.
# ===========================================================================
_addon = xbmcaddon.Addon()
ID = _addon.getAddonInfo("id")
NAME = _addon.getAddonInfo("name")
ICON = _addon.getAddonInfo("icon")

# The user's settings.xml; we watch its mtime to know when to reload settings.
_settings_path = os.path.join(
    xbmcvfs.translatePath(_addon.getAddonInfo("profile")), "settings.xml"
)
try:
    _settings_mtime = os.path.getmtime(_settings_path)
except OSError:
    _settings_mtime = -1.0


def _addon_for_settings():
    """Return an Addon whose settings reflect the latest settings.xml.

    Rebuilds the cached instance only when settings.xml has changed since the
    last read; otherwise reuses it. Keeps reads cheap while still picking up
    edits the user makes mid-session.
    """
    global _addon, _settings_mtime
    try:
        mtime = os.path.getmtime(_settings_path)
    except OSError:
        return _addon  # not written yet — nothing newer to load
    if mtime > _settings_mtime:
        _addon = xbmcaddon.Addon()
        _settings_mtime = mtime
    return _addon


# -- logging / notifications ------------------------------------------------
def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[{0}] {1}".format(ID, msg), level)


def log_error(msg):
    log(msg, xbmc.LOGERROR)


def notify(message, heading=None, icon=None, time=4000):
    xbmcgui.Dialog().notification(heading or NAME, message, icon or ICON, time)


# -- settings (read off a fresh-when-changed Addon) -------------------------
def get_setting(key, default=""):
    value = _addon_for_settings().getSetting(key)
    return value if value != "" else default


def get_bool(key, default=False):
    value = _addon_for_settings().getSetting(key)
    return value.lower() == "true" if value else default


def get_int(key, default=0):
    try:
        return int(_addon_for_settings().getSetting(key))
    except (ValueError, TypeError):
        return default


# -- dialogs ----------------------------------------------------------------
def keyboard(heading=""):
    """Prompt for text; returns "" if cancelled."""
    return xbmcgui.Dialog().input(heading) or ""


def open_settings():
    _addon_for_settings().openSettings()


# ===========================================================================
# Response cache — a TTL key/value store backed by one SQLite DB.
#
# For expensive, repeatable reads (TMDB responses, etc.). A single cache.db in
# the profile dir, persisting across Kodi restarts. Values are stored as JSON
# text, so any JSON-serializable value works. Expired rows are pruned lazily on
# read. A fresh connection per call keeps it safe across Kodi's nav threads.
# ===========================================================================
class Cache:
    """A TTL key/value store. A connection is opened per call (safe across Kodi's
    navigation threads). The schema is ensured once per process, and connections
    run with journaling/sync off and autocommit — it's a disposable cache, so we
    trade durability for fast, fsync-free writes."""

    def __init__(self):
        self._db = None
        self._ready = False     # has the table been ensured this process?

    def _conn(self):
        if self._db is None:
            profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
            try:
                os.makedirs(profile, exist_ok=True)
            except OSError:
                pass
            self._db = os.path.join(profile, "cache.db")
        conn = sqlite3.connect(self._db, timeout=5, isolation_level=None)
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA journal_mode=OFF")
        if not self._ready:     # create the table once, not on every call
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache "
                "(key TEXT PRIMARY KEY, value TEXT, expiry REAL)"
            )
            self._ready = True
        return conn

    def get(self, key):
        """Return the cached value for `key`, or None if missing/expired."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT value, expiry FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            value, expiry = row
            if expiry <= time.time():
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                return None
            return json.loads(value)
        finally:
            conn.close()

    def set(self, key, value, ttl_minutes=60):
        """Cache `value` under `key` for `ttl_minutes`."""
        try:
            blob = json.dumps(value)
        except TypeError:  # value wasn't JSON-serializable — skip silently
            return
        expiry = time.time() + ttl_minutes * 60
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expiry) VALUES (?, ?, ?)",
                (key, blob, expiry),
            )
        finally:
            conn.close()

    def clear(self):
        """Drop every cached entry."""
        conn = self._conn()
        try:
            conn.execute("DELETE FROM cache")
        finally:
            conn.close()

    def cached(self, ttl_minutes=60):
        """Decorator: memoise a function's return by its args for `ttl_minutes`."""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                key = "{0}:{1}:{2}".format(func.__name__, args,
                                           sorted(kwargs.items()))
                value = self.get(key)
                if value is None:
                    value = func(*args, **kwargs)
                    if value is not None:
                        self.set(key, value, ttl_minutes)
                return value
            return wrapper
        return decorator


# The shared cache singleton — every module imports this one instance.
cache = Cache()


# ===========================================================================
# Routing — register handlers against URL path patterns, then run()
# ===========================================================================
def _compile(pattern):
    """Turn a route pattern ("/movies/{category}") into an anchored regex."""
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    return re.compile("^" + regex + "$")


class Router:
    """Register route handlers against URL paths, then run()."""

    def __init__(self):
        self._routes = []     # [(compiled_regex, handler), ...] in registration order
        self.handle = -1
        self.params = {}      # query params (minus `page`) for this navigation
        self.page = 1

    # -- URLs ----------------------------------------------------------------
    def url_for(self, path, **query):
        """Build a plugin:// URL from a literal route path + optional query."""
        base = "plugin://{0}{1}".format(ID, path)
        q = {k: v for k, v in query.items() if v is not None}
        return base + "?" + urlencode(q) if q else base

    # -- registration --------------------------------------------------------
    def route(self, pattern):
        """Register a handler for a URL path pattern (segments use {name})."""
        def decorator(func):
            self._routes.append((_compile(pattern), func))
            return func
        return decorator

    # -- run loop ------------------------------------------------------------
    def run(self):
        """Parse argv, match the path to a route, and dispatch.

        The handle/params/page are read fresh here, so they stay correct even
        when this Router is a long-lived module singleton under
        reuseLanguageInvoker. Settings freshness is handled in the helpers.
        """
        self.handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
        self.params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
        self.page = int(self.params.pop("page", 1) or 1)
        path = urlsplit(sys.argv[0]).path or "/"
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        try:
            self._dispatch(path)
        except Exception as exc:  # noqa: BLE001 — never surface a raw traceback
            log_error("route '{0}' failed: {1}".format(path, exc))
            notify("Something went wrong")
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)

    def _dispatch(self, path):
        for regex, handler in self._routes:
            match = regex.match(path)
            if match:
                return handler(**match.groupdict())
        log_error("no route for: {0}".format(path))
        notify("Something went wrong")
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)


# The shared router singleton — addon.py and every route module import this one.
router = Router()


# ===========================================================================
# Base list UI — Item builds its own ListItem; List collects + renders them
#
# The router is generic (routing only); everything about *listings* lives here.
# The add-on subclasses these (resources/ui.py) to wrap TMDB data into rows; the
# base classes know nothing about movies or TMDB.
# ===========================================================================
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

        `action` is a Kodi built-in, usually RunPlugin(router.url_for("/...")).
        """
        return []

    def listitem(self):
        # offscreen=True builds a lightweight data item (no per-item GUI locking),
        # which is the key speedup for rendering a directory of many items.
        li = xbmcgui.ListItem(label=self.label, offscreen=True)
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
        self.items.append(Item("Next Page >>", url, icon=ICON))
        return self

    def render(self):
        rows = [(item.url, item.listitem(), item.is_folder) for item in self.items]
        if rows:
            xbmcplugin.addDirectoryItems(router.handle, rows, len(rows))
        if self.content:
            xbmcplugin.setContent(router.handle, self.content)
        xbmcplugin.addSortMethod(router.handle, xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.endOfDirectory(router.handle)
