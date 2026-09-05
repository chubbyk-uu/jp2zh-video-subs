"""Semantic scene detection — 声学纹理边界的全覆盖 scene 切分。

移植/改编自 WhisperJAV `whisperjav/vendor/semantic_audio_clustering.py`
(StreamFeatureExtractor + SemanticSegmenter, MIT License, WhisperJAV authors)。
见 THIRD_PARTY_NOTICES.md。

只保留边界所需部分：36维特征(MFCC/delta/RMS/ZCR/spectral contrast/chroma) →
median 平滑 + 下采样 → StandardScaler + Agglomerative 聚类 → 边界 snap 到局部 RMS
最低(静音) → 按余弦相似度 smart_merge 短段 → forced cleanup → 全覆盖(无时间线缺口)。
scene type / classify / 可视化不移植(anime 不吃 asr_prompt,只用边界)。

detect_scenes(audio, sr, ...) -> List[(start, end)]，全覆盖、无缺口、无重叠。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

import numpy as np

_SR = 16000
_HOP = 512
_N_MFCC = 13
_FPS = 31
_RMS_IDX = 26  # 特征行顺序: mfcc0:13, delta13:26, rms26, zcr27, contrast28:35, chroma_std35


def _extract_features(audio: np.ndarray, sr: int, chunk_dur: int = 60) -> Tuple[np.ndarray, np.ndarray]:
    """分块(默认60s)提取 36 维声学特征,拼成 (36, frames) 与 frame 时间戳。"""
    os.environ.setdefault("NUMBA_CACHE_DIR", str(Path("/tmp") / "numba_cache"))
    import librosa

    block = int(chunk_dur * sr)
    min_samples = _HOP * 10
    feats: List[np.ndarray] = []
    timestamps: List[np.ndarray] = []
    for i in range(0, len(audio), block):
        y = audio[i : i + block]
        real_samples = len(y)
        if len(y) < min_samples:
            y = np.pad(y, (0, min_samples - len(y)), mode="constant")
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=_N_MFCC)
        delta = librosa.feature.delta(mfcc)
        rms = librosa.feature.rms(y=y)
        zcr = librosa.feature.zero_crossing_rate(y=y)
        contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_std = np.std(chroma, axis=0, keepdims=True)
        features = np.vstack([mfcc, delta, rms, zcr, contrast, chroma_std])
        # Each centered STFT includes its block's endpoint. Do not count that
        # endpoint twice or treat short-tail padding as real audio. Build times
        # from the actual block offset, never the concatenated frame count.
        sample_offsets = np.arange(features.shape[1]) * _HOP
        valid = sample_offsets < real_samples
        feats.append(features[:, valid])
        timestamps.append((i + sample_offsets[valid]) / sr)
    if not feats:
        return np.empty((36, 0)), np.empty(0)
    full = np.hstack(feats)
    times = np.concatenate(timestamps)
    return full, times


def _snap_to_silence(boundaries, features, times, snap_window, rms_smoothing_window):
    """把每个内部边界滑到 ±snap_window 内 RMS 最低处(静音),避免切断语音。"""
    from scipy.ndimage import median_filter

    rms_smooth = median_filter(features[_RMS_IDX, :], size=rms_smoothing_window)
    refined = [0.0]
    for b in boundaries[1:-1]:
        lo = max(0, int(np.searchsorted(times, b - snap_window)))
        hi = min(len(rms_smooth), int(np.searchsorted(times, b + snap_window)))
        if hi > lo:
            refined.append(times[np.argmin(rms_smooth[lo:hi]) + lo])
        else:
            refined.append(b)
    refined.append(boundaries[-1])
    return sorted(set(refined))


def _smart_merge(boundaries, features, times, min_dur, max_dur):
    """把 <min_dur 的段按余弦相似度并入更像的邻居(不超过 max_dur)。"""
    from sklearn.metrics.pairwise import cosine_similarity

    segs = []
    for i in range(len(boundaries) - 1):
        s, e = boundaries[i], boundaries[i + 1]
        mask = (times >= s) & (times < e)
        if not np.any(mask):
            continue
        segs.append({"start": s, "end": e, "vec": np.mean(features[:, mask], axis=1), "dur": e - s})

    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(segs):
            seg = segs[i]
            if seg["dur"] >= min_dur:
                i += 1
                continue
            left = segs[i - 1] if i > 0 else None
            right = segs[i + 1] if i < len(segs) - 1 else None
            target = None
            if left and right:
                sl = cosine_similarity([seg["vec"]], [left["vec"]])[0][0]
                sr_ = cosine_similarity([seg["vec"]], [right["vec"]])[0][0]
                order = (-1, 1) if sl >= sr_ else (1, -1)
                for cand in order:
                    nb = left if cand == -1 else right
                    if nb["dur"] + seg["dur"] <= max_dur:
                        target = cand
                        break
            elif left and left["dur"] + seg["dur"] <= max_dur:
                target = -1
            elif right and right["dur"] + seg["dur"] <= max_dur:
                target = 1

            if target == -1:
                nd = left["dur"] + seg["dur"]
                nv = (left["vec"] * left["dur"] + seg["vec"] * seg["dur"]) / nd
                segs[i - 1] = {"start": left["start"], "end": seg["end"], "dur": nd, "vec": nv}
                del segs[i]
                changed = True
            elif target == 1:
                nd = right["dur"] + seg["dur"]
                nv = (right["vec"] * right["dur"] + seg["vec"] * seg["dur"]) / nd
                segs[i + 1] = {"start": seg["start"], "end": right["end"], "dur": nd, "vec": nv}
                del segs[i]
                changed = True
            else:
                i += 1
    return segs


def _forced_cleanup(segs, min_dur):
    """再兜一遍:仍 <min_dur 的段强制并入邻居。"""
    if not segs:
        return []
    out = []
    cur = segs[0]
    for nxt in segs[1:]:
        if cur["dur"] < min_dur:
            td = cur["dur"] + nxt["dur"]
            cur = {"start": cur["start"], "end": nxt["end"], "dur": td,
                   "vec": (cur["vec"] * cur["dur"] + nxt["vec"] * nxt["dur"]) / td}
        else:
            out.append(cur)
            cur = nxt
    if cur["dur"] < min_dur and out:
        last = out.pop()
        cur = {"start": last["start"], "end": cur["end"], "dur": last["dur"] + cur["dur"], "vec": last["vec"]}
    out.append(cur)
    return out


def _ensure_coverage(segs, duration):
    """填补首尾/中间缺口,保证全覆盖、无重叠。"""
    if not segs:
        return [{"start": 0.0, "end": duration}]
    covered = []
    if segs[0]["start"] > 1e-3:
        covered.append({"start": 0.0, "end": segs[0]["start"]})
    covered.append(segs[0])
    for curr in segs[1:]:
        prev = covered[-1]
        if curr["start"] - prev["end"] > 1e-3:
            covered.append({"start": prev["end"], "end": curr["start"]})
        if curr["start"] < prev["end"]:
            curr = {**curr, "start": prev["end"]}
        covered.append(curr)
    last = covered[-1]
    if last["end"] < duration - 1e-3:
        covered.append({"start": last["end"], "end": duration})
    elif last["end"] > duration:
        last["end"] = duration
    return covered


def detect_scenes(
    audio: np.ndarray,
    sr: int = _SR,
    min_dur: float = 20.0,
    max_dur: float = 48.0,
    clustering_threshold: float = 18.0,
    snap_window: float = 5.0,
    smoothing_window: int = 15,
    rms_smoothing_window: int = 5,
) -> List[Tuple[float, float]]:
    """Return full-coverage semantic scenes [(start, end), ...] (no gaps/overlaps)."""
    from scipy.ndimage import median_filter
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.preprocessing import StandardScaler

    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    duration = len(audio) / sr
    features, times = _extract_features(audio, sr)

    fs = median_filter(features, size=(1, smoothing_window))
    step = max(1, int(_FPS * 0.5))
    X = fs[:, ::step].T
    xt = times[::step]
    if len(X) < 2:
        return [(0.0, round(duration, 3))]
    xs = StandardScaler().fit_transform(X)
    labels = AgglomerativeClustering(
        n_clusters=None, distance_threshold=clustering_threshold, linkage="ward"
    ).fit_predict(xs)

    boundaries = [0.0]
    for i in range(1, len(labels)):
        if labels[i] != labels[i - 1]:
            boundaries.append(xt[i])
    boundaries.append(duration)

    boundaries = _snap_to_silence(boundaries, features, times, snap_window, rms_smoothing_window)
    segs = _smart_merge(boundaries, features, times, min_dur, max_dur)
    segs = _forced_cleanup(segs, min_dur)
    segs = _ensure_coverage(segs, duration)
    return [(round(s["start"], 3), round(s["end"], 3)) for s in segs]
