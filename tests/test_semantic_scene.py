import numpy as np
import pytest

from semantic_scene import _extract_features, detect_scenes


def test_real_feature_blocks_use_audio_offsets_and_trim_short_tail():
    # A non-silent tone also exercises librosa's actual centered STFT framing.
    sr = 16000
    samples = np.arange(2 * sr + 100)
    audio = np.asarray(0.1 * np.sin(2 * np.pi * 440 * samples / sr), dtype=np.float32)
    features, times = _extract_features(audio, sr, chunk_dur=1)
    assert features.shape[1] == len(times)
    assert times[32] == 1.0
    assert times[64] == 2.0
    assert len(times) == 65  # the padded tail contributes only its real frame
    assert np.all(np.diff(times) > 0)
    assert times[-1] < len(audio) / sr


def test_two_hour_timeline_has_no_accumulated_block_drift(monkeypatch):
    import librosa

    # Keep real framing arithmetic but avoid two hours of feature computation.
    def features(rows):
        return lambda *, y, **kwargs: np.zeros((rows, 1 + len(y) // 512))

    for name, rows in (("mfcc", 13), ("rms", 1), ("zero_crossing_rate", 1),
                       ("spectral_contrast", 7), ("chroma_stft", 12)):
        monkeypatch.setattr(librosa.feature, name, features(rows))
    monkeypatch.setattr(librosa.feature, "delta", lambda x: x)
    audio = np.broadcast_to(np.float32(0), (7200 * 16000 + 1,))
    matrix, times = _extract_features(audio, 16000)
    assert matrix.shape[1] == len(times)
    for block in range(121):
        assert times[block * 1875] == block * 60.0
    assert np.all(np.diff(times) > 0)
    assert times[-1] == 7200.0


@pytest.mark.parametrize("samples", [0, 100, 16000])
def test_scene_coverage_handles_empty_and_short_audio(samples):
    audio = np.zeros(samples, dtype=np.float32)
    scenes = detect_scenes(audio)
    assert scenes[0][0] == 0.0
    assert scenes[-1][1] == pytest.approx(samples / 16000, abs=0.001)
    assert all(a[1] == b[0] for a, b in zip(scenes, scenes[1:]))
