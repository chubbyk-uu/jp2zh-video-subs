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
explicit. After Stage 6.3, qwen's own default framing is WhisperSeg + aligner
fallback recovery + WJ-style generation knobs, with semantic scene splitting still
opt-in for qwen. The normal video pipeline now uses the WJ-style anime path:

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
```

This matches the WhisperJAV ChronosJAV anime outer-shell default. Semantic scene is still
a normal CLI knob and can be disabled from the top-level pipeline with
`--anime-scene-backend none` (or `--scene-backend none` when calling the sub-script
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

### Later work

After anime stabilizes:

- Keep README / README-CN default-command docs in sync with the anime default.
- Split qwen and anime configuration surfaces before porting WJ features to the qwen
  line. The current shared `QwenAsrConfig` was useful for bootstrapping anime, but
  its anime defaults (`vad_only`, WhisperSeg 5.0/0.5, semantic scenes) are wrong
  defaults for the qwen comparison line.
- Bring selected WJ improvements to the Qwen line — see "## Qwen line (Stage 6): WJ feature audit and plan" below for the line-cited audit and per-feature add/do-not-add decision.

## Qwen line (Stage 6): WJ feature audit and plan

Status: Stage 5.9 config split is implemented; Stage 6 qwen WJ feature port is planned,
not implemented. Stage 6 should bring the WJ qwen wins that are actually feasible on our
stack: weak-speech recall + collapse recovery (reusing existing infra) plus generation
safety knobs (repetition_penalty, dynamic token budget) that the transformers backend exposes.
WhisperJAV's code is layered
(deprecated modes, generic defaults vs generator overrides vs v4 YAML vs CLI defaults), so
this is a line-cited audit, not a blanket port. AssemblyTextCleaner / step-down /
text-only decoupling stay gated (higher cost, unproven), and nothing is package-blocked.

### Stage 5.9 prerequisite: split qwen and anime configs

Implemented. This was required before any qwen WJ port.

Problem addressed:

- `scripts/pipeline_configs.py::QwenAsrConfig` currently hosts both qwen and anime knobs.
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
- `QwenAsrConfig`: qwen-only backend defaults and help text. Target = **full WJ-qwen
  parity** (Stage 6.3.5): WhisperSeg 6.0/1.0 + aligner-fallback recovery + generation knobs +
  **semantic scene ON** + **step-down**. The interim Stage 6.3 default (`scene_backend=none`,
  no step-down) was set from a partial benchmark and is superseded — align to WJ first, then
  ablate (Stage 6.4).
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
| WhisperSeg vad-grouped framing | max_group **6.0**, chunk_threshold **1.0** | **DEFAULT after Stage 6.3** | DLDSS-492 benchmark moved qwen consensus recall 77.4% → 90.5% and weak-speech recall 8.8% → 13.7%. Use qwen values 6.0/1.0 (not anime 5.0/0.5). |
| Semantic scene 12–48 | semantic 12–48 | **ALIGN WJ (default ON)** | WJ qwen default IS semantic ON (argparse `--qwen-scene` default=semantic, main.py L533; the L1150 `getattr(..., 'none')` is a dead fallback; wjav_out/qwen has 302 scenes confirming it). The Stage 6.3 "semantic hurts weak-speech" result was measured WITHOUT step-down; WJ always pairs semantic with step-down (which re-frames the fragmentation semantic introduces), so that finding is not a fair test of WJ's config. Enable to match WJ; re-evaluate in the post-alignment ablation. |
| aligner_vad_fallback timing | aligner + VAD fallback on collapse | **DEFAULT after Stage 6.3** | We already have this mechanism (sentinel + `redistribute_collapsed_words` w/ `job.speech`). It reduces short-sub/collapse symptoms and preserves aligner timing where healthy. |
| repetition_penalty 1.1 | generate() sampling | **DEFAULT after Stage 6.3** | Feasible on our transformers backend; the implementation sets the verified thinker's HF `generation_config` path and warns if unavailable. |
| dynamic token budget (20 tok/s) | `_compute_dynamic_token_limit` | **DEFAULT after Stage 6.3** | Implemented as batch-safe `per_batch_max`; DLDSS-492 showed a small qwen recall gain when combined with WhisperSeg. |
| text-only assembly + `merge_master_with_timestamps` | decoupled gen→align→merge | **OPTIONAL (not required)** | Feasible — `transcribe(return_time_stamps=False)` for text + our existing standalone `Qwen3ForcedAligner` for timing (both already used by anime). But NOT needed for the two knobs above (they work in bundled mode), and bundled already merges text+align. Only adopt if we want WJ-style separation or to unify qwen+anime under one two-phase path. |
| AssemblyTextCleaner | pre-align text clean | **PENDING (待定)** | WJ qwen default has it ON, but we already run `finalize_qwen_entries` + filler/near-dup filters. Decide during the ablation whether porting it adds value over our existing cleaners; NOT part of the initial WJ-alignment pass. |
| step-down retry | on, 6.0/6.0 | **IMPLEMENTED (WJ-faithful, default inert)** | `reframe_collapsed_jobs` + step-down pass in `transcribe_qwen`: collapsed jobs re-framed via WhisperSeg at `stepdown_fallback_group` and re-transcribed, cues replaced. WJ's default `fallback == main` (6.0) does not tighten → inert re-decode on our deterministic path; kept faithful. Ablation (6.4) tests tighter fallback (e.g. 3.0). |

### Staged approach

- **Stage 5.9 — config split:** done. `AnimeAsrConfig` is first-class, top-level
  `--anime-*` flags exist, qwen defaults are qwen-only, and compatibility aliases/tests
  cover the formerly anime-tuning flags under `--qwen-*`.
- **Stage 6.0 — probe:** done. `scripts/probe_qwen_stage6.py` builds qwen-style
  WhisperSeg jobs, runs `Qwen3ASRModel.transcribe(return_time_stamps=True)`, reports
  clip-relative timestamp checks, sentinel metrics, generation-config path, and dynamic
  token-budget decisions. Host probe on `work/01/01.wav` confirmed:
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
- **Stage 6.3 — benchmark + defaults:** done on DLDSS-492 with WJ anime and WJ qwen
  references. The runner names the fully enabled ported subset `qwen_wj_core`: WhisperSeg,
  semantic scenes, collapse recovery, and generation knobs only; it deliberately does not
  imply WJ step-down retry, AssemblyTextCleaner, or full stable-ts regroup parity.
  `qwen_whisperseg_gen` is the current qwen default candidate because it improves both
  consensus and weak-speech recall over the old qwen baseline without the semantic-scene
  weak-speech regression seen in this sample.

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
- **Stage 6.3.5 — full WJ-qwen alignment: DONE (code; benchmark pending GPU).** qwen default
  now matches WJ qwen: `vad_backend=whisperseg` 6.0/1.0, `timestamp_mode=aligner_fallback`
  (≡ WJ `aligner_vad_fallback`), `repetition_penalty=1.1`, dynamic token 20 tok/s, and
  `scene_backend` flipped `none → semantic` (12–48). **Step-down implemented**
  (`reframe_collapsed_jobs` + a step-down pass in `transcribe_qwen`): after the main pass, each
  job whose sentinel is `COLLAPSED` is re-framed via WhisperSeg at `stepdown_fallback_group`
  and re-transcribed, its cues replaced (and its raw chunk marked `superseded_by_stepdown` so
  `--from-raw` stays consistent). Config: `stepdown` (default True), `stepdown_fallback_group`
  (default **6.0**). **Important WJ finding:** WJ ships `fallback == main max_group` (6.0), so
  `reframe` re-creates the same frames and re-decodes identically on our deterministic path —
  i.e. WJ's default step-down is effectively **inert** (proof: `qwen_pipeline.py` L412 main
  framer = `segmenter_max_group_duration` 6.0; `StepDownConfig.fallback_max_group_s` 6.0;
  `vad_grouped.py::reframe` just re-runs the segmenter with that value; `stepdown_initial_group`
  is stored but unused). We kept the default WJ-faithful (inert); the ablation (6.4) tests
  tighter `stepdown_fallback_group` (e.g. 3.0) where it actually reduces collapse.
  AssemblyTextCleaner stays **PENDING (待定)**. Remaining: run the benchmark on GPU to record
  the faithful WJ-qwen baseline.
- **Stage 6.4 — ablation optimization (after alignment):** from the aligned WJ-qwen baseline,
  ablate one axis at a time on the benchmark (semantic on/off *with* step-down present,
  step-down on/off, generation knobs, WhisperSeg params, and whether AssemblyTextCleaner beats
  our `finalize_qwen_entries`) to find our best qwen config. Only then consider deviating from
  strict WJ parity. None of these are package-blocked; anime remains the project default ASR line.

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

Current repository validation after the anime/WhisperSeg/semantic/config-split and
Stage 6.3 qwen benchmark/default changes:

```bash
python -m pytest tests -q
python -m compileall -q scripts tests
git diff --check
```

Latest observed result:

```text
270 passed
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
- quality report
