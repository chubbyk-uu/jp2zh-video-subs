#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 LAB_ROOT [PROXY_URL]" >&2
    exit 2
fi

lab_root="$(realpath "$1")"
proxy_url="${2:-}"
package_root="$lab_root/package/jp2zh-video-subs"
downloads="$lab_root/cache/downloads"
destination="$package_root/bin"
license_destination="$package_root/licenses/ffmpeg"
archive="$downloads/ffmpeg-8.1.2-essentials_build.zip"
expected_sha256="db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"

case "$destination/" in
    "$lab_root/"*) ;;
    *)
        echo "Refusing to write outside lab root: $destination" >&2
        exit 3
        ;;
esac

mkdir -p "$downloads" "$destination" "$license_destination"
proxy_args=()
if [[ -n "$proxy_url" ]]; then
    proxy_args=(--proxy "$proxy_url")
fi

if [[ ! -f "$archive" ]]; then
    curl --fail --location --retry 3 \
        "${proxy_args[@]}" \
        --output "$archive.part" \
        https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip
    mv "$archive.part" "$archive"
fi
printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum --check -

unzip -j -o "$archive" \
    '*/bin/ffmpeg.exe' \
    '*/bin/ffprobe.exe' \
    -d "$destination"
unzip -j -o "$archive" \
    '*/LICENSE' \
    '*/README.txt' \
    -d "$license_destination"

"$destination/ffmpeg.exe" -version | sed -n '1p'
"$destination/ffprobe.exe" -version | sed -n '1p'
printf 'Bundled FFmpeg at %s\n' "$destination"
