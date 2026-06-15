#!/usr/bin/env bash
#
# Build the Ember Kodi repository.
#
#   * packages each addon under src/ into dist/<id>/<id>-<version>.zip
#   * generates the bootstrap repository addon (no source kept in the tree)
#     into both dist/ (so it can self-update) and ./ember.repository.zip
#   * regenerates dist/addons.xml + dist/addons.xml.md5
#
# Re-run after bumping a version in any src/<addon>/addon.xml.
#
set -euo pipefail

# --- config -----------------------------------------------------------------
# Where the *contents of dist/* are served. Change this one line if hosting
# moves (e.g. a project repo would be https://brhynders.github.io/ember-addon).
BASE_URL="https://brhynders.github.io"
DATADIR_URL="${BASE_URL}/dist"

# The bootstrap repository addon (generated, not stored in src/).
REPO_ID="repository.ember"
REPO_NAME="Ember Repository"
REPO_VERSION="1.0.0"
PROVIDER="brhynders"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${ROOT}/src"
DIST="${ROOT}/dist"

# --- helpers ----------------------------------------------------------------
addon_version() { # <addon-dir> -> version attribute from its addon.xml
    sed -n 's/.*<addon[^>]*version="\([^"]*\)".*/\1/p' "$1/addon.xml" | head -n1
}

# Zip <parent>/<id> into <dest-zip>, keeping the <id> folder at the zip root
# (Kodi requires that). Skips bytecode and OS cruft. Uses Python's stdlib so
# the build needs no system 'zip'.
zip_addon() { # <parent-dir> <id> <dest-zip>
    python3 - "$1" "$2" "$3" <<'PY'
import os, sys, zipfile
parent, top, dest = sys.argv[1:4]
root = os.path.join(parent, top)
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith((".pyc", ".pyo")) or name == ".DS_Store":
                continue
            full = os.path.join(dirpath, name)
            z.write(full, os.path.relpath(full, parent))
PY
}

# Write the generated repository addon's source into <tmp>/<REPO_ID>/.
write_repo_addon() { # <tmp-dir>
    local dir="$1/${REPO_ID}"
    mkdir -p "${dir}"
    [ -f "${ROOT}/icon.png" ] && cp "${ROOT}/icon.png" "${dir}/icon.png"
    cat > "${dir}/addon.xml" <<EOF
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="${REPO_ID}" name="${REPO_NAME}" version="${REPO_VERSION}" provider-name="${PROVIDER}">
    <extension point="xbmc.addon.repository" name="${REPO_NAME}">
        <dir>
            <info compressed="false">${DATADIR_URL}/addons.xml</info>
            <checksum>${DATADIR_URL}/addons.xml.md5</checksum>
            <datadir zip="true">${DATADIR_URL}</datadir>
        </dir>
    </extension>
    <extension point="xbmc.addon.metadata">
        <summary lang="en_GB">Ember add-on repository</summary>
        <description lang="en_GB">Install and auto-update Ember from this repository.</description>
        <platform>all</platform>
        <assets>
            <icon>icon.png</icon>
        </assets>
    </extension>
</addon>
EOF
}

# Concatenate the <addon> blocks of every passed addon.xml into dist/addons.xml
# and write its md5 checksum alongside.
generate_index() { # <addon.xml>...
    {
        echo '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        echo '<addons>'
        for f in "$@"; do
            sed '1{/^<?xml/d;}' "${f}"   # drop each file's XML prolog, keep <addon>..</addon>
        done
        echo '</addons>'
    } > "${DIST}/addons.xml"
    ( cd "${DIST}" && md5sum addons.xml | cut -d' ' -f1 > addons.xml.md5 )
}

# --- build ------------------------------------------------------------------
command -v python3 >/dev/null || { echo "error: 'python3' is not installed"; exit 1; }
command -v md5sum >/dev/null  || { echo "error: 'md5sum' is not installed"; exit 1; }
mkdir -p "${DIST}"

echo "Packaging plugin.video.ember..."
PLUGIN_VER="$(addon_version "${SRC}/plugin.video.ember")"
mkdir -p "${DIST}/plugin.video.ember"
rm -f "${DIST}/plugin.video.ember/"*.zip
zip_addon "${SRC}" "plugin.video.ember" "${DIST}/plugin.video.ember/plugin.video.ember-${PLUGIN_VER}.zip"
echo "  -> ${PLUGIN_VER}"

echo "Generating ${REPO_ID}..."
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
write_repo_addon "${TMP}"
mkdir -p "${DIST}/${REPO_ID}"
rm -f "${DIST}/${REPO_ID}/"*.zip
zip_addon "${TMP}" "${REPO_ID}" "${DIST}/${REPO_ID}/${REPO_ID}-${REPO_VERSION}.zip"   # self-update copy
zip_addon "${TMP}" "${REPO_ID}" "${ROOT}/ember.repository.zip"                          # root bootstrap
echo "  -> ${REPO_VERSION}"

echo "Generating dist/addons.xml..."
generate_index "${SRC}/plugin.video.ember/addon.xml" "${TMP}/${REPO_ID}/addon.xml"

echo
echo "Done."
echo "  serve dist/ at: ${DATADIR_URL}"
echo "  install first : ember.repository.zip"
