#!/bin/sh
# Renders the SVG sources into the PNGs Home Assistant loads from
# custom_components/energy_metrics_eon/brand/, following the Home Assistant brand image
# rules (PNG, transparent, trimmed, interlaced; icon 256/512 px square, logo
# 256/512 px on its shortest side). Needs Google Chrome and python3.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
out="$here/../../custom_components/energy_metrics_eon/brand"
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$out"

# The dark logo only differs in its text colour.
sed 's/#1D2233/#FFFFFF/' "$here/logo.svg" > "$here/dark_logo.svg"

render() { # svg width height scale png
  printf '<body style="margin:0;background:transparent"><img src="file://%s" width="%s" height="%s" style="display:block">' \
    "$1" "$2" "$3" > "$tmp/page.html"
  "$chrome" --headless --disable-gpu --hide-scrollbars \
    --default-background-color=00000000 \
    --force-device-scale-factor="$4" --window-size="$2,$3" \
    --screenshot="$5" "file://$tmp/page.html" >/dev/null 2>&1
}

render "$here/icon.svg" 256 256 1 "$out/icon.png"
render "$here/icon.svg" 256 256 2 "$out/icon@2x.png"
render "$here/logo.svg" 960 256 1 "$out/logo.png"
render "$here/logo.svg" 960 256 2 "$out/logo@2x.png"
render "$here/dark_logo.svg" 960 256 1 "$out/dark_logo.png"
render "$here/dark_logo.svg" 960 256 2 "$out/dark_logo@2x.png"

python3 "$here/optimize_png.py" "$out"/*.png
