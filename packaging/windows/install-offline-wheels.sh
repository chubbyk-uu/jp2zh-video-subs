#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 LAB_ROOT PACKAGE..." >&2
    exit 2
fi

lab_root="$(realpath "$1")"
shift
runtime="$lab_root/package/jp2zh-video-subs/runtime"
wheelhouse="$lab_root/cache/windows-wheels"
temp_dir="$lab_root/cache/temp"

case "$runtime/" in
    "$lab_root/"*) ;;
    *)
        echo "Refusing to use runtime outside lab root: $runtime" >&2
        exit 3
        ;;
esac

if [[ ! -x "$runtime/python.exe" ]]; then
    echo "Missing portable Python: $runtime/python.exe" >&2
    exit 4
fi

wheelhouse_win="$(wslpath -w "$wheelhouse")"
temp_win="$(wslpath -w "$temp_dir")"

TEMP="$temp_win" TMP="$temp_win" \
    "$runtime/python.exe" -m pip install \
    --disable-pip-version-check \
    --no-warn-script-location \
    --no-index \
    --find-links "$wheelhouse_win" \
    "$@"
