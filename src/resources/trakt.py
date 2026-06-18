"""Trakt v2 client — device auth, token storage, read lists, writes, scrobble.

Mirrors tmdb.py in shape: a small authed `_request` plus thin endpoint helpers.
The app credentials are hardcoded (like the TMDB key); per-user OAuth tokens live
in one trakt.json in the profile dir (not in settings or the response cache, so
"Clear Cache" can't log you out). Tokens auto-refresh on expiry / a 401.

Read endpoints return raw Trakt items; `tmdb_ids()` pulls the TMDB ids out so the
add-on can hydrate + render them through the existing TMDB/ui machinery. Writes
(watchlist, history, scrobble) build their body from context-menu params.
"""
import json
import os
import random
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.framework import cache, get_bool, log_error, notify

# --- Trakt OAuth app credentials — from trakt.tv/oauth/applications
CLIENT_ID = "a87a4a42ed04c4ac000ed7973c0fd4a4211b845add9fc5940b896c8fe84c996f"
CLIENT_SECRET = "2bc1cd2b40a5e781e58a2c75d1ea45a9209dcb3cf98d6f8fbafada9d463ade2e"

API = "https://api.trakt.tv"
REDIRECT = "urn:ietf:wg:oauth:2.0:oob"
_TIMEOUT = 20
_PLURAL = {"movie": "movies", "tv": "shows"}
_USER_AGENT = "{0}/{1}".format(xbmcaddon.Addon().getAddonInfo("id"),
                               xbmcaddon.Addon().getAddonInfo("version"))


# ===========================================================================
# Token storage — a small JSON file in the profile dir
# ===========================================================================
def _path():
    profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
    try:
        os.makedirs(profile, exist_ok=True)
    except OSError:
        pass
    return os.path.join(profile, "trakt.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(data):
    try:
        with open(_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError as exc:
        log_error("Trakt: cannot save token: {0}".format(exc))


def _save_token(data):
    _save({"access_token": data["access_token"],
           "refresh_token": data.get("refresh_token", ""),
           "expires_at": time.time() + int(data.get("expires_in", 7776000))})


def authorized():
    return bool(CLIENT_ID and _load().get("access_token"))


def sign_out():
    _save({})


# ===========================================================================
# HTTP
# ===========================================================================
def _request(method, path, body=None, auth=True, quiet=False, _retry=True):
    if not CLIENT_ID:
        log_error("Trakt: no client_id configured")
        return None
    # A real User-Agent is required — Cloudflare 403s the default Python-urllib one.
    headers = {"Content-Type": "application/json", "User-Agent": _USER_AGENT,
               "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}
    if auth:
        token = _access_token()
        if not token:
            return None
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(API + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=_TIMEOUT) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except HTTPError as exc:
        if exc.code == 401 and auth and _retry and _refresh():
            return _request(method, path, body, auth, quiet, _retry=False)
        if not quiet:
            log_error("Trakt {0} {1}: HTTP {2}".format(method, path, exc.code))
        return None
    except (URLError, ValueError, OSError) as exc:
        if not quiet:
            log_error("Trakt {0} {1}: {2}".format(method, path, exc))
        return None


def _access_token():
    store = _load()
    if not store.get("access_token"):
        return None
    if store.get("expires_at", 0) <= time.time() + 60 and not _refresh():
        return None
    return _load().get("access_token")


def _refresh():
    refresh = _load().get("refresh_token")
    if not refresh:
        return False
    data = _request("POST", "/oauth/token", {
        "refresh_token": refresh, "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET, "redirect_uri": REDIRECT,
        "grant_type": "refresh_token"}, auth=False)
    if data and data.get("access_token"):
        _save_token(data)
        return True
    _save({})
    return False


# ===========================================================================
# Device authorization
# ===========================================================================
def authorize():
    if not CLIENT_ID:
        notify("Trakt client_id not configured")
        return
    info = _request("POST", "/oauth/device/code", {"client_id": CLIENT_ID}, auth=False)
    if not info or "device_code" not in info:
        notify("Trakt: could not start authorization")
        return
    dialog = xbmcgui.DialogProgress()
    dialog.create("Trakt Authorization",
                  "Go to: {0}\nEnter code: {1}".format(
                      info.get("verification_url", "trakt.tv/activate"),
                      info.get("user_code", "")))
    interval = max(1, int(info.get("interval", 5)))
    expires = int(info.get("expires_in", 600))
    waited = 0
    try:
        while waited < expires:
            if dialog.iscanceled():
                break
            xbmc.sleep(interval * 1000)
            waited += interval
            dialog.update(int(waited * 100 / expires))
            token = _request("POST", "/oauth/device/token",
                             {"code": info["device_code"], "client_id": CLIENT_ID,
                              "client_secret": CLIENT_SECRET}, auth=False, quiet=True)
            if token and token.get("access_token"):
                _save_token(token)
                notify("Trakt authorized")
                return
    finally:
        dialog.close()
    notify("Trakt authorization cancelled")


# ===========================================================================
# Read lists — return raw Trakt items; tmdb_ids() extracts the ids to hydrate
# ===========================================================================
def watchlist(media):
    return _request("GET", "/sync/watchlist/{0}".format(_PLURAL[media])) or []


def recommendations(media):
    return _request("GET", "/recommendations/{0}?limit=40".format(_PLURAL[media])) or []


def most_watched(media):
    return _request("GET", "/{0}/watched/weekly?limit=40".format(_PLURAL[media])) or []


def box_office():
    return _request("GET", "/movies/boxoffice") or []


def in_progress(media):
    if media == "movie":
        return _request("GET", "/sync/playback/movies") or []
    seen, shows = set(), []          # dedupe in-progress episodes down to their shows
    for entry in in_progress_episodes():
        trakt_id = ((entry.get("show") or {}).get("ids") or {}).get("trakt")
        if trakt_id and trakt_id not in seen:
            seen.add(trakt_id)
            shows.append(entry)
    return shows


def in_progress_episodes():
    return _request("GET", "/sync/playback/episodes") or []


def because_you_watched(media, shuffle=False):
    plural = _PLURAL[media]
    history = _request("GET", "/sync/history/{0}?limit=25".format(plural)) or []
    if not history:
        return []
    entry = random.choice(history) if shuffle else history[0]
    node = entry.get("movie" if media == "movie" else "show") or {}
    trakt_id = (node.get("ids") or {}).get("trakt")
    if not trakt_id:
        return []
    return _request("GET", "/{0}/{1}/related?limit=40".format(plural, trakt_id)) or []


def tmdb_ids(items, media):
    """Pull the TMDB ids out of raw Trakt list items (any wrapper shape)."""
    key = "movie" if media == "movie" else "show"
    ids = []
    for item in items:
        node = item.get(key, item)
        tmdb_id = (node.get("ids") or {}).get("tmdb")
        if tmdb_id:
            ids.append(tmdb_id)
    return ids


# ===========================================================================
# Watched library — used to stamp playcount on hydrated list items
# ===========================================================================
@cache.cached(ttl_minutes=10)
def _watched_raw(media):
    """The user's full watched library. Cached briefly so list renders don't
    re-fetch it; the 10-min TTL refreshes it soon after a manual mark."""
    return _request("GET", "/sync/watched/{0}".format(_PLURAL[media])) or []


def watched_movie_plays():
    """tmdb_id -> plays count for every watched movie."""
    out = {}
    for it in _watched_raw("movie"):
        tmdb_id = ((it.get("movie") or {}).get("ids") or {}).get("tmdb")
        if tmdb_id:
            out[tmdb_id] = it.get("plays", 0)
    return out


def watched_show_episodes():
    """tmdb_id -> count of watched episodes (excludes season 0 / specials).
    Completeness is judged against TMDB's episode count by the caller, since
    /sync/watched/shows carries no aired totals."""
    out = {}
    for it in _watched_raw("tv"):
        tmdb_id = ((it.get("show") or {}).get("ids") or {}).get("tmdb")
        if not tmdb_id:
            continue
        out[tmdb_id] = sum(len(s.get("episodes") or [])
                           for s in (it.get("seasons") or []) if s.get("number"))
    return out


# ===========================================================================
# Writes — body built from context-menu params (type/tmdb/season/episode)
# ===========================================================================
def _body(params):
    kind, tmdb = params.get("type"), params.get("tmdb")
    if not (kind and tmdb):
        return None
    ids = {"ids": {"tmdb": int(tmdb)}}
    if kind == "movie":
        return {"movies": [ids]}
    if kind == "show":
        return {"shows": [ids]}
    if kind == "season":
        return {"shows": [{"ids": {"tmdb": int(tmdb)},
                           "seasons": [{"number": int(params["season"])}]}]}
    if kind == "episode":
        return {"shows": [{"ids": {"tmdb": int(tmdb)}, "seasons": [
            {"number": int(params["season"]),
             "episodes": [{"number": int(params["episode"])}]}]}]}
    return None


def set_watchlist(params, add):
    body = _body(params)
    path = "/sync/watchlist" if add else "/sync/watchlist/remove"
    return bool(body and _request("POST", path, body))


def set_watched(params, add):
    body = _body(params)
    path = "/sync/history" if add else "/sync/history/remove"
    return bool(body and _request("POST", path, body))


def scrobble(action, item, progress):
    """Report playback to Trakt (start/pause/stop). Trakt marks watched ≥80%."""
    if not (authorized() and get_bool("trakt_scrobble", True)):
        return
    body = dict(item)
    body["progress"] = progress
    _request("POST", "/scrobble/" + action, body)
