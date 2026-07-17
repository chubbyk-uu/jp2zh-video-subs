#!/usr/bin/env python3
"""Lightweight subprocess probe for the GUI's CUDA status panel."""
from __future__ import annotations

import json
from pathlib import Path

from portable_runtime import prepare_llama_cuda_dependencies, prepare_onnx_cuda_dependencies, project_root


def probe_onnx_device(model: Path) -> tuple[bool, str, str]:
    if not model.is_file():
        return False, "missing_model", f"WhisperSeg model missing: {model}"
    try:
        prepare_onnx_cuda_dependencies()
        import onnxruntime as ort

        providers = ort.get_available_providers()
        actual_providers: list[str] = []
        if "CUDAExecutionProvider" in providers:
            session = ort.InferenceSession(
                str(model),
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            actual_providers = list(session.get_providers())
        onnx_cuda = bool(actual_providers and actual_providers[0] == "CUDAExecutionProvider")
        status = "cuda" if onnx_cuda else "cpu"
        detail = (
            f"ONNX Runtime providers: {', '.join(providers)}; "
            f"WhisperSeg session: {', '.join(actual_providers) if actual_providers else 'CUDA unavailable'}"
        )
        return onnx_cuda, status, detail
    except Exception as exc:  # pragma: no cover - depends on packaged runtime
        return False, "unavailable", f"ONNX Runtime: {type(exc).__name__}: {exc}"


def probe_devices() -> dict[str, object]:
    prepare_llama_cuda_dependencies()
    result: dict[str, object] = {
        "torch_cuda": False,
        "onnx_cuda": False,
        "onnx_status": "unavailable",
        "llama_cuda": False,
        "gpu_name": "",
    }
    details: list[str] = []

    try:
        import torch

        result["torch_cuda"] = torch.cuda.is_available()
        if result["torch_cuda"]:
            result["gpu_name"] = torch.cuda.get_device_name(0)
        details.append(f"PyTorch CUDA: {result['torch_cuda']}")
    except Exception as exc:  # pragma: no cover - depends on packaged runtime
        details.append(f"PyTorch: {type(exc).__name__}: {exc}")

    onnx_cuda, onnx_status, onnx_detail = probe_onnx_device(
        project_root() / "models" / "whisperseg" / "model.onnx"
    )
    result["onnx_cuda"] = onnx_cuda
    result["onnx_status"] = onnx_status
    details.append(onnx_detail)

    try:
        from llama_cpp import llama_cpp

        supports_gpu = getattr(llama_cpp, "llama_supports_gpu_offload", None)
        result["llama_cuda"] = bool(supports_gpu and supports_gpu())
        details.append(f"llama.cpp GPU offload: {result['llama_cuda']}")
    except Exception as exc:  # pragma: no cover - depends on packaged runtime
        details.append(f"llama.cpp: {type(exc).__name__}: {exc}")

    result["details"] = "\n".join(details)
    return result


if __name__ == "__main__":
    print(json.dumps(probe_devices(), ensure_ascii=False))
