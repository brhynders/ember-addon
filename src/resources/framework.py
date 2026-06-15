"""Minimal Kodi plugin framework — declarative menu tree + a response cache.

Menus are built from four node types and the framework renders each one,
owning all the Kodi chrome (URL building, pagination, content type, folder vs
playable). Handlers never touch xbmcplugin/xbmcgui.

    Folder      opens a submenu — static `children`, or a `provider` returning nodes
    MediaList   a list of movies/shows from a `provider` — auto-paginated
    Search      prompts for input, then renders like a MediaList
    Action      runs a `callback` (clear cache, open settings, play, ...)

You register the tree and the dynamic bits, then run():

    plugin.menu(MENU)                       # the Folder tree
    @plugin.provider("tmdb.movies")         # MediaList/Search data: (params, page) -> (rows, more)
    @plugin.folder("tmdb.genres")           # Folder children: (params) -> [Node, ...]
    @plugin.callback("play.movie")          # Action: (params) -> None | plugin.resolve*()
    plugin.run()

Routing is by the `route` query param: a static menu id, or a provider/callback
name. The handle + params are read fresh each navigation, so they stay correct
across reuseLanguageInvoker re-runs.

Media rows (what a provider returns) are plain dicts:
    label, url, is_folder, is_playable, icon, thumb/poster/fanart/...,
    art, info (title/plot/year/...), media_type, properties, context_menu.
"""
import functools
import json
import os
import sqlite3
import sys
import time
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs


# ===========================================================================
# Menu node types
# ===========================================================================
class _Node:
    def __init__(self, label, icon=None, params=None, info=None, art=None,
                 media_type=None):
        self.label = label
        self.icon = icon
        self.params = params or {}
        self.info = info
        self.art = art
        self.media_type = media_type


class Folder(_Node):
    """Opens a submenu — static `children`, or a `provider` that returns nodes."""
    def __init__(self, label, children=None, provider=None, **kw):
        super().__init__(label, **kw)
        self.children = list(children) if children else []
        self.provider = provider


class MediaList(_Node):
    """A list of movies/shows from `provider` — auto-paginated, content-typed."""
    def __init__(self, label, provider, content="movies", **kw):
        super().__init__(label, **kw)
        self.provider = provider
        self.content = content


class Search(_Node):
    """Prompts for a query, then renders like a MediaList from `provider`."""
    def __init__(self, label, provider, content="movies", **kw):
        super().__init__(label, **kw)
        self.provider = provider
        self.content = content


class Action(_Node):
    """Runs `callback` (clear cache, open settings, play, ...)."""
    def __init__(self, label, callback, **kw):
        super().__init__(label, **kw)
        self.callback = callback


def _slug(label):
    return "".join(c.lower() if c.isalnum() else "-" for c in label).strip("-")


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


class Plugin:
    """A Kodi plugin: register a menu tree + providers/callbacks, then run()."""

    def __init__(self, addon_id=None):
        self._addon = xbmcaddon.Addon(addon_id) if addon_id else xbmcaddon.Addon()
        self.id = self._addon.getAddonInfo("id")
        self.name = self._addon.getAddonInfo("name")
        self.icon = self._addon.getAddonInfo("icon")
        self._menus = {}       # route id -> Folder (static children)
        self._providers = {}   # name -> (params, page) -> (rows, has_more)
        self._folders = {}     # name -> (params) -> [Node, ...]
        self._callbacks = {}   # name -> (params) -> None | resolve sentinel
        self._root_route = "root"
        self.handle = -1
        self.params = {}
        self._register_builtins()

    def _register_builtins(self):
        """Default Action callbacks every addon gets: `settings` + `clear_cache`."""
        def settings(params):
            self.open_settings()

        def clear_cache(params):
            self.clear_cache()
            self.notify("Cache cleared")

        self._callbacks["settings"] = settings
        self._callbacks["clear_cache"] = clear_cache

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
    def get_url(self, **kwargs):
        """Build a plugin:// callback URL from query params."""
        query = {k: v for k, v in kwargs.items() if v is not None}
        base = "plugin://{0}/".format(self.id)
        return base + "?" + urlencode(query) if query else base

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

    # -- dialogs / playback --------------------------------------------------
    def keyboard(self, heading=""):
        """Prompt for text; returns "" if cancelled."""
        return xbmcgui.Dialog().input(heading) or ""

    def open_settings(self):
        self._addon.openSettings()

    def resolve(self, url):
        """From a play callback: hand Kodi a playable URL."""
        return {"__resolve__": True, "url": url}

    def resolve_fail(self):
        """From a play callback: signal the stream couldn't be resolved."""
        return {"__resolve__": True, "url": None}

    # -- registration --------------------------------------------------------
    def menu(self, root, route="root"):
        """Register the menu tree; indexes static folders so they're routable."""
        self._root_route = route
        self._index_menu(root, route)

    def _index_menu(self, folder, route):
        folder._route = route
        self._menus[route] = folder
        for child in folder.children:
            if isinstance(child, Folder) and not child.provider:
                self._index_menu(child, route + "/" + _slug(child.label))

    def provider(self, name):
        """Register a MediaList/Search data source: (params, page) -> (rows, more)."""
        def d(func):
            self._providers[name] = func
            return func
        return d

    def folder(self, name):
        """Register a dynamic Folder's children: (params) -> [Node, ...]."""
        def d(func):
            self._folders[name] = func
            return func
        return d

    def callback(self, name):
        """Register an Action/play handler: (params) -> None | resolve*()."""
        def d(func):
            self._callbacks[name] = func
            return func
        return d

    # -- run loop ------------------------------------------------------------
    def run(self, default=None):
        """Parse argv, resolve the route, render it."""
        # Rebuild the Addon each navigation so settings reads stay fresh even
        # when `plugin` is a long-lived module singleton under reuseLanguageInvoker.
        self._addon = xbmcaddon.Addon()
        self.handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
        params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
        route = params.pop("route", default or self._root_route)
        content = params.pop("content", "")
        page = int(params.pop("page", 1) or 1)
        prompt = params.pop("prompt", None)
        self.params = params
        try:
            self._route(route, content, page, prompt)
        except Exception as exc:  # noqa: BLE001 — never surface a raw traceback
            self.log_error("route '{0}' failed: {1}".format(route, exc))
            self.notify("Something went wrong")
            xbmcplugin.endOfDirectory(self.handle, succeeded=False)

    def _route(self, route, content, page, prompt):
        if route in self._menus:                      # static submenu
            return self._render_nodes(self._menus[route].children)
        if route in self._folders:                    # dynamic submenu
            return self._render_nodes(self._folders[route](dict(self.params)) or [])
        if route in self._providers:                  # media list (+ search)
            if prompt and not self.params.get("query"):
                query = self.keyboard("Search")
                if not query:
                    return xbmcplugin.endOfDirectory(self.handle, succeeded=False)
                self.params["query"] = query
            rows, has_more = self._providers[route](dict(self.params), page)
            rows = list(rows)
            if has_more:
                nxt = dict(self.params)
                nxt.update(route=route, content=content, page=page + 1)
                rows.append({"label": "Next Page >>", "icon": self.icon,
                             "is_folder": True, "url": self.get_url(**nxt)})
            return self._render(rows, content=content or "videos")
        if route in self._callbacks:                  # action / play
            result = self._callbacks[route](dict(self.params))
            if isinstance(result, dict) and result.get("__resolve__"):
                return self._resolve(result.get("url"))
            return xbmcplugin.endOfDirectory(self.handle, succeeded=False)
        self.log_error("unknown route: {0}".format(route))
        self.notify("Something went wrong")
        xbmcplugin.endOfDirectory(self.handle, succeeded=False)

    # -- rendering -----------------------------------------------------------
    def _node_url(self, node):
        if isinstance(node, MediaList):
            return self.get_url(route=node.provider, content=node.content, **node.params)
        if isinstance(node, Search):
            return self.get_url(route=node.provider, content=node.content,
                                prompt=1, **node.params)
        if isinstance(node, Action):
            return self.get_url(route=node.callback, **node.params)
        if isinstance(node, Folder):
            if node.provider:
                return self.get_url(route=node.provider, **node.params)
            return self.get_url(route=node._route)
        raise TypeError("unknown node type: {0!r}".format(node))

    def _render_nodes(self, nodes):
        items = [{
            "label": node.label, "icon": node.icon, "is_folder": True,
            "url": self._node_url(node), "info": node.info, "art": node.art,
            "media_type": node.media_type or "video",
        } for node in nodes]
        self._render(items, content="")

    def _render(self, items, content="videos"):
        rows = [(it.get("url", ""), self._make_listitem(it), it.get("is_folder", False))
                for it in items]
        if rows:
            xbmcplugin.addDirectoryItems(self.handle, rows, len(rows))
        if content:
            xbmcplugin.setContent(self.handle, content)
        xbmcplugin.addSortMethod(self.handle, xbmcplugin.SORT_METHOD_NONE)
        xbmcplugin.endOfDirectory(self.handle, succeeded=True)

    def _resolve(self, url):
        if url:
            xbmcplugin.setResolvedUrl(self.handle, True, xbmcgui.ListItem(path=url))
        else:
            xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())

    def _make_listitem(self, item):
        li = xbmcgui.ListItem(label=item.get("label", ""))

        art = {}
        if item.get("icon"):
            art["icon"] = art["thumb"] = item["icon"]
        for slot in ("thumb", "poster", "fanart", "banner", "clearlogo"):
            if item.get(slot):
                art[slot] = item[slot]
        if item.get("art"):
            art.update(item["art"])
        if art:
            li.setArt(art)

        if item.get("info"):
            _apply_info(li, item["info"], item.get("media_type", "video"))
        if item.get("is_playable"):
            li.setProperty("IsPlayable", "true")
        for key, value in (item.get("properties") or {}).items():
            li.setProperty(key, str(value))
        for stream_type, details in (item.get("stream_info") or {}).items():
            li.addStreamInfo(stream_type, details)
        if item.get("context_menu"):
            li.addContextMenuItems(item["context_menu"])
        return li
