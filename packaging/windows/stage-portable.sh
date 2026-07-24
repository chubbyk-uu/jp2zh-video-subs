#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 SOURCE_ROOT LAB_ROOT" >&2
    exit 2
fi

source_root="$(realpath "$1")"
lab_root="$(realpath "$2")"
package_root="$lab_root/package/jp2zh-video-subs"

case "$package_root/" in
    "$lab_root/"*) ;;
    *)
        echo "Refusing to write outside lab root: $package_root" >&2
        exit 3
        ;;
esac

mkdir -p \
    "$lab_root/build" \
    "$lab_root/cache/downloads" \
    "$lab_root/cache/pip" \
    "$lab_root/cache/temp" \
    "$lab_root/logs" \
    "$lab_root/test-data" \
    "$package_root/app" \
    "$package_root/bin" \
    "$package_root/cache/huggingface" \
    "$package_root/cache/numba" \
    "$package_root/cache/temp" \
    "$package_root/cache/torch" \
    "$package_root/config" \
    "$package_root/licenses" \
    "$package_root/models" \
    "$package_root/outputs" \
    "$package_root/runtime" \
    "$package_root/work"

rsync -a --delete \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "$source_root/scripts/" "$package_root/app/scripts/"

for catalog in languages.json jp2zh_zh_CN.qm jp2zh_zh_TW.qm; do
    if [[ ! -f "$package_root/app/scripts/jp2zh_gui/translations/$catalog" ]]; then
        echo "Missing GUI language catalog: $catalog" >&2
        exit 5
    fi
done

install -m 0644 "$source_root/README.md" "$package_root/app/README.md"
install -m 0644 "$source_root/README-CN.md" "$package_root/app/README-CN.md"
install -m 0644 "$source_root/LICENSE" "$package_root/app/LICENSE"
install -m 0644 "$source_root/LICENSE" "$package_root/LICENSE"
install -m 0644 "$source_root/packaging/windows/INSTALL-CN.txt" "$package_root/INSTALL-CN.txt"
install -m 0644 "$source_root/packaging/windows/INSTALL-EN.txt" "$package_root/INSTALL-EN.txt"
install -m 0644 "$source_root/THIRD_PARTY_NOTICES.md" "$package_root/app/THIRD_PARTY_NOTICES.md"
install -m 0644 "$source_root/THIRD_PARTY_NOTICES.md" "$package_root/THIRD_PARTY_NOTICES.md"
install -m 0644 "$source_root/requirements.txt" "$package_root/app/requirements.txt"
install -m 0644 "$source_root/requirements-gui.txt" "$package_root/app/requirements-gui.txt"
install -m 0644 "$source_root/packaging/windows/runtime-versions.txt" "$package_root/config/runtime-versions.txt"
install -m 0644 "$source_root/packaging/windows/runtime-lock.txt" "$package_root/config/runtime-lock.txt"
install -m 0644 "$source_root/packaging/windows/launch.cmd" "$package_root/launch.cmd"
install -m 0644 "$source_root/packaging/windows/launch-debug.cmd" "$package_root/launch-debug.cmd"
install -m 0644 "$source_root/packaging/windows/launch-env.cmd" "$package_root/launch-env.cmd"
"$source_root/packaging/windows/build-launcher.sh" "$source_root" "$package_root"
for legacy_entry in "$package_root/启动字幕工具.cmd" "$package_root/启动字幕工具-调试.cmd"; do
    if [[ -e "$legacy_entry" ]]; then
        unlink "$legacy_entry"
    fi
done

printf 'Portable layout staged at %s\n' "$package_root"
