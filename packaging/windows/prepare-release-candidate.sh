#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: $0 VERIFIED_PACKAGE_ROOT LAB_ROOT [all|program|default|qwen-asr|sakura-14b|speaker-gender|models]" >&2
    exit 2
fi

source_root="$(realpath "$1")"
lab_root="$(realpath "$2")"
target="${3:-all}"
release_root="$lab_root/release"
program_stage="$release_root/staging/program/jp2zh-video-subs"
models_stage="$release_root/staging/models-default/jp2zh-video-subs"
qwen_stage="$release_root/staging/models-qwen-asr/jp2zh-video-subs"
sakura_stage="$release_root/staging/models-sakura-14b/jp2zh-video-subs"
speaker_stage="$release_root/staging/models-speaker-gender/jp2zh-video-subs"

case "$target" in
    all|program|default|qwen-asr|sakura-14b|speaker-gender|models) ;;
    *)
        echo "Unknown staging target: $target" >&2
        exit 2
        ;;
esac
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

if [[ "$target" == all ]]; then
    rm -rf "$release_root/staging"
else
    case "$target" in
        program) rm -rf "$(dirname "$program_stage")" ;;
        default) rm -rf "$(dirname "$models_stage")" ;;
        qwen-asr) rm -rf "$(dirname "$qwen_stage")" ;;
        sakura-14b) rm -rf "$(dirname "$sakura_stage")" ;;
        speaker-gender) rm -rf "$(dirname "$speaker_stage")" ;;
        models)
            rm -rf \
                "$(dirname "$models_stage")" \
                "$(dirname "$qwen_stage")" \
                "$(dirname "$sakura_stage")" \
                "$(dirname "$speaker_stage")"
            ;;
    esac
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

stage_model_package() {
    local stage="$1"
    shift
    local model
    mkdir -p "$stage/models" "$stage/config" "$stage/licenses/models"
    for model in "$@"; do
        if [[ ! -d "$source_root/models/$model" ]]; then
            echo "Missing source model directory: $source_root/models/$model" >&2
            exit 7
        fi
        rsync -a --delete \
            --link-dest="$source_root/models/$model" \
            --exclude '.cache/' \
            "$source_root/models/$model/" "$stage/models/$model/"
    done
    install -m 0644 \
        "$(dirname "$0")/MODEL_LICENSE_STATUS.txt" \
        "$stage/licenses/models/MODEL_LICENSE_STATUS.txt"
}

copy_license_file() {
    local stage="$1"
    local name="$2"
    if [[ ! -f "$source_root/licenses/models/$name" ]]; then
        echo "Missing model license material: $source_root/licenses/models/$name" >&2
        exit 8
    fi
    install -m 0644 \
        "$source_root/licenses/models/$name" \
        "$stage/licenses/models/$name"
}

if [[ "$target" == all || "$target" == program ]]; then
    mkdir -p "$program_stage"
    rsync -a --delete \
        --link-dest="$source_root" \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude '/cache/***' \
        --exclude '/config/gui.ini' \
        --exclude '/config/models-*.sha256' \
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
    generate_manifest "$program_stage" "$program_stage/config/program-files.sha256"
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
fi

if [[ "$target" == all || "$target" == models || "$target" == default ]]; then
    stage_model_package "$models_stage" \
        anime-whisper whisperseg Qwen3-ForcedAligner-0.6B Sakura-GalTransl-7B-v3.7-GGUF
    for name in MIT.html Apache-2.0.txt CC-BY-NC-SA-4.0.txt anime-whisper-README.md \
        whisperseg-README.md qwen-forced-aligner-README.md sakura-galtransl-README.md; do
        copy_license_file "$models_stage" "$name"
    done
    generate_manifest "$models_stage" "$models_stage/config/models-default.sha256"
    printf 'Default model stage: %s\n' "$models_stage"
fi

if [[ "$target" == all || "$target" == models || "$target" == qwen-asr ]]; then
    stage_model_package "$qwen_stage" Qwen3-ASR-1.7B
    for name in Apache-2.0.txt qwen-asr-README.md; do
        copy_license_file "$qwen_stage" "$name"
    done
    generate_manifest "$qwen_stage" "$qwen_stage/config/models-qwen-asr.sha256"
    printf 'Qwen ASR model stage: %s\n' "$qwen_stage"
fi

if [[ "$target" == all || "$target" == models || "$target" == sakura-14b ]]; then
    stage_model_package "$sakura_stage" Sakura-14B-Qwen2.5-v1.0-GGUF
    for name in CC-BY-NC-SA-4.0.txt sakura-14b-README.md; do
        copy_license_file "$sakura_stage" "$name"
    done
    generate_manifest "$sakura_stage" "$sakura_stage/config/models-sakura-14b.sha256"
    printf 'Sakura 14B model stage: %s\n' "$sakura_stage"
fi

if [[ "$target" == all || "$target" == models || "$target" == speaker-gender ]]; then
    stage_model_package "$speaker_stage" voice-gender-classifier
    for name in MIT.html voice-gender-classifier-README.md; do
        copy_license_file "$speaker_stage" "$name"
    done
    generate_manifest "$speaker_stage" "$speaker_stage/config/models-speaker-gender.sha256"
    printf 'Speaker gender model stage: %s\n' "$speaker_stage"
fi
