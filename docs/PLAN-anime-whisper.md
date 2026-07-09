# WJ-style anime ASR migration plan

Last updated: 2026-07-08

## Goal

The primary long-form evaluation clip showed two different strengths:

- The existing Qwen3-ASR path produces relatively clean subtitles, but misses weak speech, breathy dialogue, and mixed moan/dialogue regions.
- WhisperJAV's anime path has better weak-speech recall, but its final SRT can have long cues and overlaps.

The goal is not to copy WhisperJAV's final subtitles wholesale. The goal is to borrow the parts that directly address our failures: anime-whisper as a text source, WhisperSeg weak-speech VAD, VAD-only timing for anime, and WJ-style semantic scene boundaries. The existing project subtitle shaping, overlap cleanup, translation, and ASS generation remain the output chain.

The top-level default project pipeline is now `--asr anime`, which selects
`--text-backend anime` in the shared Qwen/anime sub-script. The sub-script's raw
`QwenAsrConfig.text_backend` default remains `qwen` so direct script use stays
explicit. After Stage 6.8, qwen's own default framing is WhisperSeg + semantic scene +
short scene-padded recognition windows + aligner fallback recovery + WJ-derived cue regrouping.
The normal video pipeline now uses the WJ-style anime path:

```text
audio
  -> semantic scene with padded ASR/VAD windows
  -> WhisperSeg grouped frames
  -> anime-whisper text
  -> anime text cleaner
  -> vad_only frame timing + readability split
  -> final overlap/filler hygiene
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
  -> vad_only frame-native timing
  -> existing final hygiene chain
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
2. Either keep VAD-only frame-native timing, or load the standalone Qwen aligner and align all non-empty clips.

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
- top-level `--anime-scene-backend none | semantic`
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
scene_asr_pad_seconds = 0.35
```

This matches the WhisperJAV ChronosJAV anime outer-shell default. The `scene_asr_pad_seconds`
value mirrors WhisperJAV's padded `asr_processing` scene windows: scene boundaries remain the
timeline reference, while ASR/VAD sees a small overlap around scene edges. Semantic scene is
still a normal CLI knob and can be disabled from the top-level pipeline with
`--anime-scene-backend none` (or `--scene-backend none` when calling the sub-script
directly) for A/B testing.

## Current Evidence

All measurements below are from the same primary long-form evaluation clip using the same source audio and Japanese SRT outputs. The similarity score is a rough diagnostic against WhisperJAV anime output; it is useful for relative changes, but it can underrate semantically equivalent wording.

### Latest anime parity check (2026-07-08)

After matching WhisperJAV's padded semantic scene `asr_processing` windows and changing
anime `vad_only` reconstruction to frame-native output, the default anime line became close
to WhisperJAV anime on the primary long-form clip:

```text
ours anime ASS        712 dialogue cues, 0 overlaps
WhisperJAV anime ASS  737 dialogue cues, 41 overlaps
Japanese line sequence similarity: 0.9648
Exact Japanese matches after sequence alignment: 699 lines
Matched-line start time within 0.02s: 694 / 699
```

The remaining cue-count gap is mostly short filler/moan/interjection cues that WhisperJAV
keeps and this project drops through final hygiene, plus overlap resolution: WhisperJAV keeps
some overlapping cue times, while this project de-overlaps final output. The largest remaining
text differences are concentrated in low-clarity breathy/moan regions, not in the previous
large-scale anime framing or sentence-splitting mismatch.

Current follow-up: the default anime line now keeps the same WJ-like ASR framing but applies
a length-only readability split within a frame (long comma segments >50 chars, hard cap 80
chars; sentence punctuation and `…` never split) and strips leading soft ellipses. An earlier
version also split at sentence enders (`。？！?!`), but anime-whisper sprays enders on every
soft pause, so that over-fragmented frames into sub-second flash cues; sentence-splitting was
reverted and only the length cap remains. This intentionally trades exact WJ output parity for
more readable final subtitles while preserving the ASR windowing that fixed the earlier
recognition mismatch.

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

It should stay easy to disable (`--anime-scene-backend none` at the top level,
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

### Completed qwen context experiment

Current qwen default intentionally uses short WhisperSeg frames. That fixed the original
collapse/drift failure mode, but it also means most clips are only about 5-6 seconds long.
The shorter context appears to hurt Qwen text recognition compared with longer segments,
even though timing is cleaner.

Stage 6.5 implemented **long-context recognition with short-anchor timing** as an
experiment. The key
constraint is to decouple the audio span Qwen hears from the cue ownership span used for
timing and dedup:

- Recognition span: a longer merged/padded audio window fed to Qwen for better text.
- Ownership span: the original WhisperSeg frame(s) whose cue centers this job may emit.
- Timing source: forced aligner when healthy; VAD-guided fallback when the sentinel marks
  collapse. The fallback must use the owned speech regions, not the entire padded context.

Implementation plan:

1. Add a qwen-only WhisperSeg context mode. **Implemented.** It was briefly enabled as
   the Qwen default during Stage 6.5, then disabled by default after Stage 6.7 testing
   showed longer merged windows increased Qwen hallucination and tail drift.
   - `--qwen-whisperseg-context-mode none|pad|merge` (current Qwen default: `none`).
   - `pad`: widen each WhisperSeg job by bounded pre/post audio context, but keep
     `keep_lo/keep_hi` and `speech_regions` tied to the original frame.
   - `merge`: merge adjacent WhisperSeg groups. Below `target_seconds` the merge tolerance
     is `merge_gap`; **once a group passes the soft target the tolerance tightens to
     `after_target_gap`** (default 0.2s), so the group ends at the next real pause instead
     of greedily merging until `hard_max_seconds` forces a mid-speech cut. `hard_max_seconds`
     is the true safety cap and only bounds genuinely gap-free speech. Retain the original
     component speech regions inside the merged clip.
   - Pre/post context is orthogonal to merging and applies in both `pad` and `merge`
     modes, so `merge + pad` is a supported benchmark candidate. Fixed pre/post padding
     remains available; ratio padding computes pad from the final owned span and clamps it
     with min/max seconds.
2. Extend `ChunkJob` only as much as needed:
   - keep `start/end` as the recognition audio slice.
   - keep `keep_lo/keep_hi` as the cue ownership window.
   - keep `speech` as clip-relative owned speech regions for sentinel fallback.
   - if merge needs debugability, add metadata such as component frame ranges to raw dumps,
     not to cue shaping logic.
3. Build jobs in two layers:
   - First run WhisperSeg exactly as today to get atomic frames.
   - Then apply optional qwen context expansion/merge to create recognition jobs.
   - The first benchmark isolated context length; current Qwen defaults use semantic scene
     with context mode `none`.
4. Preserve collapse/drift protection:
   - For `aligner_fallback`, assess aligner items against the full recognition clip.
   - On collapse, redistribute words over the owned `speech` regions only.
   - Filter emitted cues by `keep_lo/keep_hi` so extra context cannot duplicate neighboring
     cues or claim text from outside the job's ownership span.
5. Benchmark candidates before changing defaults: **done on the primary long-form
   evaluation clip; merge/pad was later rejected as the current default after manual review.**
   - baseline: previous qwen default (`context-mode none`, 6.0/1.0).
   - pad: e.g. pre 0.5s / post 1.0s, then 1.0s / 1.5s if safe.
   - merge: e.g. soft target 12s, 18s, 24s with a small max inter-frame gap and a hard
     cap around 32-36s.
   - merge + pad: tested candidate `merge_gap=2.0`, soft `target=18`,
     `after_target_gap=0.2`, `hard_max=35`, fixed `pre/post=2.0`; ratio padding stayed
     experimental. It is still selectable, but not the default because later subtitle
     review showed more hallucination and tail drift than `context-mode none`.
   - optional diagnostic only: `vad_only` timing to separate text-window effects from
     forced-aligner effects. Follow-up A/B showed that `vad_only + merge/pad` can repeat
     whole neighboring lines because there is no aligner ownership filter to reject text
     heard from context. `vad_only + context-mode none` removes that context-leak repeat,
     but produces shorter, more fragmented cues. Therefore qwen `vad_only` is kept as a
     diagnostic-only mode and is rejected unless `whisperseg_context_mode=none`.
6. Evaluate with both automatic and manual checks:
   - Re-run the primary long-form qwen benchmark.
   - Inspect the known weak/misheard windows manually.
   - Track cue count, short cues, overlaps, same-start piles, sentinel collapse rate,
     recovered collapse rate, and raw text quality.

Result: the context machinery remains available for targeted experiments, but the current
Qwen default is `--qwen-whisperseg-context-mode none` because the longer windows did not
preserve text quality cleanly enough for production defaults.

### Later work

After anime stabilizes:

- README / README-CN default-command docs must stay in sync with the anime default.
- Qwen and anime now have separate config surfaces, so qwen no longer inherits anime
  defaults (`vad_only`, WhisperSeg 5.0/0.5, semantic scenes).
- Selected WJ qwen improvements are ported and benchmarked — see "## Qwen line
  (Stage 6): WJ feature audit and plan" below for the line-cited audit and final
  default decision.

## Qwen line (Stage 6): WJ feature audit and plan

Status: Stage 5.9 through 6.8 are implemented and benchmarked/manual-reviewed. The
current project default remains the anime line. The current qwen default is short
scene-padded WhisperSeg framing: qwen WhisperSeg values (6.0/1.0), semantic scene ON,
context mode `none`, aligner fallback recovery, WJ-style generation knobs, WJ-style cue
regrouping (`phrase_max_chars=80`, `phrase_max_internal_gap=1.5`), and step-down OFF.
WhisperJAV's code is layered (deprecated modes, generic defaults vs generator overrides
vs v4 YAML vs CLI defaults), so this section keeps the line-cited audit and experiment
history, but final defaults come from post-alignment ablations and manual subtitle review
rather than blanket WJ parity.

### Stage 5.9 prerequisite: split qwen and anime configs

Implemented. This was required before any qwen WJ port.

Problem addressed:

- Before Stage 5.9, `scripts/pipeline_configs.py::QwenAsrConfig` hosted both qwen and
  anime knobs.
- Top-level `--asr anime` uses the shared qwen sub-script with `text_backend=anime`.
- Anime defaults now live in the shared config: `timestamp_mode=vad_only`,
  `vad_backend=whisperseg`, `whisperseg_max_group=5.0`,
  `whisperseg_chunk_threshold=0.5`, and `scene_backend=semantic`.
- If `transcribe_qwen()` starts honoring `vad_backend` / `scene_backend` for qwen without
  splitting config first, `--asr qwen` would silently inherit anime defaults. That would
  break the baseline comparison line and make Stage 6 results hard to interpret.

Implemented shape:

- Do not duplicate the full ASR config. Most fields are shared by both lines:
  language/batch/device/dtype, fixed/VAD clip construction, cue shaping, filler and
  near-duplicate filters, hallucination gates, recapture knobs, and common postprocess
  thresholds. Duplicating these fields into two 60+ field dataclasses would drift.
- `BaseAsrConfig` holds shared fields. `QwenAsrConfig(BaseAsrConfig)` and
  `AnimeAsrConfig(BaseAsrConfig)` add/override only backend-selection defaults
  (`text_backend`, text model, timestamp mode, VAD backend, WhisperSeg params,
  scene params, anime generation knobs, and future qwen WJ knobs).
- `QwenAsrConfig`: qwen-only backend defaults and help text. Current default is
  WhisperSeg 6.0/1.0 + semantic scene + scene ASR pad 0.35 + context mode `none` +
  aligner-fallback recovery + WJ-style generation/cue-regrouping knobs; step-down
  remains selectable but OFF by default.
- `AnimeAsrConfig`: anime-only backend defaults and help text. Keep the current anime
  default: anime-whisper text, WhisperSeg 5.0/0.5, semantic scene, `vad_only` timing.
- Top-level CLI:
  - `--qwen-*` affects only `--asr qwen`.
  - `--anime-*` affects only `--asr anime`.
  - Temporary deprecated aliases still map existing anime-tuning flags named
    `--qwen-timestamp-mode` / `--qwen-scene-backend` when `--asr anime` and the
    corresponding `--anime-*` flag is unset.
- Sub-script implementation can remain `scripts/transcribe_ja_srt_qwen.py` initially.
  The split is about config/CLI semantics first; physically splitting an
  `transcribe_ja_srt_anime.py` script is optional later.
- Quality report config should follow the selected ASR line: anime and qwen both default
  to WhisperSeg/metadata-compatible reporting when that metadata is available.

Validation for the split:

- `tests/test_cli_config.py`: separate round trips for `QwenAsrConfig` and `AnimeAsrConfig`.
- `tests/test_pipeline.py`: `--asr qwen` command keeps qwen defaults; `--asr anime` command
  keeps anime defaults; deprecated aliases still map as intended.
- README / README-CN command docs use `--anime-*` for anime tuning.

### Verified facts

- **We are already on the transformers backend, and WJ uses the SAME package.** The
  `qwen_asr` PyPI package has two backends (`inference/qwen3_asr.py`): `from_pretrained`
  → **transformers** backend (L176–217, `backend="transformers"`), inference at L510 is a
  plain HF `self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)`; vLLM is a
  separate opt-in constructor (L237+, needs `qwen-asr[vllm]`) that we do NOT use. WJ's
  `whisperjav/modules/qwen_asr.py` is a wrapper around this **same package**
  (`from qwen_asr import Qwen3ASRModel`, L581/608) plus `stable_whisper` for regrouping; it
  reaches into `Qwen3ASRModel.model` (the HF `Qwen3ASRForConditionalGeneration`) / `.thinker`
  to drive generation. So the generation knobs below are reachable via the inner HF model —
  NOT blocked. (Earlier text in this file wrongly called ours "vLLM-based"; corrected here.)
- **WJ qwen3 line's actual parameters** (CLI path `whisperjav/main.py` L1159–1226; the
  anime-only override is L1216–1224 and does NOT apply to qwen3): framer `vad-grouped`
  (L1182); scene `semantic` 12–48 (`whisperjav/pipelines/qwen_pipeline.py` L109/213–214);
  segmenter `whisperseg`
  **max_group 6.0 / chunk_threshold 1.0** (L119–120 — qwen values; anime overrides to 5.0/0.5);
  `timestamp_mode = aligner_vad_fallback` (L1175) = trust aligner, fall back to VAD timing on
  collapse; `stepdown_enabled=True` 6.0/6.0 (L152–154); `assembly_cleaner=True`;
  `repetition_penalty=1.1` (L157); `max_tokens_per_audio_second=20.0` (L158); `max_new_tokens=4096`.
- **Reusable infra already present:** `build_whisperseg_jobs` (populates clip-relative
  `job.speech`), `alignment_recovery.assess_alignment_quality` / `redistribute_collapsed_words`,
  the `_time_anime_job` sentinel wrapper, `semantic_scene.detect_scenes`, `whisperseg_vad`,
  `chunk_entries`, `finalize_qwen_entries`, `subtitle_benchmark.py`.

### Per-feature decision

| WJ qwen feature | WJ actual value | Decision | Why / how |
|---|---|---|---|
| Config split | n/a | **ADD FIRST** | Prevents anime defaults from leaking into qwen. Add `AnimeAsrConfig`, qwen-only defaults, `--anime-*` top-level flags, and compatibility aliases. |
| WhisperSeg vad-grouped framing | max_group **6.0**, chunk_threshold **1.0** | **DEFAULT after Stage 6.3** | The primary long-form benchmark moved qwen consensus recall 77.4% -> 90.5% and weak-speech recall 8.8% -> 13.7%. Use qwen values 6.0/1.0 (not anime 5.0/0.5). |
| Semantic scene 12–48 | semantic 12–48 | **IMPLEMENTED, DEFAULT ON after later manual review** | WJ qwen default is semantic ON. Stage 6.4 briefly turned it off after one benchmark, but later subtitle review found semantic scene reduced some Qwen recognition errors, so the current Qwen default is semantic ON while it remains selectable. |
| aligner_vad_fallback timing | aligner + VAD fallback on collapse | **DEFAULT after Stage 6.3** | We already have this mechanism (sentinel + `redistribute_collapsed_words` w/ `job.speech`). It reduces short-sub/collapse symptoms and preserves aligner timing where healthy. |
| repetition_penalty 1.1 | generate() sampling | **DEFAULT after Stage 6.3** | Feasible on our transformers backend; the implementation sets the verified thinker's HF `generation_config` path and warns if unavailable. |
| dynamic token budget (20 tok/s) | `_compute_dynamic_token_limit` | **DEFAULT after Stage 6.3** | Implemented as batch-safe `per_batch_max`; the primary long-form benchmark showed a small qwen recall gain when combined with WhisperSeg. |
| text-only assembly + `merge_master_with_timestamps` | decoupled gen→align→merge | **OPTIONAL (not required)** | Feasible — `transcribe(return_time_stamps=False)` for text + our existing standalone `Qwen3ForcedAligner` for timing (both already used by anime). But NOT needed for the two knobs above (they work in bundled mode), and bundled already merges text+align. Only adopt if we want WJ-style separation or to unify qwen+anime under one two-phase path. |
| AssemblyTextCleaner | pre-align text clean | **NARROW PORT DONE** | Only the runaway-repetition half was a real gap (`行く×7` etc.). WJ's own regex under-collapses it (`行く×7 → 行く×5`), so we ported a clean minimal-unit scanner `collapse_repeated_phrases` (threshold 4 / keep 2) in `finalize_qwen_entries` instead. Did NOT port the Whisper-era hallucination list or sentence dedup (near-dup covers it). See Stage 6.4b. |
| step-down retry | on, 6.0/6.0 | **IMPLEMENTED, DEFAULT OFF after Stage 6.4** | `reframe_collapsed_jobs` + step-down pass in `transcribe_qwen`: collapsed jobs re-framed via WhisperSeg at `stepdown_fallback_group` and re-transcribed, cues replaced. WJ's default `fallback == main` (6.0) is effectively inert on our deterministic path; tighter 3.0 was benchmarked and did not help, so step-down remains selectable but OFF by default. |

### Staged approach

- **Stage 5.9 — config split:** done. `AnimeAsrConfig` is first-class, top-level
  `--anime-*` flags exist, qwen defaults are qwen-only, and compatibility aliases/tests
  cover the formerly anime-tuning flags under `--qwen-*`.
- **Stage 6.0 — probe:** done. `scripts/probe_qwen_stage6.py` builds qwen-style
  WhisperSeg jobs, runs `Qwen3ASRModel.transcribe(return_time_stamps=True)`, reports
  clip-relative timestamp checks, sentinel metrics, generation-config path, and dynamic
  token-budget decisions. Host probe on a local WAV sample confirmed:
  - WhisperSeg uses CUDA provider.
  - qwen bundled aligner `time_stamps.items` are clip-relative.
  - `repetition_penalty` can be applied at `model.model.thinker.generation_config`.
  - `model.max_new_tokens` is batch-level in the bundled path, so Stage 6.2 must use
    batch-safe budgeting (batch=1 for dynamic mode, max-per-batch, or budget grouping).
  The probe samples did not produce a collapsed long clip, so Stage 6.1 should still test
  sentinel/recovery with synthetic items and real collapsed samples when available.
- **Stage 6.1 — framing + sentinel/recovery:** done. `transcribe_qwen()` now honors
  qwen-only `vad_backend`/`scene_backend` (dispatching WhisperSeg/semantic through
  `build_qwen_jobs`). Bundled qwen `time_stamps.items` now pass
  through the shared `_time_aligned_job` sentinel/recovery path before `chunk_entries`.
  Qwen raw dumps now include `speech_regions`, `raw_items`, `sentinel`, `recovery`,
  `recovered_items`, and final `items`; `--from-raw` replays the new schema and can use
  `raw_items` for aligner-only comparison.
- **Stage 6.2 — generation knobs (cheap, feasible):** done. Qwen now uses WJ-style
  generation defaults (`max_new_tokens=4096`, `repetition_penalty=1.1`,
  `max_tokens_per_second=20.0`, `min_tokens_floor=256`). The implementation sets the
  verified inner HF generation config path and uses a batch-safe `per_batch_max` dynamic
  token budget, temporarily assigning `model.max_new_tokens` for each bundled
  `transcribe()` batch and restoring it afterwards. Qwen WhisperSeg/semantic top-level
  flags are also exposed so Stage 6.1 opt-in modes are reachable from `video_to_zh_srt.py`.
- **Stage 6.3 — benchmark + defaults:** done on the primary long-form evaluation clip with WJ anime and WJ qwen
  references. The runner names the fully enabled ported subset `qwen_wj_core`: WhisperSeg,
  semantic scenes, collapse recovery, and generation knobs only; it deliberately does not
  imply WJ step-down retry, AssemblyTextCleaner, or full stable-ts regroup parity.
  `qwen_whisperseg_gen` was the best candidate in this Stage 6.3 slice because it improved
  both consensus and weak-speech recall over the old qwen baseline without the
  semantic-scene weak-speech regression seen in this sample. Later stages changed the
  default again after full WJ alignment, semantic-scene review, and context-window review.

  | candidate | consensus recall | weak-speech recall | timing |
  | --- | ---: | ---: | --- |
  | WJ-anime | 100.0% (474/474) | 100.0% (205/205) | cues=737 short=1 long=0 ov=41 |
  | WJ-qwen | 100.0% (474/474) | 0.0% (0/205) | cues=954 short=175 long=19 ov=29 |
  | ours-anime | 93.7% (444/474) | 56.6% (116/205) | cues=804 short=2 long=0 ov=0 |
  | qwen_current | 77.4% (367/474) | 8.8% (18/205) | cues=923 short=12 long=0 ov=0 |
  | qwen_recovery | 77.6% (368/474) | 9.3% (19/205) | cues=941 short=9 long=0 ov=0 |
  | qwen_whisperseg | 90.5% (429/474) | 13.7% (28/205) | cues=1023 short=3 long=0 ov=0 |
  | qwen_whisperseg_gen | 91.4% (433/474) | 14.6% (30/205) | cues=1078 short=3 long=0 ov=0 |
  | qwen_wj_framing | 91.1% (432/474) | 10.2% (21/205) | cues=1048 short=2 long=0 ov=0 |
  | qwen_wj_core | 91.8% (435/474) | 9.3% (19/205) | cues=1103 short=4 long=0 ov=0 |

  Caveat (do not over-read): WJ-anime / WJ-qwen are the benchmark *references* — their
  100% rows are tautological (the consensus/weak-speech segments are defined from them;
  weak-speech = "WJ-anime has, no qwen ref has", so any qwen ref scores ~0% there by
  construction). Compare only the `ours-*` / `qwen_*` rows. Also, this run had **no
  step-down**, so the "semantic hurts qwen weak-speech" reading (qwen_wj_* 9–10% vs
  qwen_whisperseg_gen 14.6%) is measured against a config WJ never ships — WJ always pairs
  semantic **with** step-down.

  Decision (revised): do NOT flip the qwen default from this partial benchmark. First align
  qwen fully to the WJ qwen default, then ablate. See Stage 6.3.5 / 6.4.
- **Stage 6.3.5 — full WJ-qwen alignment experiment: DONE (historical).** This stage
  temporarily aligned qwen to WJ qwen for ablation: `vad_backend=whisperseg` 6.0/1.0,
  `timestamp_mode=aligner_fallback` (≈ WJ `aligner_vad_fallback`),
  `repetition_penalty=1.1`, dynamic token 20 tok/s, and `scene_backend` flipped
  `none → semantic` (12–48). Stage 6.4 later reverted semantic/step-down defaults
  historically; later manual review restored semantic ON, while Stage 6.5 context
  merge/pad remained selectable but not default. **Step-down implemented**
  (`reframe_collapsed_jobs` + a step-down pass in `transcribe_qwen`): after the main pass, each
  job whose sentinel is `COLLAPSED` is re-framed via WhisperSeg at `stepdown_fallback_group`
  and re-transcribed, its cues replaced (and its raw chunk marked `superseded_by_stepdown` so
  `--from-raw` stays consistent). Config: `stepdown` (default False), `stepdown_fallback_group`
  (default **6.0**). **Important WJ finding:** WJ ships `fallback == main max_group` (6.0), so
  `reframe` re-creates the same frames and re-decodes identically on our deterministic path —
  i.e. WJ's default step-down is effectively **inert** (proof: `qwen_pipeline.py` L412 main
  framer = `segmenter_max_group_duration` 6.0; `StepDownConfig.fallback_max_group_s` 6.0;
  `vad_grouped.py::reframe` just re-runs the segmenter with that value; `stepdown_initial_group`
  is stored but unused). We kept step-down selectable but OFF by default; the ablation (6.4)
  tested tighter `stepdown_fallback_group` values (e.g. 3.0) and still did not improve the
  default tradeoff. The AssemblyTextCleaner narrow port is covered in Stage 6.4b.

  **Faithful WJ-qwen baseline (primary long-form clip, vs WJ-anime + WJ-qwen refs):** `qwen_wj_core` =
  consensus **91.8%** (435/474), weak-speech **9.3%** (19/205), cues=1093 short=4 long=0 ov=0.
  Step-down *fired* on the full film (`collapsed_jobs=53 reframed=55 entries_added=78`,
  fallback 6.0) yet the score is **identical** to the Stage 6.3 no-step-down `qwen_wj_core`
  (91.8%/9.3%) — empirical confirmation that step-down at `fallback == main` (6.0) re-decodes
  the same-granularity clip and does not fix collapse. Semantic ON also costs weak-speech here
  (9.3% vs semantic-OFF `qwen_whisperseg_gen` 14.6%); resolving that is the Stage 6.4 ablation,
  not an alignment change.
- **Stage 6.4 — ablation optimization: DONE.** Ablated on a **neutral GT** (WJ-anime ∩
  ours-anime, 560 consensus / 119 weak-speech, **no qwen in the reference** so WJ-qwen scores
  as a fair candidate). Primary long-form clip:

  | candidate | consensus | weak-speech | cues | short | long | ov |
  |---|---:|---:|---|---|---|---|
  | WJ-qwen | 79.3% | 25.2% | 954 | **175** | **19** | **29** |
  | qwen_current (Silero) | 66.4% | 10.9% | 923 | 12 | 0 | 0 |
  | **semoff_sd6** (semantic off, sd inert) | 77.9% | **22.7%** | 1078 | 3 | 0 | 0 |
  | wjcore_sd6 (aligned: semantic on, sd inert) | 77.5% | 16.8% | 1093 | 4 | 0 | 0 |
  | wj_sd3 (semantic on, sd 3.0) | 77.9% | 15.1% | 1120 | 4 | 0 | 0 |
  | semoff_sd3 (semantic off, sd 3.0) | 77.7% | 21.8% | 1098 | 3 | 0 | 0 |

  Findings: (1) **vs WJ-qwen we win the quality/timing tradeoff** — WJ-qwen leads recall by
  ~1–2.5pt but ships **175 short + 19 long + 29 overlapping** cues (the collapse problem); our
  best (`semoff_sd6`) trails recall by ~2pt with **3 short / 0 long / 0 overlap**. (2) **Semantic
  ON costs ~6pt weak-speech** (22.7→16.8) with no consensus gain. (3) **Step-down 3.0 (which
  actually tightens: reframe 97 vs 55) still doesn't help** — weak-speech −1pt, more cues.
  **Historical Stage 6.4 decision:** qwen default became `semoff_sd6` (semantic OFF,
  step-down OFF). Later review changed the current default back to semantic ON and kept
  step-down OFF; both semantic scene and step-down stay selectable.
- **Stage 6.4b — AssemblyTextCleaner (narrow port): DONE.** Analysis: WJ's cleaner and our
  `finalize_qwen_entries` are complementary — ours already does interjection removal + timing
  hygiene + filler-core collapse; the one real gap is **general runaway phrase repetition**
  (`行く×7`, `だめ×4`, `ああ×6`) which survives our filler-only collapse. **But WJ's own params
  don't fix it**: WJ Stage-1a regex `([\p{L}\p{N}]{2,8})\1{2,}` is greedy and reduces `行く×7`
  only to `行く×5` (verified with WJ's `regex` lib), and its recursive stage fires only at ≥10.
  So we ported a **clean minimal-unit scanner** instead (`collapse_repeated_phrases`, threshold
  4 / keep 2): `行く×7 → 行く行く`, genuine 2–3× emphasis untouched. Applied in
  `finalize_qwen_entries` (Base config `collapse_repeats`, both lines). We did NOT port WJ's
  hallucination phrase list (Whisper-era) or sentence dedup (we have near-dup).
- **Stage 6.5 — qwen context recovery: DONE, SELECTABLE BUT NOT DEFAULT.** Stage 6.4 solved
  the collapse/drift tradeoff by moving qwen to short WhisperSeg-framed clips, but those
  clips are now often only about 5-6 seconds and can reduce Qwen recognition quality in
  some regions. Code supports long-context recognition with short-anchor timing for
  experiments: qwen-only
  WhisperSeg context `pad` / `merge` modes, original-frame cue ownership, aligner timing when
  healthy, and VAD-guided fallback over owned speech regions when collapsed. Pre/post context
  also applies in `merge` mode, and ratio padding can scale context from the final merged span.

  **Soft target given real teeth + mid-speech hard-cut elimination (later Stage 6.5 pass).**
  The first merge implementation validated and printed `target_seconds` but never used it in
  the merge decision — only `merge_gap` and `hard_max` gated merging, so `target` was inert
  (changing it 18↔24 produced identical frames). It now gates: below `target` the tolerance
  is `merge_gap` (2.0s); once a group passes `target` the tolerance tightens to
  `after_target_gap` (0.2s), so groups end at the next real pause instead of being forced
  apart mid-speech when `hard_max` is reached. A `hard_cuts` counter (breaks forced by
  `hard_max` despite a mergeable gap = mid-speech truncation) and `soft_breaks` counter are
  now printed on the merge log line.

  Framing sweep on the densest primary long-form clip (measured directly from
  `build_whisperseg_jobs`, no model needed):

  | change | jobs | hard_cuts | note |
  |---|---:|---:|---|
  | original (no soft-target teeth), `hard_max=30` | 459 | 15 | 15 mid-speech seams |
  | `after_target_gap=0.2`, `hard_max=30` | 462 | 6 | soft breaks relocate most cuts to pauses, ~free (jobs +3) |
  | **`after_target_gap=0.2`, `hard_max=35` (selected)** | **460** | **0** | zero mid-speech cuts |

  Key findings from the sweep: (1) lowering `after_target_gap` relocates hard cuts to pauses
  with no fragmentation cost (jobs/owned-p90 unchanged) but floors at ~5 because a few runs
  are genuinely gap-free >30s; (2) lowering `merge_gap` does **not** shorten the longest run
  (its internal gaps are already <1.4s — it only fragments normal speech, dropping owned-p90
  17.2s→15.2s); (3) `after_target_gap` is what controls the longest run (0.2→33.7s, 0.5→41.9s,
  1.0→46.8s). The film's true longest gap-free run is 33.7s, so `hard_max=35` gives
  `hard_cuts=0` while windows stay bounded by the speech itself (≤37.7s incl pad); 40/48 are
  identical to 35 here. Selected experiment: `merge_gap=2.0 / target=18 / after_target_gap=0.2 /
  hard_max=35 / fixed pre/post=2.0`.

  Full-pipeline re-run on the same primary long-form clip with the selected experiment
  (`--asr qwen`, galtransl):
  887 cues, 9 short (<0.5s), **0 overlaps, 0 same-start piles, 0 cues >8s**, `hard_cuts=0` —
  the framing change lands clean on the timeline.

  Note on the earlier tuning table (removed): those rows varied `target` alongside `gap`
  while `target` was still inert, so any effect attributed to `target` actually came from
  `gap`/`hard_max`. The automatic quality report is a regression guard, not the final judge;
  ratio padding stays selectable but is not the default.

  All `whisperseg_context_*` getattr fallbacks in `transcribe_ja_srt_qwen.py` were aligned to
  the dataclass defaults (previously `pre/post` fell back to 0.0 vs config 2.0, `merge_gap`
  to 1.0 vs 2.0, `hard_max` to 36.0 vs config) to avoid phantom defaults on from-raw/test paths.
  Later manual subtitle review rejected merge/pad as the Qwen default because the longer
  recognition windows increased hallucination and tail drift; current production Qwen uses
  `--qwen-whisperseg-context-mode none`.

### Collapse & drift resolution — the original qwen pain point

The project started from two qwen weaknesses: forced-aligner **collapse** (a clip's words
squashed to one timestamp -> cues pile up) and **timeline drift**. Measured on the primary long-form clip with
the raw sentinel/recovery dumps:

**Aligner-level collapse (sentinel status per chunk):**

| config | collapse rate | recovered | residual collapse |
|---|---:|---:|---:|
| Silero baseline (aligner_only, no recovery) | 10.2% (64/628) | 0 | **64 (all leak to SRT)** |
| current default (whisperseg + aligner_fallback recovery) | 5.7% (51/894) | 51/51 | **0** |

WhisperSeg short frames roughly halve the collapse rate; VAD-guided recovery fixes 100% of
the remainder → **zero residual collapse**.

**Final-SRT timing hygiene (collapse "piling up" = short/overlap/same-start):**

| config | cues | short <0.4s | overlaps | same-start piles |
|---|---:|---:|---:|---:|
| Silero baseline | 923 | 12 | 0 | 0 |
| **current default** | 1078 | **3** | **0** | **0** |
| WJ-qwen | 954 | **175** | **29** | 4 |

Our cues do not pile up; WJ-qwen's own output carries the collapse (175 short + 29 overlaps).

**Drift vs the detected speech onset (ground-truth-ish; cue start − WhisperSeg speech onset):**

| config | median offset | p90 \|offset\| | collapsed-cue p90 \|offset\| |
|---|---:|---:|---:|
| Silero baseline | +0.20s | 3.00s | **6.92s** |
| **current default** | +0.32s | **1.12s** | **0.00s** |

Worst-case drift is cut (3.00s → 1.12s), and **recovery anchors collapsed cues exactly onto
detected speech (6.92s → 0.00s)**. The residual +0.3s median is WhisperSeg's `speech_pad`
convention — a consistent lead, not chaotic drift (a global shift would zero it if desired).

Verdict: collapse and collapse-driven drift are resolved; the current qwen line is cleaner on
timing than WJ-qwen itself, at ~2pt lower raw recall (see Stage 6.4).

### Known limitation: name/word disambiguation at the ASR→translation boundary

Example from the primary long-form clip: audio「まこと？」→ qwen ASR faithfully emits kana「まこと？」→
galtransl renders it「真的吗?」. This is **not an ASR error** — qwen heard the sound
correctly; 「まこと」is genuinely ambiguous (the name 誠 / Makoto vs 真 "really/truly"), and
the name 誠 never appears as kanji anywhere in the film, so neither stage can anchor it.

Neither translation-context lever fixes this specific case:
- **Look-ahead is already implemented** via galtransl block mode (`translate_batch_size=8`,
  grouping consecutive cues with gaps ≤ `HISTORY_RESET_SECONDS=10`; the whole block is
  translated in one turn, so lines see each other both directions). This cue was already
  batched with the following confession line「俺とやり直してくれないか」and still mistranslated.
- **Bilingual history is off-distribution for galtransl v3** — its fine-tuned prompt takes
  context as one user message with a 历史翻译 block of *prior Chinese translations only*
  (`list[str]`), explicitly "must not be reused for other backends". The bilingual chat-pair
  history (JA user / ZH assistant) already exists as the **sakura** backend
  (`--translator sakura`), but this cue had its history reset by the preceding 18s gap, so no
  history form helps here anyway.

Conclusion: with no explicit name token anywhere, this is inherent ambiguity; the only
reliable anchor would be a per-work character-name glossary, which is error-prone for
「まこと」(would mistranslate legitimate 真 "really" uses). Left as an accepted low-frequency
limitation rather than a translation-architecture change.

## Stage 7: Anime line follow-up

Status: completed enough to keep anime as the default line.

The Stage 7 pass found that the main remaining gap to WhisperJAV anime was not the
anime-whisper model itself. It came from two project-side mismatches:

1. Semantic scenes were cut at the same boundaries, but WhisperJAV feeds ASR/VAD with a
   padded `asr_processing` scene window. This project now mirrors that with
   `scene_asr_pad_seconds=0.35`.
2. Anime `vad_only` output was still entering the aligned-stream `chunk_entries()` splitter,
   so one WhisperJAV frame could be over-fragmented by aligner-oriented splitting.
   The default anime `vad_only` path now keeps VAD frame timing first, then applies only a
   length-based readability split inside a frame (long comma segments >50 chars, hard
   80-character cap; sentence punctuation and `…` never split) before final hygiene. Sentence
   splitting was tried and reverted because anime-whisper's per-pause sentence enders
   over-fragmented frames into flash cues.

Outcome: the default anime ASS now matches WhisperJAV anime closely on the primary long-form
clip while retaining project output hygiene (no final overlaps). Keep forced-aligner modes
diagnostic only unless new evidence shows a net gain over `vad_only`.

## Stage 8: Qwen line follow-up

Qwen is now the next optimization target. Its current default keeps semantic scene on but
uses short scene-padded WhisperSeg frames directly (`--qwen-whisperseg-context-mode none`),
because longer merged context windows increased Qwen hallucination and tail drift in current
tests. Cue regrouping is WJ-derived: adjacent cues inside one clip merge
only when the pause is under WJ's 1.5 seconds and the combined cue stays within 80 content
characters / 8 seconds.

Planned checks:

1. Re-run the current Qwen default against the same anonymized evaluation set used for anime
   parity. Compare against both the old Qwen baseline and the stable anime default.
2. Separate failures by cause: scene boundary, WhisperSeg frame boundary, context merge
   length, forced-aligner recovery, and translation-only ambiguity.
3. Keep semantic scene on while testing whether Qwen needs selective `pad` / `merge`
   experiments for specific failure classes; do not re-enable merge by default without
   evidence that hallucination does not regress.
4. Audit Qwen recapture for removal. Recent manual review has not shown clear value from
   `--qwen-recapture-min-gap`; keep it only if a repeatable miss case demonstrates a recall
   gain without new hallucinations.
5. Plan cleanup of code paths that no longer match the main workflow:
   - legacy Whisper ASR (`--asr whisper`, `scripts/transcribe_ja_srt.py`, gap-fill-only helpers)
     after confirming no active comparison workflow still needs it;
   - optional HY-MT translator (`--translator hymt`, `scripts/translate_srt_hymt.py`) after
     confirming GalTransl / Sakura cover the intended translation use cases.
6. Prefer WJ-derived Qwen mechanisms first; add new project-specific logic only when WJ-like
   changes cannot explain the miss.

Success criteria: improve Qwen text accuracy without regressing the current low-overlap,
low-collapse timing behavior.

### Files (Stage 6.1)

- `scripts/pipeline_configs.py` — split `QwenAsrConfig` / `AnimeAsrConfig`; keep qwen and
  anime defaults separate; add qwen-only generation fields after Stage 6.0 probe.
- `scripts/video_to_zh_srt.py` — route `--asr qwen` through qwen config and `--asr anime`
  through anime config; expose `--anime-*` flags; keep compatibility aliases temporarily.
- `scripts/transcribe_ja_srt_qwen.py` — `transcribe_qwen()` framing dispatch + sentinel/recovery
  on bundled items + raw-dump upgrade; factor `_time_anime_job` into a shared helper; set
  generation knobs only after Stage 6.0 validates the exact model attribute path and batch
  behavior.
- `tests/test_transcribe_qwen.py` — framing dispatch, sentinel-on-bundled-items, raw schema,
  generation-knob wiring.
- `tests/test_cli_config.py` / `tests/test_pipeline.py` — separate qwen/anime config
  round trips and top-level command default tests.

## Out Of Scope For Now

- Speech enhancement / dual-track VAD.
- NVV moan classifier.
- Whisper hallucination JSON vocabulary. WhisperJAV anime does not rely on it; this project only ports the anime cleaner for now.
- Ensemble / smart merge.
- GUI integration.
- Full benchmark framework migration.
- Prompt/context injection into anime-whisper. The model path intentionally ignores context.

## Validation

Current repository validation after the anime frame-native parity update and Qwen semantic
default change:

```bash
pytest -q tests/test_transcribe_qwen.py tests/test_cli_config.py tests/test_pipeline.py
git diff --check
```

Latest observed result:

```text
131 passed
```

## Key Files

Modified:

- `scripts/pipeline_configs.py`
- `scripts/cli_config.py`
- `scripts/video_to_zh_srt.py`
- `scripts/transcribe_ja_srt_qwen.py`
- `scripts/probe_qwen_stage6.py`
- `README.md`
- `README-CN.md`
- `tests/test_cli_config.py`
- `tests/test_pipeline.py`
- `tests/test_transcribe_qwen.py`
- `tests/test_probe_qwen_stage6.py`

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
- optional quality report
