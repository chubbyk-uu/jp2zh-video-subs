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

from portable_runtime import prepare_onnx_cuda_dependencies, project_root

prepare_onnx_cuda_dependencies(Path(__file__))

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
DEFAULT_MODEL_PATH = project_root(Path(__file__)) / "models" / "whisperseg" / _ONNX_FILENAME


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
    # Why this speech segment ended before padding. This is diagnostic metadata:
    # the timing state machine and its output spans remain unchanged.
    end_reason: str = "unknown"


class SpeechGroup(list[SpeechSegment]):
    """A WhisperSeg frame with the cause of its outer timeline boundaries.

    It intentionally subclasses ``list`` so existing framing consumers keep using
    ``group[0]``, ``group[-1]``, and iteration unchanged. Bare lists returned by
    test doubles or third-party callers remain supported by consumers.
    """

    def __init__(
        self,
        segments: List[SpeechSegment] = (),
        *,
        left_boundary_reason: str = "audio_start",
        right_boundary_reason: str = "audio_end",
    ) -> None:
        super().__init__(segments)
        self.left_boundary_reason = left_boundary_reason
        self.right_boundary_reason = right_boundary_reason


def group_segments(
    segments: List[SpeechSegment],
    max_group_duration_s: float = 8.0,
    chunk_threshold_s: float = 1.0,
) -> List[SpeechGroup]:
    """Group speech segments by silence gap and max group duration.

    Starts a new group when the gap to the previous segment exceeds
    chunk_threshold_s OR adding the segment would exceed max_group_duration_s.
    """
    if not segments:
        return []
    groups: List[SpeechGroup] = [SpeechGroup()]
    for i, seg in enumerate(segments):
        if i > 0:
            gap = seg.start - segments[i - 1].end
            would_exceed = bool(groups[-1]) and (seg.end - groups[-1][0].start) > max_group_duration_s
            if gap > chunk_threshold_s or would_exceed:
                # A segment-level max split is stronger evidence than the later
                # group cap: this exact boundary arose while speech was ongoing.
                if segments[i - 1].end_reason in {
                    "forced_max_speech",
                    "soft_max_valley",
                    "hard_max_valley",
                    "hard_max_speech",
                } and gap <= chunk_threshold_s:
                    reason = segments[i - 1].end_reason
                elif gap > chunk_threshold_s:
                    reason = "silence_gap"
                else:
                    reason = "forced_max_group"
                groups[-1].right_boundary_reason = reason
                groups.append(SpeechGroup(left_boundary_reason=reason))
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
        hard_max_speech_duration_s: Optional[float] = None,
        soft_split_lookback_s: float = 1.0,
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
        # ``None`` deliberately means the legacy immediate force-cut behaviour.
        # Callers that opt into the soft/hard splitter pass an explicit value.
        self.hard_max_speech_duration_s = (
            float(hard_max_speech_duration_s)
            if hard_max_speech_duration_s is not None
            else self.max_speech_duration_s
        )
        self.soft_split_lookback_s = max(0.0, float(soft_split_lookback_s))
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
            f"hard_max_speech={self.hard_max_speech_duration_s}s "
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

    def _natural_speeches(
        self,
        probs: np.ndarray,
        *,
        min_speech: int,
        min_sil: int,
        max_speech: Optional[int],
    ) -> List[dict]:
        """Return unpadded hysteresis segments, optionally using the legacy hard cut."""
        thr = self.threshold
        neg = max(thr - 0.15, 0.01)
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
            if max_speech is not None and triggered and "start" in cur and (i - cur["start"]) > max_speech:
                cur["end"] = cur["start"] + max_speech
                cur["end_reason"] = "forced_max_speech"
                speeches.append(cur)
                cur, triggered, temp_end = {}, False, 0
                continue
            if prob < neg and triggered:
                if not temp_end:
                    temp_end = i
                if i - temp_end >= min_sil:
                    cur["end"] = temp_end
                    if cur["end"] - cur["start"] >= min_speech:
                        cur["end_reason"] = "silence"
                        speeches.append(cur)
                    cur, triggered, temp_end = {}, False, 0
            elif prob >= thr and temp_end:
                temp_end = 0
        if triggered and "start" in cur:
            cur["end"] = len(probs)
            if cur["end"] - cur["start"] >= min_speech:
                cur["end_reason"] = "audio_end"
                speeches.append(cur)
        return speeches

    @staticmethod
    def _smoothed_probs(probs: np.ndarray, radius: int = 2) -> np.ndarray:
        """A short moving average makes one-frame ONNX fluctuations non-decisive."""
        if radius <= 0 or len(probs) < 3:
            return probs.astype(np.float32, copy=False)
        kernel = np.full(radius * 2 + 1, 1.0 / (radius * 2 + 1), dtype=np.float32)
        return np.convolve(np.pad(probs, (radius, radius), mode="edge"), kernel, mode="valid")

    def _choose_soft_split(
        self,
        smooth: np.ndarray,
        start: int,
        end: int,
        soft: int,
        hard: int,
        min_speech: int,
    ) -> tuple[int, str]:
        """Choose one probability valley in ``[soft-lookback, hard]``.

        A qualified valley is allowed to win near the soft target. If no such valley
        exists, the lowest relative point in the same bounded window is still used,
        keeping the ASR job below the hard cap without adding an audio/RMS subsystem.
        """
        target = start + soft
        lo = max(start + min_speech, target - int(self.soft_split_lookback_s * 1000 / _FRAME_MS))
        hi = min(start + hard, end - min_speech)
        if hi < lo:
            # A terminal sub-second tail is legal but undesirable. The normal path
            # below penalizes it; this is only a last-resort hard cap.
            hi = min(start + hard, end - 1)
            lo = min(lo, hi)
        candidates = np.arange(lo, hi + 1, dtype=int)
        if len(candidates) == 0:
            return min(start + hard, end - 1), "hard_max_speech"

        values = smooth[candidates]
        prominence = np.empty(len(candidates), dtype=np.float32)
        widths = np.empty(len(candidates), dtype=np.float32)
        for idx, cut in enumerate(candidates):
            left = max(start, cut - 10)
            right = min(end, cut + 10)
            local = smooth[left : right + 1]
            prominence[idx] = float(np.mean(local) - smooth[cut])
            # Count nearby low-probability frames; a sustained valley is preferred
            # over a single noisy frame with the same depth.
            widths[idx] = float(np.count_nonzero(local <= smooth[cut] + 0.03))

        distance = np.abs(candidates - target) / max(1, hard - soft)
        tail = end - candidates
        tail_penalty = np.where(tail < int(1000 / _FRAME_MS), 0.08, 0.0)
        qualified = (values <= self.threshold + 0.05) & (prominence >= 0.02)
        if np.any(qualified):
            score = (1.0 - values) + 0.8 * prominence + 0.015 * widths - 0.12 * distance - tail_penalty
            masked = np.where(qualified, score, -np.inf)
            return int(candidates[int(np.argmax(masked))]), "soft_max_valley"

        # No real pause: retain a bounded deterministic fallback. Depth dominates,
        # while target distance resolves flat-probability ties at the soft target.
        score = (1.0 - values) + 0.35 * prominence + 0.01 * widths - 0.20 * distance - tail_penalty
        return int(candidates[int(np.argmax(score))]), "hard_max_valley"

    def _split_natural_speeches(
        self,
        speeches: List[dict],
        probs: np.ndarray,
        min_speech: int,
    ) -> List[dict]:
        soft = int(self.max_speech_duration_s * 1000.0 / _FRAME_MS)
        hard = int(self.hard_max_speech_duration_s * 1000.0 / _FRAME_MS)
        # Exact legacy path: preserve old spans and reasons for reproducible A/B.
        if hard <= soft or soft <= 0:
            return speeches
        smooth = self._smoothed_probs(probs)
        split: List[dict] = []
        for speech in speeches:
            start, end = int(speech["start"]), int(speech["end"])
            while end - start > hard:
                cut, reason = self._choose_soft_split(smooth, start, end, soft, hard, min_speech)
                if cut <= start or cut >= end:
                    cut = min(start + hard, end - 1)
                    reason = "hard_max_speech"
                split.append({"start": start, "end": cut, "end_reason": reason})
                start = cut
            split.append({"start": start, "end": end, "end_reason": speech["end_reason"]})
        return split

    def _probs_to_segments(self, probs: np.ndarray, audio_dur: float) -> List[SpeechSegment]:
        """Hysteresis VAD with legacy or soft/hard probability-valley splitting."""
        if len(probs) == 0:
            return []
        fm = float(_FRAME_MS)
        min_speech = max(1, int(self.min_speech_duration_ms / fm))
        min_sil = max(1, int(self.min_silence_duration_ms / fm))
        pad = max(0, int(self.speech_pad_ms / fm))
        # Legacy force-splitting happens inside the state machine before a following
        # silence can be observed. The soft/hard mode first finds natural runs, so a
        # real silence at 60.794s is no longer hidden by a prior artificial 5s cut.
        legacy = self.hard_max_speech_duration_s <= self.max_speech_duration_s
        max_speech = int(self.max_speech_duration_s * 1000.0 / fm) if legacy and self.max_speech_duration_s > 0 else None
        speeches = self._natural_speeches(
            probs,
            min_speech=min_speech,
            min_sil=min_sil,
            max_speech=max_speech,
        )
        if not legacy:
            speeches = self._split_natural_speeches(speeches, probs, min_speech)

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
                out.append(SpeechSegment(st, en, str(s.get("end_reason", "unknown"))))
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
