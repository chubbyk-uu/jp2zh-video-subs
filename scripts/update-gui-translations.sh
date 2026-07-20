#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
translations="$root/scripts/jp2zh_gui/translations"
sources=(
    "$root/scripts/jp2zh_gui/app.py"
    "$root/scripts/jp2zh_gui/controller.py"
    "$root/scripts/jp2zh_gui/window.py"
)

pyside6-lupdate -no-obsolete "${sources[@]}" \
    -ts "$translations/jp2zh_zh_CN.ts" "$translations/jp2zh_zh_TW.ts"
pyside6-lrelease -fail-on-unfinished -fail-on-invalid \
    "$translations/jp2zh_zh_CN.ts" "$translations/jp2zh_zh_TW.ts"
