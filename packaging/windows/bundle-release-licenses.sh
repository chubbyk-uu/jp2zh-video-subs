#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 PACKAGE_ROOT [PROXY_URL]" >&2
    exit 2
fi

package_root="$(realpath "$1")"
proxy_url="${2:-}"
licenses="$package_root/licenses"
qt_licenses="$licenses/qt-pyside"
model_licenses="$licenses/models"

case "$licenses/" in
    "$package_root/"*) ;;
    *)
        echo "Refusing to write outside package root: $licenses" >&2
        exit 3
        ;;
esac

proxy_args=()
if [[ -n "$proxy_url" ]]; then
    proxy_args=(--proxy "$proxy_url")
fi
mkdir -p "$qt_licenses" "$model_licenses"

download() {
    local url="$1"
    local output="$2"
    curl --fail --location --retry 3 \
        "${proxy_args[@]}" \
        --output "$output.part" \
        "$url"
    mv "$output.part" "$output"
}

download https://www.gnu.org/licenses/lgpl-3.0.txt "$qt_licenses/LGPL-3.0.txt"
download https://www.gnu.org/licenses/gpl-3.0.txt "$qt_licenses/GPL-3.0.txt"
download https://doc.qt.io/qtforpython-6/licenses.html "$qt_licenses/Qt-for-Python-third-party-licenses.html"
download https://www.qt.io/development/open-source-lgpl-obligations "$qt_licenses/Qt-LGPL-obligations.html"

download https://opensource.org/license/mit "$model_licenses/MIT.html"
download https://www.apache.org/licenses/LICENSE-2.0.txt "$model_licenses/Apache-2.0.txt"
download https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.txt \
    "$model_licenses/CC-BY-NC-SA-4.0.txt"
download https://huggingface.co/litagin/anime-whisper/raw/main/README.md \
    "$model_licenses/anime-whisper-README.md"
download https://huggingface.co/TransWithAI/Whisper-Vad-EncDec-ASMR-onnx/raw/main/README.md \
    "$model_licenses/whisperseg-README.md"
download https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B/raw/main/README.md \
    "$model_licenses/qwen-forced-aligner-README.md"
download https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7/raw/main/README.md \
    "$model_licenses/sakura-galtransl-README.md"
download https://huggingface.co/Qwen/Qwen3-ASR-1.7B/raw/main/README.md \
    "$model_licenses/qwen-asr-README.md"
download https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF/raw/main/README.md \
    "$model_licenses/sakura-14b-README.md"
download https://huggingface.co/JaesungHuh/voice-gender-classifier/raw/main/README.md \
    "$model_licenses/voice-gender-classifier-README.md"
install -m 0644 \
    "$(dirname "$0")/MODEL_LICENSE_STATUS.txt" \
    "$model_licenses/MODEL_LICENSE_STATUS.txt"

printf 'Release license material written to %s\n' "$licenses"
