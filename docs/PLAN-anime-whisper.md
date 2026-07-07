# WJ-style anime ASR migration plan

Last updated: 2026-07-07

## Goal

The DLDSS-492 comparison showed two different strengths:

- The existing Qwen3-ASR path produces relatively clean subtitles, but misses weak speech, breathy dialogue, and mixed moan/dialogue regions.
- WhisperJAV's anime path has better weak-speech recall, but its final SRT can have long cues and overlaps.

The goal is not to copy WhisperJAV's final subtitles wholesale. The goal is to borrow the parts that directly address our failures: anime-whisper as a text source, WhisperSeg weak-speech VAD, VAD-only timing for anime, and WJ-style semantic scene boundaries. The existing project subtitle shaping, overlap cleanup, translation, and ASS generation remain the output chain.

The top-level default project pipeline is now `--asr anime`, which selects
`--text-backend anime` in the shared Qwen/anime sub-script. The sub-script's raw
`QwenAsrConfig.text_backend` default remains `qwen` so direct script use stays
explicit, but the normal video pipeline now uses the WJ-style anime path:

```text
audio
  -> WhisperSeg grouped jobs
  -> anime-whisper text
  -> anime text cleaner
  -> vad_only pseudo timing
  -> chunk_entries / finalize_qwen_entries
  -> translate / ASS
```

Optional diagnostic paths remain available:

```text
audio
  -> current VAD or WhisperSeg
  -> anime-whisper text
  -> anime text cleaner
  -> Qwen forced aligner
  -> collapse sentinel / recovery
  -> chunk_entries / finalize_qwen_entries
```

Semantic scene is implemented and enabled by default for the anime path:

```text
semantic scene
  -> WhisperSeg per scene
  -> anime-whisper text
  -> vad_only pseudo timing
  -> existing subtitle shaping chain
```

## Implemented

### Stage 0: API and environment probes

Implemented and verified:

- `Qwen3ForcedAligner.align(audio=(np.ndarray, sr), text, language)` supports in-memory numpy clips, so the aligner path does not need temporary WAV files.
- Direct aligner language is normalized with `qwen_aligner_language()`; CLI values such as `ja` map to `Japanese`.
- WhisperSeg model resolution is local-only by default: `models/whisperseg/model.onnx`.
- WhisperSeg ONNX provider logging was added. Host CUDA was verified; sandboxed CUDA errors must not be treated as real host failures.

Relevant code:

- `scripts/transcribe_ja_srt_qwen.py`
- `scripts/whisperseg_vad.py`
- `tests/test_transcribe_qwen.py`

### Stage 1: anime text backend and aligner diagnostics

Implemented:

- `--text-backend anime`
- `--text-model models/anime-whisper`
- `--timestamp-mode aligner_fallback | aligner_only | vad_only`
- `--no-repeat-ngram-size`
- anime text generation through `WhisperProcessor` + `WhisperForConditionalGeneration`
- conservative anime cleaner in `scripts/anime_text_clean.py`
- standalone Qwen forced-aligner path for `aligner_fallback` and `aligner_only`
- raw dump/replay support for anime schema
- recapture ignored with a warning on anime backend

The anime backend uses a two-phase structure:

1. Generate all clip texts with anime-whisper.
2. Either build VAD-only pseudo timing, or load the standalone Qwen aligner and align all non-empty clips.

The Qwen backend still uses the existing `Qwen3ASRModel.from_pretrained(..., forced_aligner=...)` path.

### Stage 2: collapse sentinel and recovery

Implemented:

- `scripts/alignment_recovery.py`
- `items_to_words()` / `words_to_items()` adapters
- collapse assessment
- VAD-guided redistribution for collapsed aligner output
- proportional fallback
- raw dump fields for `raw_items`, `recovered_items`, `sentinel`, `recovery`, and final `items`

Important finding:

- WhisperJAV's anime path avoids many collapse problems by using `vad_only`, not by relying on forced-aligner recovery.
- Short collapsed phrases can evade sentinel logic because WhisperJAV also skips assessment for very short text. For anime, the stronger fix is to avoid forced aligner timing by default.

### Stage 3: WhisperSeg VAD

Implemented:

- `--vad-backend current | whisperseg`
- `--whisperseg-model`
- `--whisperseg-threshold`
- `--whisperseg-max-speech`
- `--whisperseg-max-group`
- `--whisperseg-chunk-threshold`
- local-only WhisperSeg model loading
- CUDA provider preference with provider/device logging

Current anime defaults, matching the WhisperJAV anime preset more closely:

```text
timestamp_mode = vad_only
vad_backend = whisperseg
whisperseg_threshold = 0.35
whisperseg_max_speech = 5.0
whisperseg_max_group = 5.0
whisperseg_chunk_threshold = 0.5
whisperseg_min_frame_seconds = 0.1
```

The top-level video pipeline now selects anime by default; Qwen remains available with `--asr qwen`.

### Stage 4: semantic scene

Implemented:

- `--scene-backend none | semantic`
- top-level `--qwen-scene-backend none | semantic`
- `--scene-min-seconds`
- `--scene-max-seconds`
- `--scene-clustering-threshold`
- semantic scene boundaries are used only to constrain WhisperSeg jobs
- scene type / `asr_prompt` are not fed to anime-whisper

Current anime default is:

```text
scene_backend = semantic
scene_min_seconds = 12.0
scene_max_seconds = 48.0
```

This matches the WhisperJAV ChronosJAV anime outer-shell default. Semantic scene is still
a normal CLI knob and can be disabled from the top-level pipeline with
`--qwen-scene-backend none` (or `--scene-backend none` when calling the sub-script
directly) for A/B testing.

## Current Evidence

All measurements below are from DLDSS-492 using the same source audio and Japanese SRT outputs. The similarity score is a rough diagnostic against WhisperJAV anime output; it is useful for relative changes, but it can underrate semantically equivalent wording.

### Timing modes

```text
WJ anime                 737 entries, display 2781.6s, avg 3.77s
ours WhisperSeg+aligner  951 entries, display 1573.2s, avg 1.65s
ours WhisperSeg+vad_only 779 entries, display 2622.3s, avg 3.37s
```

Conclusion:

- Forced aligner timing makes anime output too fragmented and too short.
- VAD-only timing is the right default for anime.

### Semantic scene experiments

```text
WJ anime                       737 entries, display 2781.6s
ours no semantic, vad_only     779 entries, display 2622.3s, avg_ratio 0.514
ours semantic 20-48, vad_only  797 entries, display 2532.8s, avg_ratio 0.525
ours semantic 12-48, vad_only  804 entries, display 2519.1s, avg_ratio 0.535
```

`semantic 12-48` produced 302 scenes, matching the WJ analytics scene count for this sample, but final ASR clips were still about 1020 because WhisperSeg frames are generated inside each scene.

Observed effects:

- Semantic scene improves some weak-speech recall. The 01:58 `ダメダメ...イク...` region appears with semantic enabled and was missing from the non-semantic VAD-only replay.
- Semantic scene does not fix all text misrecognition. The 18:36 `俺のベロで` region still misrecognizes under semantic, while an older WhisperSeg 8s run got that phrase right.
- Semantic 12-48 is slightly closer to WJ by rough similarity, but is more fragmented than WJ and can degrade some local text.

Conclusion:

- Semantic scene now matches the WJ ChronosJAV anime default. It remains a normal A/B
  knob because local windows show mixed text effects.
- The remaining gap is likely in clip boundary/context and audio input differences, not decode parameters.

### Decode parameter comparison

Our anime generator and WhisperJAV anime generator both use the same core decode pattern:

```text
WhisperProcessor + WhisperForConditionalGeneration
language = ja
task = transcribe
do_sample = False
num_beams = 1
no_repeat_ngram_size = 0 by default
max_new_tokens capped at 444
```

Therefore repeated misrecognitions should be investigated through clip construction and audio preprocessing before adding prompts, vocab hacks, or unrelated filters.

## Current Problems

### 1. Text misrecognition remains

Examples:

- WJ: `俺のベロで...`
- ours semantic / WJ-parameter runs: misrecognized as variants like `オーディンのベル` or noise text.
- older WhisperSeg 8s run recognized this phrase better.

This suggests that clip boundaries and context length materially affect anime-whisper recognition.

### 2. Semantic scene is mixed

Semantic scene helps weak-speech recall but can increase fragmentation and does not consistently improve wording.

It should stay easy to disable (`--qwen-scene-backend none` at the top level,
`--scene-backend none` in the sub-script) while local window experiments verify which
scene/VAD settings are best.

### 3. WJ parity is not just one flag

WJ anime combines:

- semantic scene by default in `QwenPipeline`
- WhisperSeg grouped framing
- VAD-only timestamp mode
- temporary WAV frame inputs read by the generator
- WJ reconstruction/regrouping

We currently match the major defaults in the top-level anime path, but not every implementation detail.

### 4. Evaluation is approximate

SRT-to-SRT text similarity is not a reliable semantic metric. It is good for regression spotting, but manual window review is still required.

## Next Steps

### Immediate next step: local misrecognition audit

Use a small set of known windows instead of full-film E2E runs:

- 18:36 region: `俺のベロで`
- 91:04 region: `でかい棒`
- 01:58 region: `ダメダメ...イク...`
- 02:18:35 region around apology / climax lines

For each window, run anime-whisper on:

1. current exact clip
2. clip with 0.5s leading/trailing context
3. clip with 1.0s leading/trailing context
4. merged adjacent WhisperSeg groups
5. temp WAV written to disk and loaded like WJ
6. in-memory numpy input

Goal:

- If expanded or merged clips fix recognition, tune grouping/context.
- If temp WAV/librosa fixes recognition, inspect audio preprocessing.
- If none fix recognition, compare model files/config and WJ raw frame text if available.

### Short-term implementation candidates

Only implement after the audit identifies a cause:

- Add a small anime-only context padding knob around WhisperSeg jobs.
- Add a WJ-like temp WAV/librosa diagnostic mode, not as default.
- Tune WhisperSeg grouping if it improves both weak-speech recall and misrecognition windows.
- Keep semantic scene easy to disable unless it improves the selected windows consistently.

### Later work

After anime stabilizes:

- Keep README / README-CN default-command docs in sync with the anime default.
- Consider moving selected WJ improvements back to the Qwen text backend.
- Consider Qwen text-only assembly, dynamic token budget, repetition penalty, or semantic+WhisperSeg framing for Qwen only after anime evidence is understood.

## Out Of Scope For Now

- Speech enhancement / dual-track VAD.
- NVV moan classifier.
- Whisper hallucination JSON vocabulary. WhisperJAV anime does not rely on it; this project only ports the anime cleaner for now.
- Ensemble / smart merge.
- GUI integration.
- Full benchmark framework migration.
- Prompt/context injection into anime-whisper. The model path intentionally ignores context.

## Validation

Current repository validation after the anime/WhisperSeg/semantic changes:

```bash
python -m pytest tests -q
python -m compileall -q scripts tests
git diff --check
```

Latest observed result:

```text
232 passed
```

## Key Files

Modified:

- `scripts/pipeline_configs.py`
- `scripts/transcribe_ja_srt_qwen.py`
- `tests/test_transcribe_qwen.py`

Added:

- `scripts/anime_text_clean.py`
- `scripts/alignment_recovery.py`
- `scripts/whisperseg_vad.py`
- `scripts/semantic_scene.py`
- `tests/test_anime_clean.py`
- `tests/test_alignment_recovery.py`
- `THIRD_PARTY_NOTICES.md`
- `docs/PLAN-anime-whisper.md`

Preserved project output chain:

- `chunk_entries`
- `sentences_from_alignment`
- `finalize_qwen_entries`
- overlap / near-duplicate / filler filters
- translation pipeline
- ASS generation
- quality report
