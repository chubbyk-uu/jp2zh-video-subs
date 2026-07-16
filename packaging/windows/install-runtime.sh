#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 LAB_ROOT" >&2
    exit 2
fi

lab_root="$(realpath "$1")"
runtime="$lab_root/package/jp2zh-video-subs/runtime"
lock_file="$(dirname "$0")/runtime-lock.txt"

if [[ ! -x "$runtime/python.exe" ]]; then
    echo "Missing portable Python: $runtime/python.exe" >&2
    exit 3
fi

mapfile -t packages < <(
    sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$lock_file"
)

"$(dirname "$0")/install-offline-wheels.sh" \
    "$lab_root" \
    --no-deps \
    "${packages[@]}"

"$runtime/python.exe" -c \
    "import accelerate, librosa, nagisa, numpy, onnxruntime, qwen_asr, scipy, sklearn, soundfile, torch, transformers; from llama_cpp import Llama; from PySide6 import QtCore; assert torch.__version__ == '2.11.0+cu128'; assert transformers.__version__ == '4.57.6'; print('Portable inference imports OK')"

printf 'Pinned Windows inference runtime installed at %s\n' "$runtime"
