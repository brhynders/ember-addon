# Ember add-on code

This document describes Ember's own code — the routes, the TMDB layer, and the
`Item`/`List` subclasses. It assumes the generic framework and conventions
documented in [`framework.md`](framework.md) (the `router`, `cache`, helpers,
and base `Item`/`List` come from there).

Ember is a clean, English-only movie & TV browser that reads everything from
TMDB. Playback resolution is not wired up yet (the `/play/...` routes are
placeholders).

---

## Modules

| File | Role |
|------|------|
| `addon.py` | Entry point. The **only** module with `@router.route`. Each handler fetches from `tmdb`, builds a `List` of `Item`s, and renders. Ends with `router.run()`. |
| `ui.py` | TMDB-backed subclasses of the framework bases — the screen vocabulary. |
| `tmdb.py` | TMDB v3 client, JSON→metadata mappers, and the browse data tables. |
| `playback.py` | `resolve(url)` — the playback resolution mechanic (no routes). |
| `settings.xml` | User settings. Only `tmdb_lang` is configurable. |

---

## `ui.py` — `Item` / `List` subclasses

**Item subclasses** (each sets folder/playable/media-type defaults and, for
media, wraps a TMDB mapper):

- `MenuItem(Item)` — a folder entry that opens another route (menu rows,
  sub-listings). `is_folder=True`, not playable. (This was previously named
  `Directory`.)
- `Movie(data, url, gmap=None)` — a playable movie row built from a raw TMDB
  result dict via `tmdb.map_movie`. `is_playable=True`, `media_type="movie"`.
- `Show(data, url, gmap=None)` — a TV show row (a folder of seasons) via
  `tmdb.map_show`. `media_type="tvshow"`.
- `Episode(ep, show_info, show_art, url)` — a playable episode row via
  `tmdb.map_episode`, labelled `"{season}x{episode:02d}. {title}"`.

**List subclasses** (each just carries its Kodi content type):

- `Menu` — plain navigation menu, `content=""`.
- `Movies` — `content="movies"`.
- `Shows` — `content="tvshows"`.
- `Episodes` — `content="episodes"`.

**`cancel()`** — end the current navigation with no listing (used for cancelled
searches / actions): `endOfDirectory(router.handle, succeeded=False)`.

Route handlers build the target URLs themselves (`router.url_for`) and pass them
into the items — items never know the route map.

---

## `addon.py` — routes

All routes live here. The shared helper `_media_list(media, data, more_url)`
turns a TMDB list response into a paginated `Movies`/`Shows`, appending a
"Next Page" entry while `router.page < tmdb.total(data)`.

| Path | Handler | What it shows |
|------|---------|---------------|
| `/` | `home` | Top-level menu: Movies / TV Shows / Tools |
| `/movies` | `movies_menu` | Movie browse menu (from the `_MOVIE_MENU` table) |
| `/tv` | `tv_menu` | TV browse menu (from the `_TV_MENU` table) |
| `/tools` | `tools_menu` | Settings / Clear Cache |
| `/list/{media}/{category}` | `category_list` | A TMDB endpoint list (trending, popular, …) |
| `/named/{media}/{key}` | `named_list` | A named `discover` query (`tmdb.NAMED`) |
| `/discover/{media}` | `discover_list` | `discover` filtered by query params |
| `/search/{media}` | `search_list` | Keyboard search results |
| `/genres/{media}` | `genres_menu` | Genre folders → `/discover` |
| `/years/{media}` | `years_menu` | Year folders → `/discover` |
| `/languages/{media}` | `languages_menu` | Language folders → `/discover` |
| `/networks` | `networks_menu` | Network folders → `/discover/tv` |
| `/providers/{media}` | `providers_menu` | Watch-provider folders → `/discover` (hardcoded `tmdb.PROVIDERS`) |
| `/decades/{media}` | `decades_menu` | Decade folders → `/discover` (date ranges) |
| `/certifications/{media}` | `certifications_menu` | Certification folders → `/discover` (**movie only** — see below) |
| `/tv/show/{id}` | `seasons_menu` | Seasons of a show |
| `/tv/show/{id}/season/{season}` | `episodes_list` | Episodes of a season |
| `/play/movie/{id}` | `play_movie` | Resolve a movie (placeholder) |
| `/play/episode/{id}/{season}/{episode}` | `play_episode` | Resolve an episode (placeholder) |
| `/coming-soon` | `coming_soon` | Placeholder toast (`?feature=` label) for unbuilt menu entries |
| `/settings` | `settings` | Open the settings dialog |
| `/clear-cache` | `clear_cache` | `cache.clear()` + notify |

### Browse menus & "coming soon" stubs

`/movies` and `/tv` are built from the `_MOVIE_MENU` / `_TV_MENU` tables — each
row is `(label, route, icon)`, rendered by `_menu()`. A row whose route is
`None` is a **placeholder**: it links to `/coming-soon?feature=<label>`, which
just shows a "coming soon" toast. These are the entries that need a Trakt
integration or local watch-tracking we haven't built yet — In Progress,
watchlists, Because You Watched, Trakt Recommended, Random Because You Watched,
Most Watched, Top 10 Box Office — plus Oscar Winners (no TMDB awards filter) and
**TV Certifications** (TMDB's `discover/tv` can't filter by certification).
Everything else is wired to TMDB. Replacing a stub later is a one-line table
edit (swap `None` for the real route) once its backend exists.

`media` is `"movie"` or `"tv"` throughout. Context is threaded through query
params where needed — e.g. the seasons menu passes `show_title`/`year`/`imdb`
into each season URL so the episode list can build complete metadata.

---

## `tmdb.py` — TMDB client & mappers

The TMDB knowledge layer. Nothing here touches Kodi listings; it produces the
plain `info`/`art` dicts the `ui.py` items consume.

- **Client.** `_get(path, ttl, **params)` is the core: it injects `api_key` and
  `language`, builds a cache key from the path + params, returns a cache hit if
  present, otherwise fetches over stdlib `urllib` and caches the result. It
  never crashes a menu — on a network/JSON error it logs and returns `{}`.
  Public wrappers: `movies`, `shows`, `discover`, `search`, `show_details`,
  `season_details`. (`genres`/`genre_map` read the hardcoded `GENRES` table —
  see below — and make no request.)
- **API key.** Hardcoded as `API_KEY` (a TMDB v3 key); **not** user-configurable
  — there is no setting for it. Only `tmdb_lang` (default `en-US`) is a setting,
  read via `_lang()`.
- **Cache TTLs.** `TTL_LIST` (8h) for browse lists, `TTL_DETAIL` (7d) for show/
  season details, `TTL_GENRE` (30d) for genre tables; search uses 60 min.
- **Mappers.** `map_movie`, `map_show`, `map_episode` turn raw TMDB dicts into
  the `info` (title/plot/year/rating/ids/…) and `art` (poster/thumb/fanart)
  dicts. Image URLs are built by `_img` / `image` at the configured sizes.
- **Data tables (all hardcoded).** `GENRES` (movie/tv, stable TMDB genre ids),
  `PROVIDERS` (curated US streaming services + their watch-provider ids),
  `CERTIFICATIONS` (US movie ratings), `LANGUAGES`, `NETWORKS`, and `NAMED`
  (FenLight-style named `discover` queries) drive the browse sub-menus — none of
  these menus hit the network; only the resulting `/discover` listing does. A
  `NAMED` value of `"@today"`
  is replaced with the current date by `named_params(media, key)` at request
  time (used by Premieres / Latest Releases / TV Up Coming, which are
  date-relative). "Most Favorited" maps to the `most_voted` named list
  (`vote_count.desc`) — TMDB exposes no favorite count.
- **Helpers.** `total(data)` (page count for pagination), `image(path, size)`.

---

## `playback.py` — playback resolution

A single function, no routes:

```python
def resolve(url):
    """Hand Kodi a playable URL (or fail the resolve if `url` is falsy)."""
    if url:
        xbmcplugin.setResolvedUrl(router.handle, True, xbmcgui.ListItem(path=url))
    else:
        xbmcplugin.setResolvedUrl(router.handle, False, xbmcgui.ListItem())
```

The `/play/...` route handlers in `addon.py` call `playback.resolve(...)`. Since
playback isn't wired up yet, they notify "Playback isn't wired up yet" and pass
`None`, which fails the resolve cleanly. When scraping/resolving is added, the
handlers will resolve a real stream URL through `resolve()`.

---

## Concrete request flow (a movie list)

```
plugin://plugin.video.ember/list/movie/trending?page=1
      │
      ▼
  router.run()  ── handle, params={}, page=1, path=/list/movie/trending
      │
      ▼
  category_list("movie", "trending")
      │  tmdb.movies("trending", page=1)  ──▶  cache.get / TMDB / cache.set
      │  _media_list(...)  builds Movies(Movie(...), …) + next_page
      ▼
  Movies.render()  ──▶  directory of movie rows, content="movies"
```

Selecting a movie row opens its `/play/movie/{id}` URL → `play_movie` →
`playback.resolve(None)` (placeholder).
