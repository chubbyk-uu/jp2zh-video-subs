#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 LAB_ROOT" >&2
    exit 2
fi

lab_root="$(realpath "$1")"
package_root="$lab_root/package/jp2zh-video-subs"
runtime="$package_root/runtime"
downloads="$lab_root/cache/downloads"
pip_cache="$lab_root/cache/pip"
temp_dir="$lab_root/cache/temp"
wheelhouse="$lab_root/cache/windows-wheels"
python_zip="$downloads/python-3.12.10-embed-amd64.zip"
get_pip="$downloads/get-pip.py"
python_zip_sha256="4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
get_pip_sha256="a341e1a43e38001c551a1508a73ff23636a11970b61d901d9a1cad2a18f57055"

case "$runtime/" in
    "$lab_root/"*) ;;
    *)
        echo "Refusing to write outside lab root: $runtime" >&2
        exit 3
        ;;
esac

mkdir -p "$runtime" "$downloads" "$pip_cache" "$temp_dir" "$wheelhouse"

if [[ ! -f "$python_zip" ]]; then
    curl --fail --location --retry 3 \
        --output "$python_zip.part" \
        https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
    mv "$python_zip.part" "$python_zip"
fi
if [[ ! -f "$get_pip" ]]; then
    curl --fail --location --retry 3 \
        --output "$get_pip.part" \
        https://bootstrap.pypa.io/get-pip.py
    mv "$get_pip.part" "$get_pip"
fi
printf '%s  %s\n' "$python_zip_sha256" "$python_zip" | sha256sum --check -
printf '%s  %s\n' "$get_pip_sha256" "$get_pip" | sha256sum --check -

if [[ ! -f "$runtime/python.exe" ]]; then
    unzip -q -o "$python_zip" -d "$runtime"
fi

printf '%s\n' \
    'python312.zip' \
    '.' \
    'Lib\site-packages' \
    '..\app\scripts' \
    'import site' \
    > "$runtime/python312._pth"

get_pip_win="$(wslpath -w "$get_pip")"
pip_cache_win="$(wslpath -w "$pip_cache")"
temp_win="$(wslpath -w "$temp_dir")"
wheelhouse_win="$(wslpath -w "$wheelhouse")"
package_win="$(wslpath -w "$package_root")"

TEMP="$temp_win" TMP="$temp_win" PIP_CACHE_DIR="$pip_cache_win" \
    "$runtime/python.exe" "$get_pip_win" \
    --disable-pip-version-check \
    --no-warn-script-location \
    --no-index \
    --find-links "$wheelhouse_win"

TEMP="$temp_win" TMP="$temp_win" PIP_CACHE_DIR="$pip_cache_win" \
    "$runtime/python.exe" -m pip install \
    --disable-pip-version-check \
    --no-warn-script-location \
    --no-index \
    --find-links "$wheelhouse_win" \
    PySide6==6.11.1

"$runtime/python.exe" -c \
    "import os, pathlib, sys; os.environ['JP2ZH_PORTABLE_ROOT'] = sys.argv[1]; import PySide6, portable_runtime; root = portable_runtime.project_root(); expected = pathlib.Path(sys.argv[1]).resolve(); assert str(root).casefold() == str(expected).casefold(); print(PySide6.__version__); print(root)" \
    "$package_win"

sha256sum "$python_zip" > "$package_root/config/python-runtime.sha256"
printf 'Base runtime assembled at %s\n' "$runtime"
