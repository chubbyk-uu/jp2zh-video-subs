"""Fetch inference-only candidate files at pinned Hub revisions into local models/."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MODELS = {
    "jaykwok": ("jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame", "6db0efecd56d4a7e0003190a6bd4cac056d0f390", "qwen-anime-jaykwok"),
    "hf-base": ("Qwen/Qwen3-ASR-1.7B-hf", "bcd2b5b7f32b480ab5790554cfa8347f246a14f3", "qwen-asr-hf-base"),
    "lora": ("hhim8826/qwen3-asr-lora-ja-anime-v3", "8749c32c01be5a202b44a0ff2e45121f933e69b7", "qwen-anime-lora-v3"),
    "translation": ("mmis1000/asmr-qwen3.5-9b-zh-cn-gguf-v0.2", "622bce3091604f86461e8cc95391cb755ea45715", "asmr-qwen35-v02"),
}


def fetch(key: str, root: Path, quantizations: list[str]):
    from huggingface_hub import HfApi, snapshot_download

    repo, revision, directory = MODELS[key]
    api = HfApi()
    info = api.model_info(repo, revision=revision, files_metadata=True)
    names = []
    for item in info.siblings:
        name = item.rfilename
        if key == "translation":
            keep = name == "README.md" or any(name.endswith(f"-{quant}.gguf") for quant in quantizations)
        else:
            keep = name in ("README.md", "merges.txt", "vocab.json", "tokenizer.json", "tokenizer_config.json",
                            "preprocessor_config.json", "processor_config.json", "config.json", "generation_config.json",
                            "chat_template.json", "chat_template.jinja", "added_tokens.json", "special_tokens_map.json", "model.safetensors",
                            "adapter_model.safetensors", "adapter_config.json")
        if keep:
            names.append(name)
    destination = root / directory
    print(f"{key}: {repo}@{revision}; selected {len(names)} inference files", flush=True)
    snapshot_download(repo, revision=revision, allow_patterns=names, local_dir=str(destination), max_workers=4)
    records = {}
    for item in info.siblings:
        if item.rfilename not in names:
            continue
        path = destination / item.rfilename
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lfs = item.lfs
        if lfs and digest != lfs.sha256:
            raise ValueError(f"download digest mismatch: {key}/{item.rfilename}")
        records[item.rfilename] = {"sha256": digest, "bytes": path.stat().st_size}
    (destination / "evaluation-download.json").write_text(json.dumps({"repository": repo, "revision": revision,
                                                                      "files": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{key}: verified", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=tuple(MODELS), default=list(MODELS))
    parser.add_argument("--root", type=Path, default=Path("models/evaluation"))
    parser.add_argument("--quantizations", nargs="+", choices=("q4_k_m", "q6_k", "q8_0"), default=["q4_k_m", "q8_0"])
    args = parser.parse_args()
    for key in args.models:
        fetch(key, args.root, args.quantizations)


if __name__ == "__main__":
    main()
