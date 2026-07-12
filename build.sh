#!/usr/bin/env bash
# Copyright (C) 2026 Ethan Martin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

set -euo pipefail

TAG=""
SKIP_WEB=false

print_usage() {
    echo "Usage: $0 -t|--tag <tag_name> [-s|--skip-web]"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -t|--tag)
            if [[ -n "${2:-}" && ! "${2}" =~ ^- ]]; then
                TAG="$2"
                shift 2
            else
                echo "Error: Argument for $1 is missing." >&2
                print_usage
            fi
            ;;
        -s|--skip-web)
            SKIP_WEB=true
            shift 1
            ;;
        *)
            echo "Error: Unknown option $1" >&2
            print_usage
            ;;
    esac
done

if [[ -z "$TAG" ]]; then
    echo "Error: The -t/--tag argument is required." >&2
    print_usage
fi

sed -i "s/export const version = '.*';/export const version = '${TAG}';/" ~/Programming/azalea-web/src/lib/stores/settings.svelte.ts

if [ -f "core.toml" ]; then
    sed -i "s/^version = \".*\"/version = \"${TAG}\"/" core.toml
else
    echo "Error: core.toml not found." >&2
    exit 1
fi

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
SRC_DIR="$SCRIPT_DIR/src"

echo "=== Cleaning up previous source directory ==="
rm -rf "$SRC_DIR"
mkdir -p "$SRC_DIR"

if [ "$SKIP_WEB" = false ]; then
    echo "=== Compiling Frontend Assets ==="
    rm -rf build
    cd ../azalea-web
    rm -rf build
    pnpm build
    cd ../azalea
    mv ../azalea-web/build .
else
    echo "=== Skipping Frontend Compilation (--skip-web active) ==="
fi

echo "=== Copying backend files (azalea) ==="
for f in "$SCRIPT_DIR"/*.py; do
    [ -f "$f" ] && cp "$f" "$SRC_DIR/"
done

for f in "$SCRIPT_DIR"/*.toml "$SCRIPT_DIR"/requirements.txt "$SCRIPT_DIR"/installer.iss "$SCRIPT_DIR"/app_icon.ico "$SCRIPT_DIR"/wizard_image.png "$SCRIPT_DIR"/wizard_small_image.png "$SCRIPT_DIR"/LICENSE "$SCRIPT_DIR"/README.md "$SCRIPT_DIR"/core.toml; do
    [ -f "$f" ] && cp "$f" "$SRC_DIR/"
done

for d in templates static docs builtin; do
    [ -d "$SCRIPT_DIR/$d" ] && cp -r "$SCRIPT_DIR/$d" "$SRC_DIR/$d"
done

echo "=== Copying frontend files (azalea-web) ==="
WEB_DIR="$SRC_DIR/azalea-web"
mkdir -p "$WEB_DIR"

FRONTEND_DIRS=(src static)
if [ "$SKIP_WEB" = false ] || [ -d "./build" ]; then
    FRONTEND_DIRS=(build src static)
    [ -d "./build" ] && [ ! -d ~/Programming/azalea-web/build ] && cp -r ./build ~/Programming/azalea-web/ 2>/dev/null || true
fi

for d in "${FRONTEND_DIRS[@]}"; do
    [ -d ~/Programming/azalea-web/"$d" ] && cp -r ~/Programming/azalea-web/"$d" "$WEB_DIR/$d"
done

for f in ~/Programming/azalea-web/package.json ~/Programming/azalea-web/svelte.config.js ~/Programming/azalea-web/vite.config.ts ~/Programming/azalea-web/tsconfig.json ~/Programming/azalea-web/.npmrc ~/Programming/azalea-web/.prettierrc ~/Programming/azalea-web/.prettierignore ~/Programming/azalea-web/eslint.config.js ~/Programming/azalea-web/components.json ~/Programming/azalea-web/pnpm-lock.yaml ~/Programming/azalea-web/pnpm-workspace.yaml ~/Programming/azalea-web/capacitor.config.ts; do
    [ -f "$f" ] && cp "$f" "$WEB_DIR/"
done

echo "=== Updating installer.iss metadata & version tags ==="
if [ -f "$SCRIPT_DIR/installer.iss" ]; then
    sed -i "s/^OutputBaseFilename=.*/OutputBaseFilename=Azalea ${TAG} Setup/" "$SCRIPT_DIR/installer.iss"
    sed -i "s/^AppVersion=.*/AppVersion=${TAG}/" "$SCRIPT_DIR/installer.iss"
fi

echo "=== Done. Contents of $SRC_DIR ==="
ls -la "$SRC_DIR"
echo ""
ls -la "$SRC_DIR"/azalea-web/

WINEDEBUG=-all wine "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss && cp "Azalea ${TAG} Setup.exe" ~/Videos/Movies/
