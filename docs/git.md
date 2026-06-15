# Git conventions

How commits are made in this repo. The goals: a history that reads clearly, in
small reviewable steps, with no build cruft committed.

---

## Before every commit: clean `__pycache__`

Python writes `__pycache__/` directories when modules are imported (the build
and the local verification runs both do this). These must **never** be
committed. Delete them from the start, before staging:

```sh
find . -name __pycache__ -type d -prune -exec rm -rf {} +
```

Then check `git status` to confirm nothing unexpected is staged (no `.pyc`, no
`__pycache__/`, no stray files under `src/`).

---

## Granular commits

Prefer several small, focused commits over one large mixed commit. Each commit
should be one logical change that stands on its own and could be reverted
independently. If a body needs the word "and" to list unrelated changes, it's
probably two commits.

- One concern per commit (a rename, a feature, a refactor, a docs update).
- Keep generated `dist/` changes in the same commit as the source change that
  produced them (rebuilding is part of the change).
- Commit in an order where each step leaves the tree working/buildable.

---

## Commit message format

Standard Git style — a concise subject line, a blank line, then a detailed body.

```
<subject: imperative, ~50 chars, no trailing period>

<body: wrap at ~72 cols. Explain WHAT changed and WHY — the motivation and
any trade-offs — not just the how (the diff already shows the how). Use
bullet points for multiple related details.>

Co-Authored-By: ...
```

Rules of thumb:

- **Subject** is imperative mood ("Add", "Rename", "Hardcode", "Fix") — it
  completes "If applied, this commit will …". No period at the end.
- **Blank line** between subject and body is required.
- **Body** is detailed: say why the change was made, what problem it solves, and
  call out anything non-obvious (a limitation, a follow-up, a deliberate
  omission). Bullet lists are fine and encouraged for multi-part changes.
- Reference the relevant module/area when it helps a future reader scan history.

### Example

```
Hardcode genre/provider/certification browse options

The genres, providers, and certifications sub-menus fetched their options
from TMDB at runtime; genre_map even re-fetched on every list render to
label rows. These option sets are stable, so hardcode them:

- GENRES (movie/tv), PROVIDERS (curated US streamers), CERTIFICATIONS
- genre_map now reads the table -> no per-render API call
- drop the now-dead providers()/certifications() fetchers and TTL_GENRE

IDs were taken from the live TMDB endpoints so they're exact.
```

---

## Workflow checklist

1. `find . -name __pycache__ -type d -prune -exec rm -rf {} +`
2. Rebuild if source changed: `python3 build.py` (see [build.md](framework.md)).
3. `git status` — confirm a clean, intentional set of changes.
4. Stage and commit in granular, logical steps with detailed messages.
5. Push.
