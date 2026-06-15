# Ember add-on code

This document describes Ember's own code — the routes, the TMDB layer, and the
`Item`/`List` subclasses. It assumes the generic framework and conventions
documented in [`framework.md`](framework.md) (the `router`, `cache`, helpers,
and base `Item`/`List` come from there).

Ember is a clean, English-only movie & TV browser that reads metadata from TMDB
and finds playable streams via Stremio scraper add-ons (Torrentio, Comet,
MediaFusion) resolved through TorBox debrid. Selecting a movie or episode opens
a native Kodi list of sources; picking one plays its resolved URL directly.
Trakt integration adds personalised lists, watchlist/watched context actions,
and a scrobbler service.

---

## Modules

| File | Role |
|------|------|
| `addon.py` | Entry point. The **only** module with `@router.route`. Each handler fetches from `tmdb`, builds a `List` of `Item`s, and renders. Ends with `router.run()`. |
| `ui.py` | TMDB-backed subclasses of the framework bases — the screen vocabulary. |
| `tmdb.py` | TMDB v3 client, JSON→metadata mappers, and the browse data tables. |
| `scrapers.py` | Stremio stream scrapers (base `Scraper` + subclasses) → playable `Stream`s. |
| `trakt.py` | Trakt v2 client: device auth, token store, read lists, watchlist/watched writes, scrobble. |
| `service.py` | Scrobbler service — a persistent `xbmc.Player` that reports playback to Trakt. |
| `settings.xml` | User settings: `tmdb_lang`, `trakt_scrobble`, the `torbox_api_key`, and per-scraper toggles. |

---

## `ui.py` — `Item` / `List` subclasses

**Item subclasses** (each sets folder/playable/media-type defaults and, for
media, wraps a TMDB mapper):

- `MenuItem(Item)` — a folder entry that opens another route (menu rows,
  sub-listings). `is_folder=True`, not playable. (This was previously named
  `Directory`.)
- `Movie(data, url, gmap=None)` — a movie row via `tmdb.map_movie`. A **folder**
  (`is_folder=True`): selecting it opens the movie's sources list.
- `Show(data, url, gmap=None)` — a TV show row (a folder of seasons) via
  `tmdb.map_show`. `media_type="tvshow"`.
- `Episode(ep, show_info, show_art, url)` — an episode row via
  `tmdb.map_episode`, labelled `"{season}x{episode:02d}. {title}"`. Also a
  **folder**: opens the episode's sources list.
- `Season(MenuItem)` — a season folder carrying `show_tmdb` + `season`, so its
  context menu can mark the whole season watched/unwatched.
- `Source(stream, info=None, media_type="video")` — a **playable** row wrapping a
  `scrapers.Stream` (`is_playable=True`, not a folder). Its URL is the
  already-resolved debrid link, so Kodi plays it directly. `info`/`media_type`
  carry the movie/episode identity (tmdb uniqueid + season/episode) onto the
  played item so the scrobbler can report it. Label: `[quality] filename — size · seeders · scraper`.

`Movie`/`Show`/`Season`/`Episode` override `context_menu()` to add Trakt actions
(watchlist add/remove on movies & shows; mark watched/unwatched on all four) —
each is a `RunPlugin` to a `/trakt/...` write route.

**List subclasses** (each just carries its Kodi content type):

- `Menu` — plain navigation menu, `content=""`.
- `Movies` — `content="movies"`.
- `Shows` — `content="tvshows"`.
- `Episodes` — `content="episodes"`.
- `Sources` — `content="videos"`; a native list of scraped sources.

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
| `/tv/show/{id}/season/{season}` | `episodes_list` | Episodes of a season (`?imdb=` threaded in) |
| `/sources/movie/{id}` | `movie_sources` | Native list of scraped sources for a movie |
| `/sources/episode/{id}/{season}/{episode}` | `episode_sources` | Sources for an episode (`?imdb=`) |
| `/trakt/watchlist/{media}` | `trakt_watchlist` | Your Trakt watchlist |
| `/trakt/recommended/{media}` | `trakt_recommended` | Trakt personalised recommendations |
| `/trakt/most-watched/{media}` | `trakt_most_watched` | Most-watched this week |
| `/trakt/progress/{media}` | `trakt_progress` | In-progress movies / shows |
| `/trakt/progress-episodes` | `trakt_progress_episodes` | In-progress episodes (resume points) |
| `/trakt/boxoffice` | `trakt_boxoffice` | Top 10 box office (movies) |
| `/trakt/because[-random]/{media}` | `trakt_because[_random]` | Related to a (recent/random) watched item |
| `/trakt/{watchlist,watched}-{add,remove}` | write handlers | Context-menu actions (params: `type`/`tmdb`/`season`/`episode`) |
| `/trakt/authorize`, `/trakt/signout` | auth handlers | Device-code login / sign out (Tools menu) |
| `/coming-soon` | `coming_soon` | Placeholder toast (`?feature=` label) for unbuilt menu entries |
| `/settings` | `settings` | Open the settings dialog |
| `/clear-cache` | `clear_cache` | `cache.clear()` + notify |

### Browse menus & "coming soon" stubs

`/movies` and `/tv` are built from the `_MOVIE_MENU` / `_TV_MENU` tables — each
row is `(label, route, icon)`, rendered by `_menu()`. A row whose route is
`None` is a **placeholder**: it links to `/coming-soon?feature=<label>`, which
just shows a "coming soon" toast. The personalised rows (In Progress, watchlists,
Because You Watched, Trakt Recommended, Random, Most Watched, Top 10 Box Office)
are now wired to Trakt; only two stubs remain — **Oscar Winners** (no TMDB awards
filter) and **TV Certifications** (TMDB's `discover/tv` can't filter by
certification). Replacing a stub later is a one-line table edit (swap `None` for
the real route).

`media` is `"movie"` or `"tv"` throughout. Context is threaded through query
params where needed — e.g. the seasons menu passes `imdb` into each season URL,
and the episode list passes it on to `/sources/episode/...`, since the Stremio
scrapers key off the show's IMDb id.

---

## `tmdb.py` — TMDB client & mappers

The TMDB knowledge layer. Nothing here touches Kodi listings; it produces the
plain `info`/`art` dicts the `ui.py` items consume.

- **Client.** `_get(path, ttl, **params)` is the core: it injects `api_key` and
  `language`, builds a cache key from the path + params, returns a cache hit if
  present, otherwise fetches over stdlib `urllib` and caches the result. It
  never crashes a menu — on a network/JSON error it logs and returns `{}`.
  Public wrappers: `movies`, `shows`, `discover`, `search`, `show_details`,
  `movie_details`, `season_details`, and `imdb_id(media, tmdb_id)` (resolves the
  IMDb id the scrapers need). (`genres`/`genre_map` read the hardcoded `GENRES`
  table — see below — and make no request.)
- **API key.** Hardcoded as `API_KEY` (a TMDB v3 key); **not** user-configurable
  — there is no setting for it. Only `tmdb_lang` (default `en-US`) is a setting,
  read via `_lang()`.
- **Cache TTLs.** `TTL_LIST` (8h) for browse lists, `TTL_DETAIL` (7d) for
  show/movie/season details; search uses 60 min.
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

## `scrapers.py` — stream scrapers

Finds playable sources from Stremio stream add-ons, using the same base-class +
subclass pattern as `ui.py`. The base **`Scraper`** runs the shared pipeline —
hit the add-on's `/stream/{type}/{id}.json`, parse the standard Stremio stream
objects, and keep only those with a directly-playable `url` (we depend on TorBox
debrid links; a raw magnet/`infoHash` can't be played natively, so it's
dropped). Each subclass only overrides `base_url(key)` to build its configured
prefix:

- **`Torrentio`** — path config: `https://torrentio.strem.fun/torbox=<KEY>`.
- **`Comet`** — URL-safe base64 of a JSON config (`debridServices:
  [{service:"torbox", apiKey:<KEY>}]`) in the path.
- **`MediaFusion`** — config is stored server-side: POST
  `{"streaming_provider":{"service":"torbox","token":<KEY>}}` to
  `/encrypt-user-data`, then use the returned `encrypted_str` in the path
  (cached per token).

`sources(media_type, video_id)` runs every **enabled** scraper in parallel
(`ThreadPoolExecutor`), merges the `Stream`s, and sorts by quality → size →
seeders. A `Stream` carries `scraper`, `title`, `url`, `quality`, `size`,
`seeders`; `ui.Source` wraps it into a playable row. `configured()` reports
whether a TorBox key is set; a scraper is enabled when a key exists and its
`scraper_<name>` toggle isn't off.

Stremio ids: a movie is its IMDb id (`tt…`); an episode is `tt…:season:episode`.

> **Note:** the source URLs are TorBox debrid links, so playable only with a
> valid `torbox_api_key`. Without debrid these add-ons return magnets, which
> native Kodi can't play — hence the debrid requirement.

---

## `trakt.py` — Trakt client & `service.py` — scrobbler

Same shape as `tmdb.py`: a small authed `_request` plus thin endpoint helpers.

- **Credentials.** `CLIENT_ID`/`CLIENT_SECRET` are hardcoded (register an app at
  trakt.tv/oauth/applications, redirect `urn:ietf:wg:oauth:2.0:oob`). Per-user
  OAuth tokens live in **`trakt.json`** in the profile dir — *not* in settings or
  the response cache, so "Clear Cache" can't log you out.
- **Auth.** `authorize()` runs the OAuth **device-code** flow (shows a code + URL
  in a `DialogProgress`, polls for approval). Tokens auto-refresh on expiry / a
  401. `authorized()` / `sign_out()` round it out; the Tools menu toggles between
  Authorize and Sign Out.
- **Reads** return raw Trakt items; `tmdb_ids(items, media)` pulls the TMDB ids
  out (handling each endpoint's wrapper shape). `addon._hydrate()` then fetches
  TMDB details in parallel and renders with the existing `Movies`/`Shows`. So a
  Trakt list reuses all the normal rendering.
- **Writes.** `set_watchlist` / `set_watched` build a sync body from the
  context-menu params (`type`/`tmdb`/`season`/`episode`) and POST to
  `/sync/{watchlist,history}[/remove]`.
- **Scrobble.** `scrobble(action, item, progress)` POSTs `/scrobble/{start,
  pause,stop}`; honours the `trakt_scrobble` setting.

**`service.py`** is a persistent `xbmc.Player` (wired as an `xbmc.service` by
`build.py` because the file exists). On play/pause/stop it reads the playing
item's `VideoInfoTag` — the tmdb uniqueid + mediatype + season/episode that
`Source` attaches — and scrobbles; Trakt marks an item watched once stopped past
~80%. It scrobbles any movie/episode carrying a tmdb id, so disabling
`trakt_scrobble` is the off switch.

---

## Concrete request flow (movie → sources → play)

```
plugin://plugin.video.ember/list/movie/trending?page=1
      │
      ▼  category_list("movie", "trending") → Movies.render() (folder rows)
      │
Select a movie → plugin://.../sources/movie/{tmdb_id}
      │
      ▼  movie_sources(id)
      │    imdb = tmdb.imdb_id("movie", id)
      │    scrapers.sources("movie", imdb)  ──▶  Torrentio / Comet / MediaFusion
      │                                           (parallel, TorBox-resolved urls)
      ▼  Sources(Source(stream) …).render()  ──▶ native list of source rows
      │
Select a source → Kodi plays its resolved URL directly (no resolve callback)
```

Episodes follow the same path via `/sources/episode/{id}/{season}/{episode}`,
building the Stremio id `{imdb}:{season}:{episode}`.
