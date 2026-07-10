"""WhisperSeg speech segmentation (ONNX) — 短而纯的 speech frame。

移植/改编自 WhisperJAV `whisperjav/modules/speech_segmentation/backends/whisperseg.py`
与 `.../backends/ten.py::group_segments` (MIT License, WhisperJAV authors)，其状态机又
改编自 TransWithAI/Whisper-Vad-EncDec-ASMR-onnx/inference.py (MIT)。见 THIRD_PARTY_NOTICES.md。

Whisper-encoder VAD 导出为 ONNX，帧级 20ms 分辨率、30s 窗口、训练于 ~500h 日语 ASMR，
适配 JAV 里常见的气声/弱语音。运行期只依赖 onnxruntime + transformers(仅 feature extractor)。

用途：把长而杂的 Silero clip 换成短而贴合语音的 frame，降低 forced aligner 局部塌缩。
segment(audio, sr) 返回 groups：List[List[SpeechSegment]]，每个 group 是一个 frame。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

_SAMPLE_RATE = 16000
_FRAME_MS = 20
_CHUNK_MS = 30000

# Upstream provenance only — NOT used at runtime. Unlike WhisperJAV (which downloads
# via hf_hub_download(revision=...) so the pin takes effect at load time), this backend
# loads model.onnx from the local models/ dir and does not download or verify a hash.
# The revision pin is therefore enforced by the README download command
# (`hf download ... --revision 6ac29e2c...`), which fetches the exact commit the code
# was validated against and prevents silent upstream model.onnx changes.
_HF_REPO = "TransWithAI/Whisper-Vad-EncDec-ASMR-onnx"
_HF_REVISION = "6ac29e2cbf2f4f8e9b639861766a8639dd666e9c"
_ONNX_FILENAME = "model.onnx"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "whisperseg" / _ONNX_FILENAME


def resolve_model_path(explicit: str = "") -> str:
    """Return a local ONNX path without downloading.

    By default WhisperSeg is loaded from models/whisperseg/model.onnx, matching the
    repository's other local model assets. A user may pass an explicit file path.
    """
    candidate = Path(explicit).expanduser() if explicit else DEFAULT_MODEL_PATH
    if candidate.exists():
        return str(candidate)
    raise SystemExit(
        f"WhisperSeg ONNX model not found: {candidate}. "
        "Place model.onnx under models/whisperseg/ or pass --whisperseg-model."
    )


@dataclass
class SpeechSegment:
    start: float  # seconds
    end: float


def group_segments(
    segments: List[SpeechSegment],
    max_group_duration_s: float = 8.0,
    chunk_threshold_s: float = 1.0,
) -> List[List[SpeechSegment]]:
    """Group speech segments by silence gap and max group duration.

    Starts a new group when the gap to the previous segment exceeds
    chunk_threshold_s OR adding the segment would exceed max_group_duration_s.
    """
    if not segments:
        return []
    groups: List[List[SpeechSegment]] = [[]]
    for i, seg in enumerate(segments):
        if i > 0:
            gap = seg.start - segments[i - 1].end
            would_exceed = bool(groups[-1]) and (seg.end - groups[-1][0].start) > max_group_duration_s
            if gap > chunk_threshold_s or would_exceed:
                groups.append([])
        groups[-1].append(seg)
    return [g for g in groups if g]


class WhisperSegVAD:
    """ONNX WhisperSeg segmenter with a Silero-compatible state machine."""

    def __init__(
        self,
        model_path: str,
        threshold: float = 0.35,
        min_speech_duration_ms: int = 100,
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 300,
        max_speech_duration_s: Optional[float] = 5.0,
        max_group_duration_s: float = 8.0,
        chunk_threshold_s: float = 1.0,
        force_cpu: bool = False,
    ):
        self.model_path = model_path
        self.threshold = float(threshold)
        self.min_speech_duration_ms = int(min_speech_duration_ms)
        self.min_silence_duration_ms = int(min_silence_duration_ms)
        self.speech_pad_ms = int(speech_pad_ms)
        self.max_group_duration_s = float(max_group_duration_s)
        self.chunk_threshold_s = float(chunk_threshold_s)
        self.max_speech_duration_s = (
            float(max_speech_duration_s) if max_speech_duration_s is not None else float(max_group_duration_s)
        )
        self.force_cpu = bool(force_cpu)
        self.actual_device = "unloaded"
        self.requested_providers: list[str] = []
        self.providers: list[str] = []
        self._session = None
        self._fe = None
        self._input = None
        self._outputs = None
        self._chunk_samples = int(_CHUNK_MS * _SAMPLE_RATE / 1000)

    def _ensure_model(self) -> None:
        if self._session is not None:
            return
        import onnxruntime as ort
        from transformers import WhisperFeatureExtractor

        if not os.path.exists(self.model_path):
            raise SystemExit(f"WhisperSeg onnx not found: {self.model_path}")
        available_providers = list(ort.get_available_providers())
        if "CUDAExecutionProvider" in available_providers and not self.force_cpu:
            requested_providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            requested_providers = ["CPUExecutionProvider"]
        self.requested_providers = list(requested_providers)
        self._session = ort.InferenceSession(self.model_path, providers=requested_providers)
        self.providers = list(self._session.get_providers())
        if self.providers and self.providers[0] == "CUDAExecutionProvider":
            self.actual_device = "GPU (CUDAExecutionProvider)"
        else:
            self.actual_device = "CPU"
            if "CUDAExecutionProvider" in self.requested_providers:
                print(
                    "Warning: WhisperSeg requested CUDAExecutionProvider but the ONNX "
                    f"session activated {self.providers}; using CPU.",
                    flush=True,
                )
        self._input = self._session.get_inputs()[0].name
        self._outputs = [o.name for o in self._session.get_outputs()]
        # WhisperSeg was trained/exported against Whisper-base features. Construct
        # the extractor locally so --vad-backend whisperseg does not depend on a
        # Hugging Face cache or network access at runtime.
        self._fe = WhisperFeatureExtractor()
        print(
            "WhisperSeg ready: "
            f"device={self.actual_device} requested_providers={self.requested_providers} "
            f"active_providers={self.providers} "
            f"threshold={self.threshold} max_speech={self.max_speech_duration_s}s "
            f"max_group={self.max_group_duration_s}s",
            flush=True,
        )

    def _forward(self, audio: np.ndarray) -> np.ndarray:
        """Full audio -> per-frame speech probabilities (sequential 30s chunks)."""
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        probs: List[np.ndarray] = []
        for i in range(0, len(audio), self._chunk_samples):
            chunk = audio[i : i + self._chunk_samples]
            if len(chunk) < self._chunk_samples:
                chunk = np.pad(chunk, (0, self._chunk_samples - len(chunk)))
            feats = self._fe(chunk, sampling_rate=_SAMPLE_RATE, return_tensors="np").input_features
            logits = self._session.run(self._outputs, {self._input: feats})[0][0]
            probs.append(1.0 / (1.0 + np.exp(-logits)))
        return np.concatenate(probs) if probs else np.zeros(0, dtype=np.float32)

    def _probs_to_segments(self, probs: np.ndarray, audio_dur: float) -> List[SpeechSegment]:
        """State machine with dual-threshold hysteresis, min-duration filtering,
        max-duration force-split and overlap-prevented padding."""
        if len(probs) == 0:
            return []
        fm = float(_FRAME_MS)
        thr = self.threshold
        neg = max(thr - 0.15, 0.01)
        min_speech = max(1, int(self.min_speech_duration_ms / fm))
        min_sil = max(1, int(self.min_silence_duration_ms / fm))
        pad = max(0, int(self.speech_pad_ms / fm))
        max_speech = int(self.max_speech_duration_s * 1000.0 / fm) if self.max_speech_duration_s > 0 else len(probs)

        triggered = False
        speeches: List[dict] = []
        cur: dict = {}
        temp_end = 0
        for i, p in enumerate(probs):
            prob = float(p)
            if prob >= thr and not triggered:
                triggered = True
                cur = {"start": i}
                continue
            if triggered and "start" in cur and (i - cur["start"]) > max_speech:
                cur["end"] = cur["start"] + max_speech
                speeches.append(cur)
                cur, triggered, temp_end = {}, False, 0
                continue
            if prob < neg and triggered:
                if not temp_end:
                    temp_end = i
                if i - temp_end >= min_sil:
                    cur["end"] = temp_end
                    if cur["end"] - cur["start"] >= min_speech:
                        speeches.append(cur)
                    cur, triggered, temp_end = {}, False, 0
            elif prob >= thr and temp_end:
                temp_end = 0
        if triggered and "start" in cur:
            cur["end"] = len(probs)
            if cur["end"] - cur["start"] >= min_speech:
                speeches.append(cur)

        for idx, s in enumerate(speeches):  # overlap-prevented padding
            s["start"] = max(speeches[idx - 1]["end"], s["start"] - pad) if idx else max(0, s["start"] - pad)
            if idx < len(speeches) - 1:
                s["end"] = min(speeches[idx + 1]["start"], s["end"] + pad)
            else:
                s["end"] = min(len(probs), s["end"] + pad)

        out: List[SpeechSegment] = []
        for s in speeches:
            st = s["start"] * fm / 1000.0
            en = min(s["end"] * fm / 1000.0, audio_dur)
            if en > st:
                out.append(SpeechSegment(st, en))
        return out

    def segment(self, audio: np.ndarray, sample_rate: int = _SAMPLE_RATE) -> List[List[SpeechSegment]]:
        """Return grouped speech frames for the given mono 16kHz audio."""
        if sample_rate != _SAMPLE_RATE:
            raise SystemExit("WhisperSeg requires 16 kHz audio")
        self._ensure_model()
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        dur = len(audio) / _SAMPLE_RATE
        probs = self._forward(audio)
        segs = self._probs_to_segments(probs, dur)
        return group_segments(segs, self.max_group_duration_s, self.chunk_threshold_s)

    def cleanup(self) -> None:
        self._session = None
        self._fe = None
