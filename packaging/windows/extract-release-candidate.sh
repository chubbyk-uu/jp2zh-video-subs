#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 LAB_ROOT" >&2
    exit 2
fi

lab_root="$(realpath "$1")"
release_root="$lab_root/release"
archives="$release_root/archives"
extract_root="$release_root/extracted"

case "$extract_root/" in
    "$lab_root/"*) ;;
    *)
        echo "Refusing to write outside lab root: $extract_root" >&2
        exit 3
        ;;
esac

(
    cd "$archives"
    sha256sum --check SHA256SUMS
)
rm -rf "$extract_root"
mkdir -p "$extract_root"

7z.exe x -y -o"$(wslpath -w "$extract_root")" \
    "$(wslpath -w "$archives/jp2zh-video-subs-windows-x64-cuda-program.7z")"
7z.exe x -y -o"$(wslpath -w "$extract_root")" \
    "$(wslpath -w "$archives/jp2zh-video-subs-default-models.7z")"

test -x "$extract_root/jp2zh-video-subs/runtime/python.exe"
test -x "$extract_root/jp2zh-video-subs/bin/ffmpeg.exe"
test -f "$extract_root/jp2zh-video-subs/models/anime-whisper/model.safetensors"
test -d "$extract_root/jp2zh-video-subs/runtime/Lib/site-packages/transformers/models"
test ! -e "$extract_root/jp2zh-video-subs/config/gui.ini"
test -z "$(find "$extract_root/jp2zh-video-subs/outputs" "$extract_root/jp2zh-video-subs/work" -type f -print -quit)"
"$extract_root/jp2zh-video-subs/runtime/python.exe" -c \
    "from transformers import WhisperForConditionalGeneration, WhisperProcessor; print('Extracted Transformers runtime OK')"

printf 'Fresh extracted candidate: %s\n' "$extract_root/jp2zh-video-subs"
