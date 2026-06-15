"""Minimal Kodi plugin framework — path-based routing + a response cache.

The framework is generic: it knows about URLs and the run loop, but nothing
about movies, episodes, TMDB, or how a listing is rendered. You register
handlers against URL paths; each handler builds its own listing (via the
addon's List/Item classes) and renders it.

    @plugin.route("/movies/{category}")     # {name} -> a path segment
    def movie_category(category):
        Movies(...).render()                # rendering lives in the addon

    plugin.url_for("/movies/trending")              # -> plugin://<id>/movies/trending
    plugin.url_for("/play/movie/603", autoplay=1)   # leftover kwargs -> ?autoplay=1
    plugin.run()

Routing is by the URL path (read from sys.argv[0]); the handle, query params,
and page are read fresh each navigation, so they stay correct across
reuseLanguageInvoker re-runs. The framework owns no rendering: handlers build
their listings with the addon's List/Item classes (which call xbmcplugin
themselves) and read `plugin.handle` for playback resolution. The framework
only ends a directory itself when a dispatch fails, so Kodi doesn't hang.
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
# Response cache — TTL key/value store in one SQLite DB (key, value, expiry).
#
# For expensive, repeatable reads (TMDB responses, etc.). A single cache.db in
# the profile dir, persisting across Kodi restarts. `value` is JSON text, so any
# JSON-serializable value works. Expired rows are pruned lazily on read. A fresh
# connection per call keeps it safe across Kodi's navigation threads.
# ===========================================================================
_cache_db = None


def _cache_conn():
    global _cache_db
    if _cache_db is None:
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
        try:
            os.makedirs(profile, exist_ok=True)
        except OSError:
            pass
        _cache_db = os.path.join(profile, "cache.db")
    conn = sqlite3.connect(_cache_db, timeout=5)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache "
        "(key TEXT PRIMARY KEY, value TEXT, expiry REAL)"
    )
    return conn


def cache_get(key):
    """Return the cached value for `key`, or None if missing/expired."""
    conn = _cache_conn()
    try:
        row = conn.execute(
            "SELECT value, expiry FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expiry = row
        if expiry <= time.time():
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
            return None
        return json.loads(value)
    finally:
        conn.close()


def cache_set(key, value, ttl_minutes=60):
    """Cache `value` under `key` for `ttl_minutes`."""
    try:
        blob = json.dumps(value)
    except TypeError:  # value wasn't JSON-serializable — skip silently
        return
    expiry = time.time() + ttl_minutes * 60
    conn = _cache_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expiry) VALUES (?, ?, ?)",
            (key, blob, expiry),
        )
        conn.commit()
    finally:
        conn.close()


def cache_clear():
    """Drop every cached entry."""
    conn = _cache_conn()
    try:
        conn.execute("DELETE FROM cache")
        conn.commit()
    finally:
        conn.close()


def _compile(pattern):
    """Turn a route pattern ("/movies/{category}") into an anchored regex."""
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    return re.compile("^" + regex + "$")


class Plugin:
    """A Kodi plugin: register route handlers, then run()."""

    def __init__(self, addon_id=None):
        self._addon = xbmcaddon.Addon(addon_id) if addon_id else xbmcaddon.Addon()
        self.id = self._addon.getAddonInfo("id")
        self.name = self._addon.getAddonInfo("name")
        self.icon = self._addon.getAddonInfo("icon")
        self._routes = []     # [(compiled_regex, handler), ...] in registration order
        self.handle = -1
        self.params = {}      # query params (minus `page`) for this navigation
        self.page = 1

    # -- logging / notifications --------------------------------------------
    def log(self, msg, level=xbmc.LOGINFO):
        xbmc.log("[{0}] {1}".format(self.id, msg), level)

    def log_error(self, msg):
        self.log(msg, xbmc.LOGERROR)

    def notify(self, message, heading=None, icon=None, time=4000):
        xbmcgui.Dialog().notification(
            heading or self.name, message, icon or self.icon, time
        )

    # -- URLs ----------------------------------------------------------------
    def url_for(self, path, **query):
        """Build a plugin:// URL from a literal route path + optional query."""
        base = "plugin://{0}{1}".format(self.id, path)
        q = {k: v for k, v in query.items() if v is not None}
        return base + "?" + urlencode(q) if q else base

    # -- settings (read off this navigation's Addon — always fresh) ----------
    def get_setting(self, key, default=""):
        value = self._addon.getSetting(key)
        return value if value != "" else default

    def get_bool(self, key, default=False):
        value = self._addon.getSetting(key)
        return value.lower() == "true" if value else default

    def get_int(self, key, default=0):
        try:
            return int(self._addon.getSetting(key))
        except (ValueError, TypeError):
            return default

    # -- response cache (delegates to the shared module-level store) ---------
    def cached(self, ttl_minutes=60):
        """Decorator: memoise a function's return by its args for `ttl_minutes`."""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                key = "{0}:{1}:{2}".format(func.__name__, args,
                                           sorted(kwargs.items()))
                value = cache_get(key)
                if value is None:
                    value = func(*args, **kwargs)
                    if value is not None:
                        cache_set(key, value, ttl_minutes)
                return value
            return wrapper
        return decorator

    def cache_get(self, key):
        return cache_get(key)

    def cache_set(self, key, value, ttl_minutes=60):
        cache_set(key, value, ttl_minutes)

    def clear_cache(self):
        cache_clear()

    # -- dialogs -------------------------------------------------------------
    def keyboard(self, heading=""):
        """Prompt for text; returns "" if cancelled."""
        return xbmcgui.Dialog().input(heading) or ""

    def open_settings(self):
        self._addon.openSettings()

    # -- registration --------------------------------------------------------
    def route(self, pattern):
        """Register a handler for a URL path pattern (segments use {name})."""
        def decorator(func):
            self._routes.append((_compile(pattern), func))
            return func
        return decorator

    # -- run loop ------------------------------------------------------------
    def run(self):
        """Parse argv, match the path to a route, and dispatch."""
        # Rebuild the Addon each navigation so settings reads stay fresh even
        # when `plugin` is a long-lived module singleton under reuseLanguageInvoker.
        self._addon = xbmcaddon.Addon()
        self.handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
        self.params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
        self.page = int(self.params.pop("page", 1) or 1)
        path = urlsplit(sys.argv[0]).path or "/"
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        try:
            self._dispatch(path)
        except Exception as exc:  # noqa: BLE001 — never surface a raw traceback
            self.log_error("route '{0}' failed: {1}".format(path, exc))
            self.notify("Something went wrong")
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)

    def _dispatch(self, path):
        for regex, handler in self._routes:
            match = regex.match(path)
            if match:
                return handler(**match.groupdict())
        self.log_error("no route for: {0}".format(path))
        self.notify("Something went wrong")
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)


# The shared singleton — addon.py and every route module import this one
# instance. Plugin() auto-detects the running add-on, so this stays reusable.
plugin = Plugin()
