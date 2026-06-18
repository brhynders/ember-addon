#!/usr/bin/env python3
"""build.py — single source of truth for a Kodi add-on + its own repository.

Reusable across add-ons: edit the CONFIG block below, then run ./build.py
(or `python3 build.py`). src/ holds ONLY hand-written code — the add-on manifest
and icon are assembled at build time and never written into src/. Generated:

    dist/<id>/<id>-<ver>.zip + dist/addons.xml + dist/addons.xml.md5   live repo
    dist/<repo-id>.zip     bootstrap repo add-on users install first
    dist/index.html        link page so /dist/ is browseable as a Kodi source

The add-on's addon.xml + resources/icon.png exist only inside the packaged zip;
the single committed icon is the root icon.png master.

To cut a release: bump VERSION below, run ./build.py, commit, push.
Only the latest plugin zip is kept; old versions live in git history.

Pass --install to also copy the freshly-built add-on into your local (Windows)
Kodi addons dir for testing — auto-detected from WSL across all Windows users.

Depends only on the Python 3 standard library — no system zip/md5sum needed.
"""

import glob
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile

# === CONFIG =================================================================
# GitHub Pages base URL that serves this repo's files (NO trailing slash).
#   * project pages (repo named "<repo>"):      https://<user>.github.io/<repo>
#   * user pages    (repo named "<user>.github.io"): https://<user>.github.io
BASE_URL = "https://brhynders.github.io/ember-addon"

AUTHOR = "brhynders"  # provider-name for both add-ons

# --- video add-on -----------------------------------------------------------
PLUGIN_ID = "plugin.video.catalyst"
PLUGIN_NAME = "Catalyst"
VERSION = "0.1.0"
SUMMARY = "Catalyst - lightweight movie & TV streaming"
DESCRIPTION = "A clean, English-only streaming browser built from scratch."
LICENSE = "GPL-3.0-or-later"
PYTHON_VERSION = "3.0.0"  # required xbmc.python version

# --- bootstrap repository add-on -------------------------------------------
REPO_ID = "repository.catalyst"
REPO_NAME = "Catalyst Repository"
REPO_VERSION = "1.0.0"

# --- local install (./build.py --install) ----------------------------------
# Leave "" to auto-detect the Windows Kodi addons dir from WSL (scans every
# Windows user, picks the one with Kodi). Set a path (or the KODI_ADDONS_DIR
# env var) to override — e.g. for a Microsoft Store install or an odd location.
KODI_ADDONS_DIR = ""
# ============================================================================

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")
ICON = os.path.join(ROOT, "icon.png")
PLUGIN_ZIP_DIR = os.path.join(DIST, PLUGIN_ID)

EPOCH = (2020, 1, 1, 0, 0, 0)  # fixed zip timestamps -> byte-stable archives


def esc(s):
    """Escape &, <, > for safe XML text/attributes."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_zip(src_dir, arc_prefix, dest):
    """Zip src_dir into dest, each file under arc_prefix/ at the zip root.

    Kodi requires the addon-id folder at the zip root. Skips bytecode/OS cruft;
    fixed timestamps keep the archive byte-stable across rebuilds (no git churn).
    """
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirs, files in os.walk(src_dir):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(files):
                if name.endswith((".pyc", ".pyo")) or name == ".DS_Store":
                    continue
                full = os.path.join(dirpath, name)
                arc = os.path.join(arc_prefix, os.path.relpath(full, src_dir))
                info = zipfile.ZipInfo(arc.replace(os.sep, "/"), date_time=EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read())


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# Windows Kodi addons dirs, reachable from WSL via /mnt/c. The * over Users
# matches only accounts that actually have Kodi installed.
_KODI_GLOBS = (
    "/mnt/c/Users/*/AppData/Roaming/Kodi/addons",
    "/mnt/c/Users/*/AppData/Local/Packages/XBMCFoundation.Kodi_*"
    "/LocalCache/Roaming/Kodi/addons",
)


def find_kodi_addons_dir():
    """Locate the (Windows) Kodi addons dir, or None.

    Honors KODI_ADDONS_DIR (config or env var); otherwise scans every Windows
    user under /mnt/c and returns the first that actually has Kodi installed.
    """
    override = KODI_ADDONS_DIR or os.environ.get("KODI_ADDONS_DIR", "")
    if override:
        return override if os.path.isdir(override) else None
    found = []
    for pattern in _KODI_GLOBS:
        found.extend(sorted(glob.glob(pattern)))
    if len(found) > 1:
        print("  note: Kodi found for multiple users; using the first:")
        for path in found:
            print("    - {0}".format(path))
    return found[0] if found else None


def install_local(plugin_stage):
    """Copy the freshly-staged add-on into the local Kodi addons dir."""
    addons_dir = find_kodi_addons_dir()
    if addons_dir is None:
        print(
            "  ! --install: no Kodi addons dir found "
            "(set KODI_ADDONS_DIR in build.py or the env)"
        )
        return
    dest = os.path.join(addons_dir, PLUGIN_ID)
    print("Installing {0} -> {1}".format(PLUGIN_ID, dest))
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(plugin_stage, dest)
    print("  installed — restart Kodi (or rescan) to pick up the change")


def main():
    if not os.path.isfile(ICON):
        sys.exit("error: missing master icon at {0}".format(ICON))

    install = "--install" in sys.argv[1:]
    stage = tempfile.mkdtemp()
    try:
        plugin_stage = os.path.join(stage, "plugin")
        repo_stage = os.path.join(stage, "repo")

        # --- 1. stage the video add-on (code + generated manifest + icon) ---
        print("Staging {0}...".format(PLUGIN_ID))
        shutil.copytree(SRC, plugin_stage)  # hand-written code
        resources = os.path.join(plugin_stage, "resources")
        os.makedirs(resources, exist_ok=True)
        shutil.copy(ICON, os.path.join(resources, "icon.png"))  # single icon

        service_ext = ""
        if os.path.isfile(os.path.join(SRC, "service.py")):
            service_ext = (
                '    <extension point="xbmc.service" '
                'library="service.py" start="login"/>\n'
            )
            print("  + service.py detected -> adding xbmc.service extension")

        plugin_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<addon id="{id}" name="{name}" version="{ver}" provider-name="{author}">\n'
            "    <requires>\n"
            '        <import addon="xbmc.python" version="{py}"/>\n'
            "    </requires>\n"
            '    <extension point="xbmc.python.pluginsource" library="addon.py">\n'
            "        <provides>video</provides>\n"
            "    </extension>\n"
            '{service}    <extension point="xbmc.addon.metadata">\n'
            "        <reuselanguageinvoker>true</reuselanguageinvoker>\n"
            '        <summary lang="en_GB">{summary}</summary>\n'
            '        <description lang="en_GB">{desc}</description>\n'
            "        <platform>all</platform>\n"
            "        <license>{license}</license>\n"
            "        <assets>\n"
            "            <icon>resources/icon.png</icon>\n"
            "        </assets>\n"
            "    </extension>\n"
            "</addon>\n"
        ).format(
            id=PLUGIN_ID,
            name=esc(PLUGIN_NAME),
            ver=VERSION,
            author=esc(AUTHOR),
            py=PYTHON_VERSION,
            service=service_ext,
            summary=esc(SUMMARY),
            desc=esc(DESCRIPTION),
            license=esc(LICENSE),
        )
        write(os.path.join(plugin_stage, "addon.xml"), plugin_xml)

        # --- 2. package the video add-on into dist/ -------------------------
        print("Packaging {0} {1}...".format(PLUGIN_ID, VERSION))
        os.makedirs(PLUGIN_ZIP_DIR, exist_ok=True)
        for old in os.listdir(PLUGIN_ZIP_DIR):
            if old.endswith(".zip"):
                os.remove(os.path.join(PLUGIN_ZIP_DIR, old))
        write_zip(
            plugin_stage,
            PLUGIN_ID,
            os.path.join(PLUGIN_ZIP_DIR, "{0}-{1}.zip".format(PLUGIN_ID, VERSION)),
        )

        # --- 3. generate dist/addons.xml + md5 ------------------------------
        print("Generating dist/addons.xml...")
        body = plugin_xml.split("\n", 1)[1]  # drop the <?xml ...?> prolog line
        addons_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            "<addons>\n" + body + "</addons>\n"
        )
        write(os.path.join(DIST, "addons.xml"), addons_xml)
        digest = hashlib.md5(addons_xml.encode("utf-8")).hexdigest()
        write(os.path.join(DIST, "addons.xml.md5"), digest + "\n")

        # --- 4. build the bootstrap repository add-on (dist/<repo-id>.zip) ---
        print("Building dist/{0}.zip...".format(REPO_ID))
        os.makedirs(repo_stage, exist_ok=True)
        repo_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<addon id="{id}" name="{name}" version="{ver}" provider-name="{author}">\n'
            '    <extension point="xbmc.addon.repository" name="{name}">\n'
            "        <dir>\n"
            '            <info compressed="false">{url}/dist/addons.xml</info>\n'
            "            <checksum>{url}/dist/addons.xml.md5</checksum>\n"
            '            <datadir zip="true">{url}/dist</datadir>\n'
            "        </dir>\n"
            "    </extension>\n"
            '    <extension point="xbmc.addon.metadata">\n'
            '        <summary lang="en_GB">{plugin} add-on repository</summary>\n'
            '        <description lang="en_GB">Install and update {plugin} from this repository.</description>\n'
            "        <platform>all</platform>\n"
            "        <assets>\n"
            "            <icon>icon.png</icon>\n"
            "        </assets>\n"
            "    </extension>\n"
            "</addon>\n"
        ).format(
            id=REPO_ID,
            name=esc(REPO_NAME),
            ver=REPO_VERSION,
            author=esc(AUTHOR),
            url=BASE_URL,
            plugin=esc(PLUGIN_NAME),
        )
        write(os.path.join(repo_stage, "addon.xml"), repo_xml)
        shutil.copy(ICON, os.path.join(repo_stage, "icon.png"))
        write_zip(repo_stage, REPO_ID, os.path.join(DIST, "{0}.zip".format(REPO_ID)))

        # --- 5. generate dist/index.html so /dist/ is browseable as a source -
        # GitHub Pages has no directory autoindex; this link is what Kodi's HTTP
        # VFS parses so the bootstrap zip shows up when /dist/ is added as a
        # file-manager source. Href is relative to dist/ (the zip sits beside it).
        print("Generating dist/index.html...")
        write(
            os.path.join(DIST, "index.html"),
            '<!doctype html>\n<a href="{repo}.zip">{repo}.zip</a>\n'.format(
                repo=REPO_ID
            ),
        )

        # --- 6. optionally install into the local Kodi (./build.py --install)
        if install:
            install_local(plugin_stage)

    finally:
        shutil.rmtree(stage, ignore_errors=True)

    print()
    print("Done. v{0} -> {1}".format(VERSION, BASE_URL))


if __name__ == "__main__":
    main()
