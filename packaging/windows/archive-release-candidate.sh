#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 LAB_ROOT [all|program|models]" >&2
    exit 2
fi

lab_root="$(realpath "$1")"
target="${2:-all}"
release_root="$lab_root/release"
program_stage="$release_root/staging/program"
models_stage="$release_root/staging/models-default"
archives="$release_root/archives"
program_archive="$archives/jp2zh-video-subs-windows-x64-cuda-program.7z"
models_archive="$archives/jp2zh-video-subs-default-models.7z"

case "$target" in
    all|program|models) ;;
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
if [[ "$target" != models && ! -x "$program_stage/jp2zh-video-subs/runtime/python.exe" ]]; then
    echo "Missing prepared program stage" >&2
    exit 4
fi
if [[ "$target" != program && ! -d "$models_stage/jp2zh-video-subs/models/anime-whisper" ]]; then
    echo "Missing prepared default model stage" >&2
    exit 5
fi
if ! command -v 7z.exe >/dev/null 2>&1; then
    echo "7z.exe is required to build release archives" >&2
    exit 6
fi

mkdir -p "$archives"
if [[ "$target" != models ]]; then
    rm -f "$program_archive"
    (
        cd "$program_stage"
        7z.exe a -t7z -mx=1 -mmt=on "$(wslpath -w "$program_archive")" jp2zh-video-subs
    )
fi
if [[ "$target" != program ]]; then
    rm -f "$models_archive"
    (
        cd "$models_stage"
        7z.exe a -t7z -mx=0 -mmt=on "$(wslpath -w "$models_archive")" jp2zh-video-subs
    )
fi

(
    cd "$archives"
    if [[ ! -f "$(basename "$program_archive")" || ! -f "$(basename "$models_archive")" ]]; then
        echo "Both program and model archives are required for SHA256SUMS" >&2
        exit 7
    fi
    sha256sum \
        "$(basename "$program_archive")" \
        "$(basename "$models_archive")" \
        > SHA256SUMS
)
printf 'Archives written to %s\n' "$archives"
