# Project Quality Improvement Plan

Last updated: 2026-07-14

## Project Objective

This is the project-level plan. The primary goal is to produce readable Japanese-to-Chinese
ASS subtitles whose **Japanese source text is materially more accurate** on JAV/anime-style
audio. Timing stability, cue readability, translation, and formatting remain required output
qualities, but they cannot compensate for an ASR mishearing the source dialogue.

The project now has two usable ASR lines with different strengths:

- **Anime (default):** better weak-speech recall and VAD-only timing that avoids forced-aligner
  collapse, but still makes acoustic misrecognitions in breathy, noisy, overlapping, or
  dialectal speech.
- **Qwen (comparison line):** cleaner in some ordinary dialogue, with bounded aligner
  drift/collapse recovery, but short WhisperSeg frames can lose linguistic context and it
  has its own weak-speech and hallucination trade-offs.

The former anime migration work is complete enough to keep Anime as the default. Its detailed
implementation record remains below because it explains the current baseline. Future work is
not "make Anime resemble WhisperJAV"; it is evidence-driven improvement of source-text
correctness across both ASR lines.

## Quality Priorities

1. Improve Japanese recognition correctness and weak-speech recall.
2. Preserve the current no-overlap, low-drift, no-collapse timing behavior.
3. Preserve readable cue shaping and faithful Chinese translation.
4. Do not replace a stable default based on cue counts, text length, or one-off subjective
   examples alone.

## Current Baseline

The normal video pipeline now uses the WJ-derived Anime framing path. Anime and Qwen retain
separate configuration surfaces so experiments on one line do not silently change the other.
The existing quality report is a structural regression guard (coverage, timing, duplicates,
residue); it is not an ASR semantic-accuracy judge.

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
  -> WhisperSeg
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

### 5. Forced-WhisperSeg boundary sentence breaks (implemented)

The project can now identify why a WhisperSeg frame ended. `SpeechSegment` records its
end cause, grouped frames carry left/right boundary provenance, `ChunkJob` preserves it,
and raw dumps expose `left_boundary_reason` / `right_boundary_reason`. The relevant causes
include `forced_max_speech`, `forced_max_group`, `silence_gap`, semantic-scene edges, and
audio ends. This observability does not alter recognition, cue shaping, or timing output.

The local evaluation video `E:\迅雷下载\新建文件夹\hhd800.com@DLDSS-492.mp4` exposes a
concrete unresolved failure around 00:00:50--01:00. In the semantic-scene processing window,
WhisperSeg produced the following adjacent anime/Qwen frame boundaries:

```text
50.574--55.634  right_boundary_reason=forced_max_speech
55.634--60.794  left_boundary_reason=forced_max_speech, right_boundary_reason=forced_max_speech
60.794--63.678  left_boundary_reason=forced_max_speech
```

At the first boundary, both ASR lines can emit the spoken sentence as two independent
texts: `何事も挑戦。` followed by `だよ。`. The Japanese source is therefore fragmented, and
the isolated second fragment can translate incorrectly (for example as a standalone
Chinese acknowledgement) even though the intended sentence is `何事も挑戦だよ。`.

This is not a generic cue-shaping or translation-only defect: the boundary metadata proves
that WhisperSeg cut continuous speech at its configured duration limit. The fix is now at the
VAD source, rather than a post-ASR repair: `whisperseg_max_speech=5.0` is a soft target,
`whisperseg_soft_split_lookback=1.0` extends the search to 4 seconds, and
`whisperseg_hard_max_speech=8.0` bounds each natural speech run. Phase one uses only smoothed
WhisperSeg probabilities: valley depth/prominence, width, target distance, and a soft penalty
for leaving a tail under one second. RMS/energy remains deliberately deferred.

A qualified valley is recorded as `soft_max_valley`; otherwise the best bounded relative
valley is `hard_max_valley`, with `hard_max_speech` reserved for an invalid last-resort cap.
When `hard_max <= soft_target`, the original immediate-cut state machine and exact
`forced_max_speech` reason are retained for reproducible A/B.

The DLDSS expectation must follow the actual no-cap VAD result, not infer continuity from
the current forced-cut labels. A local probe using the same semantic-scene input produced:

```text
max_speech=5.0:
50.574--55.634  forced_max_speech
55.634--60.794  forced_max_speech
60.794--63.678  silence

max_speech=99.0:
50.574--60.794  silence
60.794--63.678  silence
```

Thus `60.794` is a natural silence boundary that the old force-cut branch masked. The current
implementation selected a weak-probability valley at `56.694`, yielding:

```text
50.574--56.694  soft_max_valley
56.694--60.794  silence
60.794--63.678
```

The new algorithm does not imply a 50.574--63.678 13.1s job. All strong-cut reasons propagate
through `SpeechSegment`, `SpeechGroup`, `ChunkJob`, and raw dumps. Main framing and
quality-report WhisperSeg use the same soft/hard/lookback configuration; step-down stays
tighter by using `min(main_hard_max, stepdown_fallback_group)`. Semantic-scene padding is still
only VAD input context, never extra final-ASR padding; Anime remains VAD-only and Qwen keeps its
existing aligner/fallback path.

Validation passed synthetic legacy/valley/padding/reason tests, a DLDSS local VAD A/B, and a
20.764-second end-to-end Anime/Qwen run. Both E2E outputs recognized `何事も挑戦だよ` as one
ASR text window, with five final jobs and no job overlap in that scene. A separate 24-minute
Anime framing run completed with 239 jobs and active `soft_max_valley`/`hard_max_valley`
reasons. Adjacent semantic scenes intentionally have overlapping VAD input windows, so job
audio spans can overlap across those scenes; final cue ownership and final subtitle entries,
not those input windows, are the no-overlap contract.

### 6. Local LLM subtitle review pipeline (planned, not implemented)

Target implementation session: 2026-07-14.

The next quality experiment is an auditable local-LLM review stage after ASR. Its purpose is
to correct high-confidence context and consistency errors that acoustic decoding alone cannot
resolve. It is not expected to recover inaudible or completely omitted speech, and uncertain
acoustic cases must remain unchanged with `requires_audio_check=true`.

Planned data flow:

```text
raw Japanese ASR
  -> full-transcript glossary extraction
  -> windowed Japanese proposal + independent verification
  -> corrected Japanese
  -> Chinese translation from corrected Japanese only
  -> bilingual consistency review
  -> final bilingual ASS
```

Default local service for the experiment:

```text
base_url = http://127.0.0.1:11434/v1
model = qwen3.5:9b
temperature = 0.1
```

Before implementation, verify that the Ollama OpenAI-compatible endpoint is reachable from
WSL and that the model is installed. This is currently an unverified prerequisite: the local
probe did not find an `ollama` command or a responding service at that address. A Windows-host
Ollama instance may require a WSL-reachable host address instead of loopback.

#### Stage A: Japanese review

1. Parse the original Japanese SRT through the existing subtitle structures. Assign stable
   IDs such as `seg-000001`, independent of the SRT display index, and retain the timestamp,
   exact original text, settings, and original subtitle block.
2. Extract people, name variants, places, jobs, forms of address, and domain terms without
   changing subtitles. Process bounded chunks (roughly 150-250 cues), then consolidate them
   into `glossary.json` entries containing `type`, `canonical_ja`, `variants`, `preferred_zh`,
   `evidence_ids`, and `confidence`.
3. Review owned cores of about 40 cues with 8-12 read-only context cues on each side and the
   consolidated glossary. Check inconsistent names/terms, clear homophone errors, contextual
   contradictions, cross-cue sentence breaks, and clearly ungrammatical Japanese. Do not
   polish style, remove oral language, sanitize adult content, or invent unheard information.
4. Save proposal patches with `segment_id`, `original_ja`, `replacement_ja`, `category`,
   `confidence`, `evidence_ids`, `reason`, and `requires_audio_check`. Only core cues may be
   proposed by a window, preventing duplicate ownership in overlapping context.
5. Validate every proposal in a separate blind request. The validator sees the source,
   replacement, evidence, context, and glossary, but not the proposer's reason or confidence.
   Using the same model does not make the checks independent, so conservative hard gates are
   required.

Automatic application requires all of the following:

- proposer and validator confidence are both at least 0.90;
- `requires_audio_check` is false;
- `original_ja` exactly matches the current cue, without normalization;
- replacement is non-empty, different, and within a conservative edit-distance bound;
- every evidence ID exists and proposals do not conflict;
- numbers, negation, and person/relationship semantics are unchanged.

Changes involving numbers, negation, people/relationships, conflicting patches, or excessive
rewrites remain report-only even when the model is confident. Cross-cue redistribution also
remains report-only until atomic grouped patches are implemented with a `patch_group_id`; a
group must apply completely or not at all.

Outputs:

- `raw.ja.srt`
- `corrected.ja.srt`
- `glossary.json`
- `ja_patches_proposed.json`
- `ja_patches_verified.json`
- `ja_review_report.md`

#### Stage B: translation from corrected Japanese

Translation must use `corrected.ja.srt` as its only Japanese subtitle input and record that
file's hash in the stage manifest. It receives neighbouring context and the glossary for
consistent names, jobs, forms of address, and terminology, and writes `translated.zh.srt`.

The requested Ollama translation path must be benchmarked against the existing GalTransl
backend before replacing the production default. A general 9B model may sanitize adult
content, refuse, over-shorten, or invent text; prompts and validation must explicitly reject
those behaviours. The review pipeline should therefore use a translation-backend adapter
rather than silently changing the existing default.

#### Stage C: bilingual review and final ASS

Review `corrected.ja.srt`, `translated.zh.srt`, and `glossary.json` for source/target mismatch,
omission, reversal, invention, inconsistent terminology, and errors in negation, numbers, or
speaker/subject. This stage normally patches Chinese only. A clear Japanese error produces a
separate report-only Japanese candidate and marks affected Chinese cues for retranslation.

Save `bilingual_patches.json`, then reuse the existing ASS writer to create
`final.bilingual.ass`. The final report must list every accepted, rejected, uncertain, and
audio-check candidate. Before implementation, resolve one audit ambiguity: either add a
recommended `final.zh.srt`, or define `translated.zh.srt` as the post-review final Chinese and
retain its pre-review value only in request logs. The final ASS must never contain Chinese
changes that have no inspectable SRT or patch representation.

Planned per-video output directory:

```text
output/<video-stem>/
|-- raw.ja.srt
|-- corrected.ja.srt
|-- translated.zh.srt
|-- final.bilingual.ass
|-- glossary.json
|-- ja_patches_proposed.json
|-- ja_patches_verified.json
|-- bilingual_patches.json
|-- ja_review_report.md
`-- final_review_report.md
```

All prompts and raw responses belong under
`work/<video-stem>/llm_review/requests/`, not in the final output directory.

#### Reliability and implementation order

Reuse `translation_common.Entry` and the existing SRT/ASS code. Add isolated review modules
instead of refactoring ASR internals: a shared OpenAI-compatible client/schema/cache layer,
Japanese reviewer, corrected-Japanese translator adapter, bilingual reviewer, and finally
top-level orchestration in `video_to_zh_srt.py`.

Implement in this order:

1. Define versioned schemas, stage manifests, exact timeline invariants, and tests.
2. Add the Ollama client with bounded retry, JSON parse/schema retry, request/response logs,
   and content-addressed cache.
3. Implement glossary map/consolidate and Japanese proposal/verification/application.
4. Route translation exclusively from corrected Japanese and add the backend A/B gate.
5. Implement Chinese-first bilingual review, final ASS output, resume, and a short E2E test.

Resume must not rely on output existence or cue count alone. Each stage manifest records
input SHA-256, model, temperature, prompt/schema versions, glossary hash, and output hash;
changes to any of them invalidate that stage and its dependants.

Acceptance criteria:

- cue count, SRT indices, and every timestamp remain byte-for-byte equivalent through review;
- no patch applies when its exact original text no longer matches;
- no automatic number, negation, or person/relationship change occurs;
- grouped cross-cue patches are atomic or report-only;
- translation provenance proves it read `corrected.ja.srt`;
- malformed JSON, transient request failures, cache invalidation, proposal conflicts, and
  resume behaviour are covered by tests;
- final ASS timestamps match the corrected Japanese timeline exactly;
- manual precision of automatically applied Japanese patches reaches at least 95% on the
  initial evaluation sample before the feature is enabled by default.

## Historical Implementation Record

### Completed qwen context experiment

Current qwen default intentionally uses short WhisperSeg frames. That fixed the original
collapse/drift failure mode, but it also means most clips are only about 5-6 seconds long.
The shorter context appears to hurt Qwen text recognition compared with longer segments,
even though timing is cleaner.

Stage 6.5 implemented **long-context recognition with short-anchor timing** as an
experiment. The current retained experiment is qwen-only `merge`; the older `pad`
mode was removed because it added extra per-frame context expansion and polluted
recognition in tests. Note: `scene_asr_pad_seconds=0.35` is only the semantic scene
`asr_processing` window expansion used before WhisperSeg detects frames. It does not
expand any final Qwen recognition job, whether the context mode is `none` or `merge`.
The key
constraint is to decouple the audio span Qwen hears from the cue ownership span used for
timing and dedup:

- Recognition span: a longer merged audio window fed to Qwen for better text.
- Ownership span: the original WhisperSeg frame(s) whose cue centers this job may emit.
- Timing source: forced aligner when healthy; VAD-guided fallback when the sentinel marks
  collapse. The fallback must use the owned speech regions, not the entire padded context.

Implementation plan:

1. Add a qwen-only WhisperSeg context mode. **Implemented.** It was briefly enabled as
   the Qwen default during Stage 6.5, then disabled by default after Stage 6.7 testing
   showed longer merged windows increased Qwen hallucination and tail drift.
   - `--qwen-whisperseg-context-mode none|merge` (current Qwen default: `none`).
   - `merge`: merge adjacent WhisperSeg groups. Below `target_seconds` the merge tolerance
     is `merge_gap`; **once a group passes the soft target the tolerance tightens to
     `after_target_gap`** (default 0.2s), so the group ends at the next real pause instead
     of greedily merging until `hard_max_seconds` forces a mid-speech cut. `hard_max_seconds`
     is the true safety cap and only bounds genuinely gap-free speech. Retain the original
     component speech regions inside the merged clip.
   - `merge` ignores the legacy pre/post and ratio pad knobs. It joins adjacent component
     frame bounds exactly from the first frame start to the last frame end; it does not add
     `scene_asr_pad_seconds` to either edge. This prevents non-owned boundary speech from
     leaking into the merged recognition job.
2. Extend `ChunkJob` only as much as needed:
   - keep `start/end` as the recognition audio slice.
   - keep `keep_lo/keep_hi` as the cue ownership window.
   - keep `speech` as clip-relative owned speech regions for sentinel fallback.
   - if merge needs debugability, add metadata such as component frame ranges to raw dumps,
     not to cue shaping logic.
3. Build jobs in two layers:
   - First run WhisperSeg exactly as today to get atomic frames.
   - Then apply optional qwen context merge to create recognition jobs.
   - The first benchmark isolated context length; current Qwen defaults use semantic scene
     with context mode `none`.
4. Preserve collapse/drift protection:
   - For `aligner_fallback`, assess aligner items against the full recognition clip.
   - On collapse, redistribute words over the owned `speech` regions only.
   - Filter emitted cues by `keep_lo/keep_hi` so neighboring merged jobs cannot duplicate
     cues or claim text across their ownership boundary.
5. Benchmark candidates before changing defaults: **done on the primary long-form
   evaluation clip; merge was later rejected as the current default after manual review.**
   - baseline: previous qwen default (`context-mode none`, 6.0/1.0).
   - merge: e.g. soft target 12s, 18s, 24s with a small max inter-frame gap and a hard
     cap around 32-36s.
   - earlier merge + extra pad candidates were rejected; that pad mode has since been
     removed. Current merge uses exact component-frame bounds.
   - optional diagnostic only: `vad_only` timing to separate text-window effects from
     forced-aligner effects. Follow-up A/B showed that `vad_only + merge` can repeat
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
  near-duplicate filters, hallucination gates, and common postprocess
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
  | qwen_fixed_tiling | 77.4% (367/474) | 8.8% (18/205) | cues=923 short=12 long=0 ov=0 |
  | qwen_fixed_recovery | 77.6% (368/474) | 9.3% (19/205) | cues=941 short=9 long=0 ov=0 |
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
  | qwen_fixed_tiling | 66.4% | 10.9% | 923 | 12 | 0 | 0 |
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
  WhisperSeg context `merge` mode, original-frame cue ownership, aligner timing when
  healthy, and VAD-guided fallback over owned speech regions when collapsed. The removed
  `pad` mode is intentionally not selectable.

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
  hard_max=35`.

  Full-pipeline re-run on the same primary long-form clip with the selected experiment
  (`--asr qwen`, galtransl):
  887 cues, 9 short (<0.5s), **0 overlaps, 0 same-start piles, 0 cues >8s**, `hard_cuts=0` —
  the framing change lands clean on the timeline.

  Note on the earlier tuning table (removed): those rows varied `target` alongside `gap`
  while `target` was still inert, so any effect attributed to `target` actually came from
  `gap`/`hard_max`. The automatic quality report is a regression guard, not the final judge;
  The legacy ratio/pre/post padding controls were later removed from the CLI because they
  no longer affected either context mode.

  All active `whisperseg_context_*` getattr fallbacks in `transcribe_ja_srt_qwen.py` were aligned to
  the dataclass defaults to avoid phantom defaults on from-raw/test paths.
  Later manual subtitle review rejected merge as the Qwen default because the longer
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

## Stage 7: Anime line follow-up (completed)

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
clip while retaining project output hygiene (no final overlaps). VAD-only remains the default,
but the forced-align path is now a production candidate rather than diagnostic-only; the
remaining gates are recorded below.

### Planned Anime forced-align default evaluation

Status: cue shaping implemented and validated on one long-form video; default switch blocked
on text-preservation fixes, scene-boundary reconciliation, and multi-video review.

Anime forced-align now treats anime-whisper source punctuation as authoritative. Pure aligner
character gaps no longer create cue boundaries inside one source unit; hard sentence endings
(`。？！?!`), original WhisperSeg frame boundaries, and the 80-character / 8-second safety caps
remain valid boundaries. This removed grammatical tail fragments such as standalone `か?`,
`です…`, and `ましょう…` without changing Anime VAD-only or Qwen shaping.

On the 137-minute local MIDV-890 evaluation video, the revised path changed the Japanese cue
count from 434 to 370 (VAD-only: 333). Forced-align cues under one second fell from 114 to 55,
and cues over six seconds fell to 12 (VAD-only: 69). Its final Chinese ASS had no overlaps,
16 cues under 1.5 seconds, and 21 cues over six seconds. Seven collapsed alignments were all
recovered through the existing VAD fallback. This is enough to keep testing the path, but not
enough to replace the default from one title.

The remaining 21 normalized Japanese characters of difference from VAD-only have three
distinct causes:

1. **Eight characters are over-aggressive shared filler collapse.** Anime forced-align and
   Qwen both enter `collapse_filler_repetitions`; Anime VAD-only does not. Normal double
   repetitions such as `ふふっ`, `ああ`, and `ねえねえ` can therefore lose real laughter,
   vocalization, or emphasis. Two repetitions should remain; any revised collapse rule must
   be conservative and regression-tested on both aligned backends.
2. **Ten characters are duplicated semantic-scene boundary text.** Adjacent padded scene
   windows independently detected and recognized overlapping speech (`エロい…エロいって`,
   and a partial `すっごい、おちん` before the complete next cue). Forced-align ownership
   removed those partial duplicates; VAD-only retained them. These characters must not be
   restored. The shared canonical-frame reconciliation below is the source-level fix.
3. **Three characters expose a real ownership-order bug.** The forced aligner returned valid
   timestamps for short `もぐ` and `ぁ` cues, but `min_duration=0.8` expanded their display
   spans before ownership was tested. The expanded centers moved beyond `keep_hi`, so valid
   cues were discarded. Ownership must use the raw aligned span, then apply the display floor.

Implementation order, deliberately one behavior change at a time:

1. Fix aligned-cue ownership to claim with the raw aligner span and apply `min_duration` only
   after ownership. Cover short cues at a frame end and preserve Qwen behavior.
2. Make shared filler collapse conservative: retain normal double repetition, collapse only
   sufficiently strong filler-loop evidence, and A/B both Qwen and Anime forced-align.
3. Implement the planned semantic-scene boundary reconciliation below so all backends receive
   one canonical WhisperSeg frame set while retaining one-sided weak-speech detections.
4. Re-run MIDV-890 VAD-only and forced-align. Require no unexplained source-text loss, no
   duplicate boundary cues, no overlap, and no regression in short-cue/readability metrics.
5. Run the same A/B on at least two additional videos with different dialogue density and weak
   speech. Switch the Anime default only if manual playback confirms a net timing/readability
   gain without source-text or translation regression.

## Stage 8: Qwen line follow-up (historical baseline)

At the time of this stage, Qwen was the next optimization target. Its current default keeps semantic scene on but
uses short scene-padded WhisperSeg frames directly (`--qwen-whisperseg-context-mode none`),
because longer merged context windows increased Qwen hallucination and tail drift in current
tests. Cue regrouping is WJ-derived: adjacent cues inside one clip merge
only when the pause is under WJ's 1.5 seconds and the combined cue stays within 80 content
characters / 8 seconds.

The checks below are retained as historical context. Any future Qwen work must serve the
project-level source-text-correctness goal above rather than re-open old experiments by default:

1. Re-run the current Qwen default against the same anonymized evaluation set used for anime
   parity. Compare against both the old Qwen baseline and the stable anime default.
2. Separate failures by cause: scene boundary, WhisperSeg frame boundary, context merge
   length, forced-aligner recovery, and translation-only ambiguity.
3. Keep semantic scene on while testing whether Qwen needs selective context-merge
   experiments for specific failure classes; the legacy `pad` mode has been removed. Do not
   re-enable merge by default without
   evidence that hallucination does not regress.
4. Qwen recapture has been removed. Recent manual review did not show clear value from the
   second ASR pass; future Qwen recall work should target WhisperSeg / scene framing and
   recognition quality instead.
5. HY-MT translation and the legacy Whisper ASR path have been removed. The remaining
   supported ASR lines are anime and Qwen, both using the shared Qwen/anime sub-script
   with WhisperSeg framing.
6. Prefer WJ-derived Qwen mechanisms first; add new project-specific logic only when WJ-like
   changes cannot explain the miss.

### Planned semantic-scene boundary reconciliation

The current semantic path runs WhisperSeg independently on overlapping padded scene
processing windows (`strict scene ± scene_asr_pad_seconds`). A weak boundary utterance can
therefore be detected by both scenes with slightly different bounds, or only by the
neighbouring scene whose strict interval does not own its center. Simple center-based
ownership is unsafe because it can discard a one-sided weak-speech detection.

Planned implementation, after a focused boundary audit:

1. Preserve the padded scene windows for WhisperSeg input; do not hard-clip the audio before
   detection.
2. Collect all scene-relative WhisperSeg groups as absolute-time candidates before creating
   `ChunkJob` objects.
3. Keep candidates far from a scene boundary unchanged. Around each overlap band, reconcile
   candidates from both adjacent scenes: union materially overlapping speech intervals,
   retain one-sided intervals, and regroup complementary fragments with the backend's existing
   `chunk_threshold` / `max_group` rules.
4. Emit one canonical set of boundary frames for both anime and Qwen. Recognition audio may
   retain useful boundary context, while the canonical frame set prevents duplicate ASR jobs.
5. Add tests for duplicate detections, complementary partial fragments, a one-sided weak
   detection, and a real silence that must remain a frame boundary.

Do not implement center-only scene ownership as the final solution. Success means no lost
one-sided weak speech, no duplicate boundary cue, and unchanged non-boundary framing.

## Planned: Windows CUDA GUI portable distribution

Status: approved future objective; implementation has not started.

The desired release is a Windows x64 **portable folder** with a desktop GUI. A user should
be able to unzip the folder and launch the application without separately installing Python,
FFmpeg, or project Python packages. It must retain CUDA acceleration for the supported NVIDIA
GPU stack. This is deliberately a folder distribution, not a single self-extracting executable:
the runtime, CUDA-related DLLs, and models are too large and too dynamically loaded for a
single-file package to be a good first target.

The first GUI release is a batch subtitle-generation application, not a video player or
timeline/subtitle editor. Its user-facing scope is:

- drag/drop one or more videos or a directory;
- select the normal Anime/Qwen ASR and GalTransl/Sakura translation presets;
- select output/work locations and common options such as bilingual ASS, resume, and quality
  report;
- show live per-job stage, log output, failure, cancellation, retry, and links to results;
- diagnose required models, FFmpeg, available CUDA providers/GPU, disk space, and common
  configuration errors before a long job starts.

The intended portable layout is:

```text
jp2zh-video-subs/
  launch.bat or launcher.exe
  runtime/       embedded Python and pinned package runtime
  app/           project scripts and GUI
  bin/ffmpeg.exe
  models/        separately managed local model files
  config/
  outputs/
  work/
```

NVIDIA display drivers remain a machine prerequisite and are not bundled. The exact supported
Windows version, driver floor, Python version, CUDA/Torch wheel set, ONNX Runtime provider,
and CUDA build of `llama-cpp-python` must be fixed and validated on native Windows before a
release is claimed to support CUDA.

Model weights are not part of the basic program archive. They should be distributed as
separate optional archives (default Anime + WhisperSeg + GalTransl, optional Qwen/aligner,
optional Sakura-14B), with a model manifest that checks required paths, sizes, and hashes.
This avoids forcing every user to download every backend and reflects the current model
footprint: the local `models/` directory is approximately 23 GB when all supported models are
present.

### Implementation order

1. **Define the Windows support contract.** Choose Windows x64 versions and a tested NVIDIA
   driver/CUDA compatibility baseline. Create a reproducible native-Windows environment
   specification with pinned Python and GPU packages. Do not claim generic CUDA compatibility.
2. **Add a GUI-facing pipeline contract.** Keep the CLI as a supported interface. Add
   structured stage/progress/error events and cooperative cancellation around the existing
   extraction, ASR, translation, ASS, and report stages. Preserve the current subprocess
   boundary between ASR and translation so their GPU memory is not intentionally concurrent.
3. **Implement the GUI in the existing WSL development workflow.** Use a desktop toolkit
   (PySide6 is the current candidate) and drive the existing pipeline rather than duplicate its
   ASR/translation logic. Make project-root resolution work from a source checkout and from the
   portable folder.
4. **Add preflight and model management.** Implement the runtime/model/FFmpeg/CUDA checks,
   user-readable remediation messages, and model manifest/import/download workflow. The GUI
   must fail clearly when a model or CUDA provider is unavailable rather than silently using an
   unintended backend.
5. **Assemble a development portable folder on native Windows.** Bundle FFmpeg and an embedded
   Python runtime with the pinned dependencies. Start with `launch.bat`; only add a thin
   launcher executable later if it materially improves usability. Do not start with a
   PyInstaller single-file executable.
6. **Run native Windows GPU validation.** On a clean unpacked folder, test the default Anime
   path, Qwen comparison path, both translators, batch/resume/cancel behavior, missing-model
   handling, and GPU/provider diagnostics. At least one additional NVIDIA GPU/driver
   combination should be tested before public release.
7. **Publish separated archives and release instructions.** Ship the program package and
   model packages separately, document supported hardware/driver expectations, and retain a
   reproducible build script for later releases.

### Development-environment constraint

Most implementation work should remain in the current WSL/Linux checkout. Native Windows is
required only for dependency assembly and final CUDA/portable-folder verification; WSL, Wine,
and CPU-only CI cannot establish that the Windows CUDA DLL/provider combination works. The
first task when this work begins is therefore the GUI-facing pipeline contract, not a Windows
environment migration.

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

## Deferred Or Rejected By Default

- NVV moan classifier. It is not yet tied to a demonstrated source-text accuracy gain.
- Whisper hallucination JSON vocabulary. WhisperJAV anime does not rely on it; this project
  currently retains only the conservative anime cleaner.
- Full-film ensemble / smart merge. Timestamp coverage and text length are not semantic
  correctness signals; reconsider only after a calibrated candidate selector exists.
- GUI integration.
- A full benchmark-framework migration. Future evaluation work should begin with a small,
  maintainable manually verified corpus rather than new benchmark infrastructure.
- Prompt/context injection into anime-whisper. The current model path intentionally ignores
  textual context; audio-window experiments remain possible when separately justified.

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
- `docs/PLAN.md`

Preserved project output chain:

- `chunk_entries`
- `sentences_from_alignment`
- `finalize_qwen_entries`
- overlap / near-duplicate / filler filters
- translation pipeline
- ASS generation
- optional quality report
