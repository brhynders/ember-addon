"""TorBox debrid client — resolve a cached torrent hash to a direct CDN URL.

The Stremio add-ons hand back a slow resolve/redirect endpoint (3-8s) that does
this same work server-side on every click. Calling the TorBox API directly cuts
that to ~1s: check the hash is cached, add the (already-cached) torrent, list its
files, then request a direct download link. The transfer is deleted afterwards so
the account stays clean — re-adding a cached hash is instant.

    resolve("c3da…dcd6", "The.Movie.2160p.mkv") -> "https://…tb-cdn.io/…" | None

A Cloudflare layer in front of api.torbox.app rejects the default urllib
user-agent, so a browser UA is required on every request.
"""
import json
import threading
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from resources.framework import get_setting, log_error

_API = "https://api.torbox.app/v1/api/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_TIMEOUT = 30
_VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".wmv", ".mpg", ".flv")


def _key():
    return get_setting("torbox_api_key")


def _call(method, path, params=None, data=None, json_body=None, timeout=_TIMEOUT):
    """One TorBox API call; returns the parsed JSON dict, or None on failure.

    `data` is form-encoded (createtorrent wants that); `json_body` is sent as a
    JSON payload (controltorrent rejects form data with a 422).
    """
    headers = {"Authorization": "Bearer " + _key(), "User-Agent": _UA,
               "Accept": "application/json"}
    url = _API + path + (("?" + urlencode(params)) if params else "")
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif data:
        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with urlopen(Request(url, data=body, headers=headers, method=method),
                     timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, ValueError) as exc:
        log_error("torbox {0}: {1}".format(path, exc))
        return None


def _ok(resp):
    return isinstance(resp, dict) and resp.get("success")


def cached_hashes(infohashes):
    """Subset of infohashes TorBox has cached, checked in as few calls as we can.

    checkcached takes many comma-separated hashes at once; we chunk only to keep
    the query string sane. Uncached hashes are simply absent from `data` (a list
    of cached entries, or an object keyed by hash depending on the API mood — we
    accept both). Hashes are matched case-insensitively.
    """
    wanted = list({h.lower() for h in infohashes if h})
    cached = set()
    for i in range(0, len(wanted), 100):
        batch = wanted[i:i + 100]
        resp = _call("GET", "torrents/checkcached",
                     params={"hash": ",".join(batch), "format": "list"})
        if not _ok(resp):
            continue
        data = resp.get("data")
        if isinstance(data, dict):          # object keyed by hash -> cached entry
            cached.update(h.lower() for h, v in data.items() if v)
        else:                               # list of cached entries, each {hash: …}
            for row in data or []:
                h = row.get("hash", "") if isinstance(row, dict) else ""
                if h:
                    cached.add(h.lower())
    return cached


def _name(f):
    return str(f.get("name") or f.get("short_name") or "")


def _pick_file(files, filename):
    """TorBox file id for the wanted file: filename match, else largest video."""
    videos = [f for f in files if _name(f).lower().endswith(_VIDEO_EXT)]
    target = (filename or "").rsplit("/", 1)[-1].lower()
    pool = videos or files
    if target:
        for f in pool:
            name = _name(f).lower()
            if name.endswith(target) or target.endswith(name.rsplit("/", 1)[-1]):
                return f.get("id")
    if not pool:
        return None
    return max(pool, key=lambda f: f.get("size") or 0).get("id")


def _delete(torrent_id):
    """Fire-and-forget removal of the transfer we added to resolve."""
    threading.Thread(
        target=_call, args=("POST", "torrents/controltorrent"),
        kwargs={"json_body": {"torrent_id": int(torrent_id), "operation": "delete"}},
        daemon=True).start()


def resolve(infohash, filename=""):
    """A cached torrent hash -> direct CDN URL, or None if it can't be resolved.

    createtorrent (instant for a cached hash) -> mylist (list files, pick the
    right one) -> requestdl (direct link), then the transfer is deleted. Sources
    are pre-filtered to cached hashes at scrape time, so we skip a checkcached
    here; if a hash was evicted since, the added transfer is removed in finally.
    None means the caller couldn't get a playable URL.
    """
    if not _key() or len(infohash) != 40:
        return None
    created = _call("POST", "torrents/createtorrent",
                    data={"magnet": "magnet:?xt=urn:btih:" + infohash,
                          "seed": 3, "allow_zip": "false"})
    data = (created or {}).get("data") or {}
    torrent_id = data.get("torrent_id", data.get("id"))
    if torrent_id is None:
        return None
    try:
        listed = _call("GET", "torrents/mylist",
                       params={"id": torrent_id, "bypass_cache": "true"})
        info = (listed or {}).get("data") or {}
        if isinstance(info, list):
            info = info[0] if info else {}
        file_id = _pick_file(info.get("files") or [], filename)
        if file_id is None:
            return None
        got = _call("GET", "torrents/requestdl",
                    params={"token": _key(), "torrent_id": torrent_id,
                            "file_id": file_id})
        url = got.get("data") if _ok(got) else None
        return url if isinstance(url, str) and url else None
    finally:
        _delete(torrent_id)
