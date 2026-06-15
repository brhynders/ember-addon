# Ember

A clean, English-only Kodi video add-on, distributed as a self-hosted Kodi repository.

## Repository layout

```
ember-addon/
├── README.md              this file
├── index.html            landing / install page (served by GitHub Pages)
├── build.sh              packages src/ into dist/ and rebuilds the repo zip
├── ember.repository.zip  bootstrap repo add-on — users install this first
├── icon.png             shared brand icon
├── src/                  add-on source (the only thing you edit by hand)
│   └── plugin.video.ember/
└── dist/                 GENERATED — served as the live Kodi repository
    ├── addons.xml
    ├── addons.xml.md5
    ├── plugin.video.ember/plugin.video.ember-<ver>.zip
    └── repository.ember/repository.ember-<ver>.zip
```

`dist/` and `ember.repository.zip` are build outputs — never edit them by hand.

## Building / releasing

1. Make changes under `src/plugin.video.ember/`.
2. Bump `version` in `src/plugin.video.ember/addon.xml`.
3. Run the build:

   ```sh
   ./build.sh
   ```

4. Commit and push. GitHub Pages serves the new `dist/`, and Kodi picks up the
   update on its next repository refresh.

Only the **latest** zip per add-on is kept — old versions live in git history.

## Installing in Kodi

1. Download **`ember.repository.zip`**.
2. Kodi → Add-ons → *Install from zip file* → select it.
3. Kodi → Add-ons → *Install from repository* → **Ember Repository** → Video
   add-ons → **Ember**.

After that, updates arrive automatically.

## Hosting

`build.sh` bakes one base URL into the repository add-on (`BASE_URL` at the top
of the script). It currently points at `https://brhynders.github.io`; change
that single line if the hosting location moves, then re-run `./build.sh`.
