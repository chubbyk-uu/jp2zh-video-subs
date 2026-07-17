"""Runtime paths shared by source checkouts and Windows portable folders."""
from __future__ import annotations

import os
import sys
import ctypes
import tempfile
from pathlib import Path


PORTABLE_ROOT_ENV = "JP2ZH_PORTABLE_ROOT"


def project_root(anchor: Path | None = None) -> Path:
    """Return the portable root when launched from a bundle, else the source root."""
    configured = os.environ.get(PORTABLE_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    source = (anchor or Path(__file__)).resolve()
    directory = source if source.is_dir() else source.parent
    for candidate in (directory, *directory.parents):
        if candidate.name == "scripts":
            if candidate.parent.name == "app" and (candidate.parent.parent / "runtime").is_dir():
                return candidate.parent.parent
            return candidate.parent
    return directory


def app_root(anchor: Path | None = None) -> Path:
    """Return the directory containing bundled/source application scripts."""
    root = project_root(anchor)
    bundled = root / "app"
    return bundled if bundled.is_dir() else root


def scripts_dir(anchor: Path | None = None) -> Path:
    return app_root(anchor) / "scripts"


def portable_config_path(anchor: Path | None = None) -> Path | None:
    """Return the portable INI path, or None for normal platform settings."""
    if not os.environ.get(PORTABLE_ROOT_ENV, "").strip():
        return None
    return project_root(anchor) / "config" / "gui.ini"


def single_instance_lock_path(anchor: Path | None = None) -> Path:
    """Return a per-bundle lock path, or a per-user temporary path for source runs."""
    config_path = portable_config_path(anchor)
    if config_path is not None:
        return config_path.with_name("jp2zh-video-subs.lock")
    return Path(tempfile.gettempdir()) / "jp2zh-video-subs-gui.lock"


def rebase_portable_path(path: str | Path, previous_root: str | Path, current_root: str | Path) -> Path:
    """Move a saved path with its portable root while leaving external paths unchanged."""
    saved = Path(path)
    try:
        relative = saved.relative_to(Path(previous_root))
    except ValueError:
        return saved
    return Path(current_root) / relative


def prepare_windows_dll_search(anchor: Path | None = None) -> None:
    """Expose bundled CUDA/runtime DLLs before native extensions are imported."""
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return
    root = project_root(anchor)
    candidates = (
        root / "runtime",
        root / "runtime" / "Lib" / "site-packages" / "torch" / "lib",
    )
    handles = getattr(prepare_windows_dll_search, "_handles", [])
    for path in candidates:
        if path.is_dir():
            handles.append(os.add_dll_directory(str(path)))
    prepare_windows_dll_search._handles = handles


def prepare_llama_cuda_dependencies(anchor: Path | None = None) -> None:
    """Preload bundled CUDA libraries in dependency order for llama.cpp."""
    prepare_windows_dll_search(anchor)
    if sys.platform != "win32":
        return
    torch_lib = project_root(anchor) / "runtime" / "Lib" / "site-packages" / "torch" / "lib"
    handles = getattr(prepare_llama_cuda_dependencies, "_handles", [])
    for name in ("cudart64_12.dll", "cublasLt64_12.dll", "cublas64_12.dll"):
        path = torch_lib / name
        if path.is_file():
            handles.append(ctypes.WinDLL(str(path)))
    prepare_llama_cuda_dependencies._handles = handles


def prepare_onnx_cuda_dependencies(anchor: Path | None = None) -> None:
    """Preload the bundled PyTorch CUDA/cuDNN libraries for ONNX Runtime."""
    prepare_windows_dll_search(anchor)
    if sys.platform != "win32":
        return
    try:
        import torch  # noqa: F401 - import intentionally preloads native DLLs
    except ImportError:
        return
