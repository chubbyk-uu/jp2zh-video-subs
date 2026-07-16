#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "Usage: $0 SOURCE_MODELS PACKAGE_ROOT default|all MANIFEST_PATH" >&2
    exit 2
fi

source_models="$(realpath "$1")"
package_root="$(realpath "$2")"
model_set="$3"
manifest="$(realpath -m "$4")"
destination="$package_root/models"

case "$destination/" in
    "$package_root/"*) ;;
    *)
        echo "Refusing to write outside package root: $destination" >&2
        exit 3
        ;;
esac
case "$manifest" in
    "$package_root"/*) ;;
    *)
        echo "Manifest must stay inside package root: $manifest" >&2
        exit 4
        ;;
esac

default_models=(
    anime-whisper
    whisperseg
    Qwen3-ForcedAligner-0.6B
    Sakura-GalTransl-7B-v3.7-GGUF
)
optional_models=(
    Qwen3-ASR-1.7B
    Sakura-14B-Qwen2.5-v1.0-GGUF
    voice-gender-classifier
)

case "$model_set" in
    default) selected=("${default_models[@]}") ;;
    all) selected=("${default_models[@]}" "${optional_models[@]}") ;;
    *)
        echo "Unknown model set: $model_set" >&2
        exit 5
        ;;
esac

mkdir -p "$destination" "$(dirname "$manifest")"
for name in "${selected[@]}"; do
    source_path="$source_models/$name"
    if [[ ! -d "$source_path" ]]; then
        echo "Missing source model directory: $source_path" >&2
        exit 6
    fi
    mkdir -p "$destination/$name"
    rsync -a --delete "$source_path/" "$destination/$name/"
done

{
    printf '# sha256  bytes  relative_path\n'
    for name in "${selected[@]}"; do
        find "$destination/$name" -type f -print0
    done |
        sort -z |
        while IFS= read -r -d '' file; do
            hash="$(sha256sum "$file" | cut -d ' ' -f 1)"
            size="$(stat -c '%s' "$file")"
            relative="${file#"$package_root/"}"
            printf '%s  %s  %s\n' "$hash" "$size" "$relative"
        done
} > "$manifest"

printf 'Copied model set %s and wrote %s\n' "$model_set" "$manifest"
