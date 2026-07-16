#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 LAB_ROOT [all|program|default|qwen-asr|sakura-14b|speaker-gender|models]" >&2
    exit 2
fi

lab_root="$(realpath "$1")"
target="${2:-all}"
release_root="$lab_root/release"
program_stage="$release_root/staging/program"
models_stage="$release_root/staging/models-default"
qwen_stage="$release_root/staging/models-qwen-asr"
sakura_stage="$release_root/staging/models-sakura-14b"
speaker_stage="$release_root/staging/models-speaker-gender"
archives="$release_root/archives"
program_archive="$archives/jp2zh-video-subs-windows-x64-cuda-program.7z"
models_archive="$archives/jp2zh-video-subs-default-models.7z"
qwen_archive="$archives/jp2zh-video-subs-qwen-asr-model.7z"
sakura_archive="$archives/jp2zh-video-subs-sakura-14b-model.7z"
speaker_archive="$archives/jp2zh-video-subs-speaker-gender-model.7z"

case "$target" in
    all|program|default|qwen-asr|sakura-14b|speaker-gender|models) ;;
    *)
        echo "Unknown archive target: $target" >&2
        exit 2
        ;;
esac
case "$archives/" in
    "$lab_root/"*) ;;
    *)
        echo "Refusing to write outside lab root: $archives" >&2
        exit 3
        ;;
esac
if [[ "$target" == all || "$target" == program ]] && [[ ! -x "$program_stage/jp2zh-video-subs/runtime/python.exe" ]]; then
    echo "Missing prepared program stage" >&2
    exit 4
fi
if ! command -v 7z.exe >/dev/null 2>&1; then
    echo "7z.exe is required to build release archives" >&2
    exit 6
fi

mkdir -p "$archives"
if [[ "$target" == all || "$target" == program ]]; then
    rm -f "$program_archive"
    (
        cd "$program_stage"
        7z.exe a -t7z -mx=1 -mmt=on "$(wslpath -w "$program_archive")" jp2zh-video-subs
    )
fi

archive_model_stage() {
    local requested="$1"
    local stage="$2"
    local archive="$3"
    local sentinel="$4"
    if [[ "$target" != all && "$target" != models && "$target" != "$requested" ]]; then
        return
    fi
    if [[ ! -e "$stage/jp2zh-video-subs/models/$sentinel" ]]; then
        echo "Missing prepared $requested model stage" >&2
        exit 5
    fi
    rm -f "$archive"
    (
        cd "$stage"
        7z.exe a -t7z -mx=0 -mmt=on "$(wslpath -w "$archive")" jp2zh-video-subs
    )
}

archive_model_stage default "$models_stage" "$models_archive" anime-whisper
archive_model_stage qwen-asr "$qwen_stage" "$qwen_archive" Qwen3-ASR-1.7B
archive_model_stage sakura-14b "$sakura_stage" "$sakura_archive" Sakura-14B-Qwen2.5-v1.0-GGUF
archive_model_stage speaker-gender "$speaker_stage" "$speaker_archive" voice-gender-classifier

(
    cd "$archives"
    find . -maxdepth 1 -type f -name 'jp2zh-video-subs-*.7z' -printf '%f\n' |
        sort |
        xargs -r sha256sum > SHA256SUMS
)
printf 'Archives written to %s\n' "$archives"
