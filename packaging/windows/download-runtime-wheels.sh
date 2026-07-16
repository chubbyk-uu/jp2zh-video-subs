#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 LAB_ROOT [PROXY_URL]" >&2
    exit 2
fi

lab_root="$(realpath "$1")"
proxy_url="${2:-}"
wheelhouse="$lab_root/cache/windows-wheels"
lock_file="$(dirname "$0")/runtime-lock.txt"

case "$wheelhouse/" in
    "$lab_root/"*) ;;
    *)
        echo "Refusing to write outside lab root: $wheelhouse" >&2
        exit 3
        ;;
esac

mkdir -p "$wheelhouse"
proxy_args=()
curl_proxy_args=()
if [[ -n "$proxy_url" ]]; then
    proxy_args=(--proxy "$proxy_url")
    curl_proxy_args=(--proxy "$proxy_url")
fi

mapfile -t pypi_packages < <(
    sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$lock_file" |
        rg -v '^(torch|torchaudio|llama-cpp-python)=='
)

python -m pip download \
    "${proxy_args[@]}" \
    --disable-pip-version-check \
    --only-binary=:all: \
    --platform win_amd64 \
    --python-version 312 \
    --implementation cp \
    --abi cp312 \
    --no-deps \
    --dest "$wheelhouse" \
    "${pypi_packages[@]}"

python -m pip download \
    "${proxy_args[@]}" \
    --disable-pip-version-check \
    --only-binary=:all: \
    --platform win_amd64 \
    --python-version 312 \
    --implementation cp \
    --abi cp312 \
    --no-deps \
    --index-url https://download.pytorch.org/whl/cu128 \
    --dest "$wheelhouse" \
    torch==2.11.0+cu128 torchaudio==2.11.0+cu128

llama_wheel="$wheelhouse/llama_cpp_python-0.3.33-py3-none-win_amd64.whl"
llama_sha256="e5b16dffdef2b0722ea7e66bab5af76f111a37ff5ec7a7f4909acb584c7ceb54"
if [[ ! -f "$llama_wheel" ]]; then
    curl --fail --location --retry 3 \
        "${curl_proxy_args[@]}" \
        --output "$llama_wheel.part" \
        https://github.com/abetlen/llama-cpp-python/releases/download/v0.3.33-cu125/llama_cpp_python-0.3.33-py3-none-win_amd64.whl
    mv "$llama_wheel.part" "$llama_wheel"
fi
printf '%s  %s\n' "$llama_sha256" "$llama_wheel" | sha256sum --check -

printf 'Windows runtime wheelhouse populated at %s\n' "$wheelhouse"
