#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 SOURCE_ROOT PACKAGE_ROOT" >&2
    exit 2
fi

source_root="$(realpath "$1")"
package_root="$(realpath "$2")"
compiler="${MINGW_CC:-x86_64-w64-mingw32-gcc}"
resource_compiler="${MINGW_WINDRES:-x86_64-w64-mingw32-windres}"

if ! command -v "$compiler" >/dev/null 2>&1; then
    echo "Missing MinGW cross compiler: $compiler" >&2
    exit 3
fi
if ! command -v "$resource_compiler" >/dev/null 2>&1; then
    echo "Missing MinGW resource compiler: $resource_compiler" >&2
    exit 3
fi
if [[ ! -x "$package_root/runtime/pythonw.exe" ]]; then
    echo "Missing portable runtime: $package_root/runtime/pythonw.exe" >&2
    exit 4
fi

resource_object="$(mktemp --suffix=.o)"
trap 'rm -f "$resource_object"' EXIT

(
    cd "$source_root/packaging/windows"
    "$resource_compiler" launcher.rc -O coff -o "$resource_object"
)

"$compiler" \
    -municode \
    -mwindows \
    -Os \
    -s \
    "$source_root/packaging/windows/launcher.c" \
    "$resource_object" \
    -o "$package_root/jp2zh字幕工具.exe"

printf 'Launcher written to %s\n' "$package_root/jp2zh字幕工具.exe"
