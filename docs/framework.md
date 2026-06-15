# Framework & project conventions

This document describes the reusable, add-on-agnostic parts of the project: the
home-grown framework (`framework.py`), the build system (`build.py`), and the
repository conventions (`src/` vs `dist/`, the single `icon.png` master, the
generated manifest, etc.).

For this specific add-on's code — its routes, its TMDB layer, its `Item`/`List`
subclasses — see [`addon.md`](addon.md).

---

## 1. Repository layout & conventions

```
<repo>/
├── build.py            # single source of truth: builds the add-on + its repo
├── icon.png            # the ONE committed icon (master); copied in at build time
├── src/                # hand-written code ONLY (no generated files live here)
│   ├── addon.py        # thin entry: import the routes module, then router.run()
│   └── resources/
│       ├── framework.py    # the generic framework (this doc's subject)
│       ├── routes.py       # all @router.route handlers (imported by addon.py)
│       ├── settings.xml    # user-facing settings
│       └── ...             # add-on-specific modules (see addon.md)
├── dist/               # GENERATED — committed so GitHub Pages can serve it
│   ├── <plugin-id>/<plugin-id>-<ver>.zip   # the add-on zip
│   ├── addons.xml + addons.xml.md5         # repo index
│   ├── <repo-id>.zip                       # bootstrap repo add-on
│   └── index.html                          # browseable link page
└── docs/
    ├── framework.md    # this file
    └── addon.md        # the add-on-specific code
```

Two hard rules underpin everything:

- **`src/` is hand-written only.** The `addon.xml` manifest and
  `resources/icon.png` are *never* written into `src/` — they are assembled at
  build time and exist only inside the packaged zip. This keeps the source tree
  clean and the manifest a pure function of `build.py`'s CONFIG block.
- **`dist/` is generated** by `build.py`. It is committed (GitHub Pages serves
  it as the Kodi repository), but you never hand-edit it. Zips are byte-stable
  (fixed timestamps), so rebuilding without source changes produces no diff.

(The framework imposes one usage convention too — all routes live in a single
imported `routes` module, kept out of the re-executed entry script; see §3.1.)

---

## 2. `build.py` — packaging & release

`build.py` depends only on the Python 3 standard library and builds two things
from one CONFIG block at the top of the file:

1. **The video add-on** (`PLUGIN_ID`, e.g. `plugin.video.<name>`).
2. **A bootstrap repository add-on** (`REPO_ID`, e.g. `repository.<name>`) — the
   small add-on a user installs first so Kodi can auto-update the plugin.

### The single-icon convention

There is exactly one committed image: **`icon.png` at the repo root** (the
master). At build time `build.py` copies it to `resources/icon.png` inside the
staged add-on and to the repo add-on's `icon.png`, and the manifest references
`resources/icon.png`. So: edit one file, both add-ons get the new icon, and no
icon is ever duplicated into `src/`.

### The generated manifest

`build.py` writes `addon.xml` into the *staged* add-on (never into `src/`) from
the CONFIG values, including:

- `<import addon="xbmc.python" version="{PYTHON_VERSION}"/>`
- `<extension point="xbmc.python.pluginsource" library="addon.py">` —
  `addon.py` is the entry point Kodi runs.
- `<reuselanguageinvoker>true</reuselanguageinvoker>` — Kodi reuses the Python
  interpreter across navigations for speed. **This is why the framework's
  module-level singletons (`router`, `cache`) and the settings-freshness logic
  matter** (see §3) — module state persists between navigations.
- If a `src/service.py` exists, an `xbmc.service` extension is added
  automatically.

### Commands

```sh
python3 build.py             # build add-on + repo into dist/
python3 build.py --install   # also copy the built add-on into the local
                             # (Windows) Kodi addons dir, auto-detected from WSL
```

`--install` honors the `KODI_ADDONS_DIR` env var / CONFIG override; otherwise it
scans every Windows user under `/mnt/c` and picks the one with Kodi installed.

### Cutting a release

1. Bump `VERSION` in `build.py`'s CONFIG block.
2. `python3 build.py`
3. Commit (the `src/` change + the regenerated `dist/`) and push.

Only the latest plugin zip is kept in `dist/`; old versions live in git history.

---

## 3. `framework.py` — the generic framework

`framework.py` is a single module, deliberately. It knows about URLs, a cache,
Kodi list rendering, and add-on settings — but **nothing** about any particular
add-on's domain (no movies, TV, scrapers, etc.). It exposes four concerns:

```python
from resources.framework import router, cache, notify, get_setting, Item, List
```

### 3.1 Routing — the `router` singleton

Path-based routing. Handlers are registered against URL *paths* and dispatched
from `sys.argv` on each navigation.

```python
@router.route("/movies/{category}")     # {name} captures one path segment
def movie_category(category):
    ...                                  # build a listing and .render() it

router.url_for("/movies/trending")              # -> plugin://<id>/movies/trending
router.url_for("/play/movie/603", autoplay=1)   # extra kwargs -> ?autoplay=1
router.run()                                     # parse argv, match, dispatch
```

Per-navigation state, read fresh inside `run()` each time (correct even under
`reuselanguageinvoker`):

- `router.handle` — the Kodi directory handle (`int(sys.argv[1])`).
- `router.params` — query-string params (minus `page`) as a dict.
- `router.page` — the `page` param as an int (default `1`), for pagination.

The router owns **no rendering**. On a dispatch failure (no matching route, or a
handler raising) it logs, notifies "Something went wrong", and ends the
directory with `succeeded=False` so Kodi doesn't hang — that is the *only* time
the router itself touches the listing API.

**Framework convention — all routes in one imported module, not the entry
script.** Every `@router.route` lives in a single `routes` module (in Ember,
`resources/routes.py`); the entry script (`addon.py`) just imports it and calls
`router.run()`. This matters under `reuseLanguageInvoker`: the entry script
re-executes on **every** navigation, but imported modules are cached in
`sys.modules` and their top level does **not** re-run. Putting the decorators in
an imported module means routes register **once per interpreter**; putting them
in the entry script would re-run the decorators each navigation, appending
duplicate routes to the persistent `router` singleton and slowing dispatch over
a session. Keep handlers thin — fetch data, build a `List` of `Item`s, render —
and delegate anything heavier to a domain module.

### 3.2 Response cache — the `cache` singleton

A TTL key/value store backed by a single SQLite `cache.db` in the add-on's
profile dir (persists across Kodi restarts). Values are JSON-serialized, so any
JSON-serializable value works. Expired rows are pruned lazily on read; a fresh
connection per call keeps it safe across Kodi's navigation threads.

```python
cache.get(key)                       # -> value or None (None if missing/expired)
cache.set(key, value, ttl_minutes=60)
cache.clear()                        # drop everything

@cache.cached(ttl_minutes=480)       # memoise by (func name, args, kwargs)
def expensive(...):
    ...
```

### 3.3 Helpers — module-level functions

Stateless utilities; no object to thread around. Add-on identity is read once at
import; settings are re-read smartly (see below).

- Constants: `ID`, `NAME`, `ICON` (from the running add-on's metadata).
- `log(msg, level=xbmc.LOGINFO)`, `log_error(msg)`
- `notify(message, heading=None, icon=None, time=4000)`
- `get_setting(key, default="")`, `get_bool(key, default=False)`,
  `get_int(key, default=0)`
- `keyboard(heading="")` — text prompt, returns `""` if cancelled.
- `open_settings()`

**Settings freshness without rebuilding every call.** Under
`reuselanguageinvoker` the module is long-lived, so a cached `Addon()` could go
stale if the user changes a setting mid-session. Rather than rebuild `Addon()`
on every read, the helpers keep one instance and rebuild it **only when
`settings.xml`'s mtime advances** (`_addon_for_settings()`). Cheap reads, still
fresh.

### 3.4 Base list UI — `Item` and `List`

The framework owns generic Kodi directory rendering; an add-on subclasses these
to wrap its own data (see [`addon.md`](addon.md) for concrete subclasses).
**Video-only by charter:** `Item` applies metadata via the `InfoTagVideo` API
(`_apply_info`).

`Item` — one list row. Builds its own `xbmcgui.ListItem` and declares its own
context menu:

```python
Item(label, url, icon=None, info=None, art=None,
     media_type="video", is_folder=True, is_playable=False, properties=None)
```

- Class attributes `is_folder` / `is_playable` / `media_type` set subclass
  defaults (override per type).
- `context_menu()` → `[(label, action), ...]`; override to add entries (action
  is usually a Kodi built-in like `RunPlugin(router.url_for("/..."))`).
- `listitem()` → the built `xbmcgui.ListItem` (art, info, IsPlayable,
  properties, context menu).

`List` — a directory: a content type + a collection of `Item`s.

```python
class Movies(List):
    content = "movies"          # Kodi content type for the container

Movies(item_iterable).render()  # addDirectoryItems + setContent + endOfDirectory
lst.add(item)                   # append (skips items with no label)
lst.next_page(url)              # append a "Next Page >>" folder entry
```

`render()` is the single call that emits the whole directory to Kodi.

### Generic request flow

```
Kodi launches addon.py  ── imports the routes module (registers routes once),
      │                     then router.run()
      ▼
  router.run()  ── parse sys.argv (handle, params, page), match path
      │
      ▼
  @router.route handler (in the routes module)
      │  fetch data (optionally via cache)
      │  build a List of Item subclasses
      ▼
  List.render()  ──▶  xbmcplugin.addDirectoryItems + setContent + endOfDirectory
```

A playable row points its URL at a route whose handler resolves a stream (or
lists sources) instead of rendering a directory.

---

## 4. Reusing this skeleton for another add-on

The framework and build system are add-on agnostic. To start a new add-on:

1. Copy `build.py`, `framework.py`, and `icon.png`; edit `build.py`'s CONFIG.
2. Put your routes in a `routes` module and keep `addon.py` a thin entry that
   imports it then calls `router.run()`; add a domain layer (your client/mappers).
3. Subclass `Item` / `List` for your media rows; keep `addon.py` the sole owner
   of `@router.route`.
4. `python3 build.py --install` and iterate.

Document your add-on's own modules in `docs/addon.md`, mirroring this repo.
