#!/usr/bin/env python3
"""Lightweight subprocess probe for the GUI's CUDA status panel."""
from __future__ import annotations

import json


def probe_devices() -> dict[str, object]:
    result: dict[str, object] = {
        "torch_cuda": False,
        "onnx_cuda": False,
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

    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
        result["onnx_cuda"] = "CUDAExecutionProvider" in providers
        details.append(f"ONNX Runtime providers: {', '.join(providers)}")
    except Exception as exc:  # pragma: no cover - depends on packaged runtime
        details.append(f"ONNX Runtime: {type(exc).__name__}: {exc}")

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
