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
for archive in \
    jp2zh-video-subs-qwen-asr-model.7z \
    jp2zh-video-subs-sakura-14b-model.7z \
    jp2zh-video-subs-speaker-gender-model.7z; do
    if [[ -f "$archives/$archive" ]]; then
        7z.exe x -y -o"$(wslpath -w "$extract_root")" \
            "$(wslpath -w "$archives/$archive")"
    fi
done

test -x "$extract_root/jp2zh-video-subs/runtime/python.exe"
test -x "$extract_root/jp2zh-video-subs/bin/ffmpeg.exe"
test -x "$extract_root/jp2zh-video-subs/jp2zh-subtitle-tool.exe"
test ! -e "$extract_root/jp2zh-video-subs/jp2zh字幕工具.exe"
test ! -e "$extract_root/jp2zh-video-subs/启动字幕工具.cmd"
test ! -e "$extract_root/jp2zh-video-subs/启动字幕工具-调试.cmd"
test -f "$extract_root/jp2zh-video-subs/models/anime-whisper/model.safetensors"
test -f "$extract_root/jp2zh-video-subs/models/Qwen3-ASR-1.7B/config.json"
test -f "$extract_root/jp2zh-video-subs/models/Sakura-14B-Qwen2.5-v1.0-GGUF/sakura-14b-qwen2.5-v1.0-iq4xs.gguf"
test -f "$extract_root/jp2zh-video-subs/models/voice-gender-classifier/model.safetensors"
test -d "$extract_root/jp2zh-video-subs/runtime/Lib/site-packages/transformers/models"
test -f "$extract_root/jp2zh-video-subs/app/scripts/jp2zh_gui/translations/languages.json"
test -f "$extract_root/jp2zh-video-subs/app/scripts/jp2zh_gui/translations/jp2zh_zh_CN.qm"
test -f "$extract_root/jp2zh-video-subs/app/scripts/jp2zh_gui/translations/jp2zh_zh_TW.qm"
test ! -e "$extract_root/jp2zh-video-subs/config/gui.ini"
test ! -e "$extract_root/jp2zh-video-subs/config/jp2zh-video-subs.lock"
test -z "$(find "$extract_root/jp2zh-video-subs/outputs" "$extract_root/jp2zh-video-subs/work" -type f -print -quit)"
"$extract_root/jp2zh-video-subs/runtime/python.exe" -c \
    "from transformers import WhisperForConditionalGeneration, WhisperProcessor; print('Extracted Transformers runtime OK')"

printf 'Fresh extracted candidate: %s\n' "$extract_root/jp2zh-video-subs"
