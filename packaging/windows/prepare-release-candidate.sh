#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 VERIFIED_PACKAGE_ROOT LAB_ROOT" >&2
    exit 2
fi

source_root="$(realpath "$1")"
lab_root="$(realpath "$2")"
release_root="$lab_root/release"
program_stage="$release_root/staging/program/jp2zh-video-subs"
models_stage="$release_root/staging/models-default/jp2zh-video-subs"

case "$release_root/" in
    "$lab_root/"*) ;;
    *)
        echo "Refusing to write outside lab root: $release_root" >&2
        exit 3
        ;;
esac
if [[ ! -x "$source_root/runtime/python.exe" ]]; then
    echo "Verified package runtime is missing: $source_root/runtime/python.exe" >&2
    exit 4
fi

rm -rf "$release_root/staging"
mkdir -p "$program_stage" "$models_stage/models" "$models_stage/config"

rsync -a --delete \
    --link-dest="$source_root" \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '/cache/***' \
    --exclude '/config/gui.ini' \
    --exclude '/config/models-default.sha256' \
    --exclude '/config/python-runtime.sha256' \
    --exclude '/models/***' \
    --exclude '/outputs/***' \
    --exclude '/work/***' \
    "$source_root/" "$program_stage/"

mkdir -p \
    "$program_stage/cache/huggingface" \
    "$program_stage/cache/numba" \
    "$program_stage/cache/temp" \
    "$program_stage/cache/torch" \
    "$program_stage/models" \
    "$program_stage/outputs" \
    "$program_stage/work"
if [[ ! -d "$program_stage/runtime/Lib/site-packages/transformers/models" ]]; then
    echo "Prepared runtime is incomplete: transformers/models is missing" >&2
    exit 5
fi

for name in anime-whisper whisperseg Qwen3-ForcedAligner-0.6B Sakura-GalTransl-7B-v3.7-GGUF; do
    rsync -a --delete \
        --link-dest="$source_root/models/$name" \
        --exclude '.cache/' \
        "$source_root/models/$name/" "$models_stage/models/$name/"
done
if [[ -d "$source_root/licenses/models" ]]; then
    mkdir -p "$models_stage/licenses"
    rsync -a --delete \
        --link-dest="$source_root/licenses/models" \
        "$source_root/licenses/models/" "$models_stage/licenses/models/"
fi

generate_manifest() {
    local root="$1"
    local output="$2"
    local excluded_relative="${output#"$root/"}"
    local sizes_file hashes_file
    mkdir -p "$(dirname "$output")"
    sizes_file="$(mktemp "$release_root/.manifest-sizes.XXXXXX")"
    hashes_file="$(mktemp "$release_root/.manifest-hashes.XXXXXX")"
    trap 'rm -f "$sizes_file" "$hashes_file"' RETURN
    (
        cd "$root"
        find . -type f ! -path "./$excluded_relative" -printf '%P\t%s\n' |
            sort > "$sizes_file"
        find . -type f ! -path "./$excluded_relative" -print0 |
            sort -z |
            xargs -0 sha256sum > "$hashes_file"
    )
    {
        printf '# sha256  bytes  relative_path\n'
        awk '
            NR == FNR {
                tab = index($0, "\t")
                sizes[substr($0, 1, tab - 1)] = substr($0, tab + 1)
                next
            }
            {
                hash = substr($0, 1, 64)
                path = substr($0, 67)
                sub(/^\.\//, "", path)
                print hash "  " sizes[path] "  " path
            }
        ' "$sizes_file" "$hashes_file"
    } > "$output"
    rm -f "$sizes_file" "$hashes_file"
    trap - RETURN
}

generate_manifest "$program_stage" "$program_stage/config/program-files.sha256"
generate_manifest "$models_stage" "$models_stage/config/models-default.sha256"

if rg -a -l \
    'jp2zh-win-portable-lab|/mnt/[a-z]/|\\\\wsl\\.localhost' \
    "$program_stage/app" "$program_stage/config" "$program_stage"/*.cmd >/dev/null 2>&1; then
    echo "Release candidate contains a development-machine path" >&2
    rg -a -l \
        'jp2zh-win-portable-lab|/mnt/[a-z]/|\\\\wsl\\.localhost' \
        "$program_stage/app" "$program_stage/config" "$program_stage"/*.cmd >&2
    exit 6
fi

printf 'Program stage: %s\n' "$program_stage"
printf 'Default model stage: %s\n' "$models_stage"
