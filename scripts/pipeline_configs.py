"""Stage config dataclasses — the single source of truth for sub-script tuning knobs.

Deliberately lightweight: only stdlib + cli_config, no torch/llama/qwen imports, so the
orchestrator and tests can import these without pulling the GPU/model stack. Each sub-script
builds its parser from its config here; the orchestrator serializes the same config back to
flags. Defaults below are the sub-script's canonical defaults — keep them here only.
"""
from __future__ import annotations

from dataclasses import dataclass

from cli_config import arg_field


@dataclass
class QwenAsrConfig:
    """Tunable knobs forwarded to transcribe_ja_srt_qwen.py.

    IO/positional args (audio, output, --model, --forced-aligner, --meta-output,
    --raw-output, --from-raw) are not here: they are not pipeline tuning knobs and the
    sub-script/orchestrator handle them explicitly.
    """

    language: str = arg_field("Japanese", help="ASR language label")
    batch_size: int = arg_field(24, help="Inference batch size")
    device: str = arg_field("cuda:0", help="Torch device")
    dtype: str = arg_field("bfloat16", choices=("bfloat16", "float16", "float32"), help="Model dtype")
    max_new_tokens: int = arg_field(256, help="Max new tokens per clip")
    chunk_seconds: float = arg_field(30.0, help="ASR window length")
    chunk_overlap_seconds: float = arg_field(3.0, help="ASR window overlap")
    context: str = arg_field("", help="Extra ASR hotwords/context appended to the built-in list")
    no_default_context: bool = arg_field(False, action="store_true", help="Drop the built-in ASR context")

    # VAD clip construction (used when vad_chunks is on).
    vad_chunks: bool = arg_field(False, action="boolean_optional", help="Cut clips on silence (VAD)")
    vad_threshold: float = arg_field(0.1, help="VAD speech probability threshold")
    vad_window_seconds: float = arg_field(8.0, help="VAD sliding window length")
    vad_window_overlap_seconds: float = arg_field(4.0, help="VAD sliding window overlap")
    vad_min_silence_ms: int = arg_field(500, help="VAD min silence to split")
    vad_speech_pad_ms: int = arg_field(200, help="VAD speech padding")
    vad_max_cluster_gap: float = arg_field(2.0, help="Merge speech clusters within this gap")
    vad_pad_seconds: float = arg_field(0.2, help="Pad added around each cluster")
    vad_min_clip_seconds: float = arg_field(0.3, help="Drop clips shorter than this")
    vad_pre_context_seconds: float = arg_field(0.0, help="Audio pre-context fed to ASR")
    vad_post_context_seconds: float = arg_field(0.5, help="Audio post-context fed to ASR")
    vad_max_leading_silence: float = arg_field(0.5, help="Cap on total leading expansion")
    vad_context_merge_gap: float = arg_field(0.0, help="Second-level cluster merge gap (0 off)")
    vad_target_context_seconds: float = arg_field(24.0, help="Target length of a context group")

    # Sentence/cue shaping.
    phrase_max_chars: int = arg_field(26, help="Max content chars per cue")
    phrase_max_duration: float = arg_field(8.0, help="Max cue duration")
    phrase_max_internal_gap: float = arg_field(2.0, help="Split a cue on internal gaps over this")
    phrase_max_char_seconds: float = arg_field(0.5, help="Per-char duration cap for the aligner")
    min_duration: float = arg_field(0.8, help="Floor a cue to this duration")
    min_cue_seconds: float = arg_field(0.2, help="Drop cues shorter than this after shaping")

    # Filler/interjection handling.
    isolated_interjection_silence: float = arg_field(3.0, help="Silence on both sides to drop a lone filler (0 off)")
    isolated_interjection_run: int = arg_field(3, help="Drop a chain of this many consecutive fillers (0 off)")
    isolated_interjection_run_gap: float = arg_field(5.0, help="Max gap within a filler chain")
    interjection_reply_anchor_lag: float = arg_field(3.0, help="Keep はい anchored within this lag (0 off)")
    collapse_filler_repetition: bool = arg_field(True, action="boolean_optional", help="Collapse repeated filler runs inside a cue")

    # Recapture pass (second, more sensitive look inside gaps).
    recapture_min_gap: float = arg_field(0.0, help="Min uncovered gap to recapture (0 disables)")
    recapture_min_speech: float = arg_field(2.0, help="Min detected speech in a gap to re-transcribe")
    recapture_vad_threshold: float = arg_field(0.05, help="More sensitive VAD threshold for recapture")

    # Opt-in Whisper-style hallucination/near-duplicate filtering.
    near_dup_max_gap: float = arg_field(0.25, help="Near-duplicate max gap")
    near_dup_similarity: float = arg_field(0.90, help="Near-duplicate similarity threshold")
    near_dup_squeeze_seconds: float = arg_field(0.5, help="Near-duplicate squeeze window")
    main_min_chars: int = arg_field(1, help="Min chars to keep a cue")
    main_max_compression_ratio: float = arg_field(25.0, help="Max compression ratio")
    main_duplicate_window_seconds: float = arg_field(8.0, help="Duplicate detection window")
    hallucination_min_repeats: int = arg_field(3, help="Min repeats to flag a hallucination")
    hallucination_repeat_no_speech_prob: float = arg_field(0.75, help="no_speech_prob gate for repeats")
    hallucination_repeat_avg_logprob: float = arg_field(-1.0, help="avg_logprob gate for repeats")
    hallucination_high_risk_max_repeats: int = arg_field(2, help="Absolute repeat cap for high-risk phrases")
    filter_hallucinations: bool = arg_field(False, action="store_true", help="Apply Whisper-style hallucination filters")


@dataclass
class HymtTranslateConfig:
    """Tunable knobs shared with translate_srt_hymt.py."""

    context_size: int = arg_field(2, help="Prior translated Chinese lines used as background")
    lead_out_seconds: float = arg_field(0.0, help="Extend each displayed cue by this many seconds")
    min_display_seconds: float = arg_field(0.0, help="Minimum displayed cue duration")


@dataclass
class SakuraTranslateConfig:
    """Tunable knobs shared with translate_srt_sakura.py."""

    context_size: int = arg_field(6, help="Prior source/translation turns supplied as context")
    lead_out_seconds: float = arg_field(0.0, help="Extend each displayed cue by this many seconds")
    min_display_seconds: float = arg_field(0.0, help="Minimum displayed cue duration")


@dataclass
class GalTranslTranslateConfig:
    """Tunable knobs shared with translate_srt_galtransl.py."""

    context_size: int = arg_field(6, help="Prior translated Chinese lines supplied as context")
    batch_size: int = arg_field(8, help="Max consecutive cues translated as one GalTransl turn")
    lead_out_seconds: float = arg_field(0.0, help="Extend each displayed cue by this many seconds")
    min_display_seconds: float = arg_field(0.0, help="Minimum displayed cue duration")


@dataclass
class BilingualAssConfig:
    """Style and speaker-colour knobs shared with make_bilingual_ass.py."""

    font: str = arg_field("Microsoft YaHei", help="ASS font name")
    zh_font_size: int = arg_field(36, help="Chinese line font size")
    ja_font_size: int = arg_field(24, help="Japanese line font size")
    zh_colour: str = arg_field("&H0000FFFF", help="Chinese line ASS colour &HAABBGGRR")
    ja_colour: str = arg_field("&H00B4B4B4", help="Japanese line ASS colour &HAABBGGRR")
    male_colour: str = arg_field("&H00FFBF00", help="Male-speaker Chinese line ASS colour")
    female_colour: str = arg_field("&H00B478FF", help="Female-speaker Chinese line ASS colour")
    play_res_x: int = arg_field(1280, help="ASS PlayResX")
    play_res_y: int = arg_field(720, help="ASS PlayResY")
    colour_by_speaker: bool = arg_field(False, action="boolean_optional", help="Colour cues by speaker classification")
    gender_confidence: float = arg_field(0.6, help="Minimum classifier confidence for speaker colour")
