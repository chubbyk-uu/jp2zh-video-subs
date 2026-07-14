---
name: review-bilingual-ass
description: Review and correct this project's Chinese/Japanese bilingual ASS subtitles from one primary ASS file, using full-document context to fix high-confidence Japanese ASR errors, Chinese mistranslations, names, titles, and terminology while preserving ASS structure and timing. Use for requests to 审校、校对、修正、检查 or compare `.ass` subtitle files produced by jp2zh-video-subs. A second ASR/ASS is optional supporting evidence, never a prerequisite.
---

# Review Bilingual ASS

Produce a conservative, publishable correction pass over one bilingual ASS. Treat an alternate ASR as optional evidence only.

## Inputs and outputs

Require one primary `.ass` path. Accept an optional alternate ASS for the same video when available.

Never overwrite the input. Default to:

- `<stem>.reviewed.zh.ass`
- `<stem>.review-report.md`
- `<common-stem>.asr-comparison.md` only when comparing versions

Keep reports beside the requested output unless the user says otherwise.

## Workflow

1. Inspect the primary file with `scripts/ass_review.py inspect <file>`.
2. Extract a numbered bilingual review sheet with `scripts/ass_review.py sheet <file> --markdown`. Read every `Dialogue` event in chronological order. Use chunks only for manageability; do not review a sample and extrapolate.
3. Run two independent all-event discovery sweeps before deciding any correction:
   - **Japanese surface sweep:** ignore the Chinese long enough to ask whether every Japanese cue parses as spoken Japanese. Mark broken word boundaries, impossible vocabulary, dialect mistaken for standard Japanese, malformed inflections, and homophone-like chunks as suspects.
   - **Bilingual direction sweep:** compare Japanese and Chinese for polarity, subject, agency, tense, quantity, referents, and action state. Mark fluent Chinese that merely rationalizes malformed Japanese as suspect.
   Discovery must be broad. The conservative evidence threshold controls whether a suspect is edited, not whether it enters the suspect list.
4. Keep a coverage ledger for each sequential chunk. Record its event range and the event numbers marked by the surface sweep, bilingual sweep, or both. Explicitly write `none` when a sweep finds no suspect. The ranges must cover every event exactly once.
5. Build a working glossary of characters, names, titles, relationships, organizations, dialect forms, and recurring terms. Recheck earlier chunks when later context establishes a term.
6. Read `references/review-rubric.md` and apply its evidence hierarchy and correction threshold.
7. Review the primary ASS on its own first:
   - Use Japanese as the main source text.
   - Use Chinese as a clue, not ground truth.
   - Resolve lines using the full story, adjacent replies, grammar, collocations, and established terminology.
   - Run a separate contradiction pass over question/answer and cause/effect chains. A fluent translation can still be wrong.
8. Before creating or editing the reviewed copy, replay the first and last 15 events plus the first and last 3 events of every reading chunk with the full glossary and story context. Opening cues lack preceding context and chunk edges are common omission points.
9. Freeze a candidate ledger. Every suspect from either discovery sweep must end as `confirmed change` or `unresolved`; it may return to `unchanged clear` only with a short reason. For every confirmed change, record the raw text, proposal, source-form clue, why the original fails in context, contextual support, and plausible alternatives. Follow `references/review-rubric.md` exactly.
10. If an alternate ASS exists, align it by time and use it as additional evidence. Do not bulk-copy it and do not weaken the single-ASS workflow.
11. Create the reviewed copy only after the candidate ledger is frozen. Edit only the tenth ASS `Dialogue` field (`Text`). Preserve headers, styles, event count, order, start/end times, layer, name, margins, effect, inline tags, and `\N{\rJA}` bilingual structure.
12. Apply one final decision per event. Do not iteratively rewrite a cue in the reviewed file while reasoning. If a decision is reopened, return to the pristine original and replace its ledger entry before making the single final edit.
13. Run `scripts/ass_review.py diff` and re-prove every changed event against the original plus neighboring cues. Revert any entry whose ledger cannot explain both the candidate and why the original reading fails.
14. Run a second complete pass over **unchanged events only**, using the final glossary and narrative context. This is a miss-detection pass, not a style pass. Any new suspect must return to the original cue and enter the ledger before editing.
15. Write a report containing scope, count, complete confirmed changes, glossary, unresolved audio-dependent doubts, coverage ranges, per-chunk suspect event numbers, and validation results. Reconcile `total events = changed + unresolved + unchanged clear`; do not claim completion if coverage is unaccounted for.
16. Run `scripts/ass_review.py validate <original> <reviewed>`. Also run `ffprobe` when available.
17. If comparing versions, report both absolute confirmed-error counts and per-event rates. Discuss segmentation, coverage, obvious fragments, and fluent hallucinations separately.

## Editing rules

- Correct only high-confidence errors. Preserve natural spoken language and explicit content.
- Prefer a local targeted change over rewriting a whole cue.
- Do not invent missing dialogue, normalize personalities, sanitize language, or polish acceptable phrasing.
- Contextual inference is allowed. Do not replace text merely because another wording sounds nicer or more typical.
- For an inferred ASR correction, show a concrete case: the candidate must plausibly account for the raw sound/text, make a specific nearby exchange or narrative fact coherent, and leave no equally plausible reading in the available evidence. Explain why the original reading fails; thematic expectation alone is not enough.
- When the Japanese and Chinese agree on an odd reading, treat them as one ASR-derived signal, not two independent confirmations. Still correct it if the original causes a concrete contradiction and the proposed reading explains it better.
- Treat names and semantic minimal pairs as high-risk. Check nearby responses explicitly; for example, a later answer using `振った` is evidence that `降られた` should be `振られた`, not rain.
- When evidence is insufficient, leave the cue unchanged and record it as unresolved.
- Check direction-sensitive details before finalizing: negation, tense, agency, comparison, and whether an action has begun, ended, or is merely possible. Do not convert `勃ってきた` into `勃ってない`, or the reverse, without returning to the original raw form and the ledger.
- Keep the original checksum in the report or final validation output so accidental overwrite is detectable.

## Deterministic helper

Use the bundled script instead of rewriting ASS parsing and comparison snippets:

```bash
python .agents/skills/review-bilingual-ass/scripts/ass_review.py inspect input.ass
python .agents/skills/review-bilingual-ass/scripts/ass_review.py sheet input.ass --markdown
python .agents/skills/review-bilingual-ass/scripts/ass_review.py diff input.ass input.reviewed.ass --markdown
python .agents/skills/review-bilingual-ass/scripts/ass_review.py validate input.ass input.reviewed.ass
```

`validate` must pass before claiming completion. A failed structural check is a blocker for delivery, not a report-only warning.

## Final response

Link the reviewed ASS and report. State the event count, confirmed changed-event count, whether an alternate ASR was used, validation result, and that the original was untouched. For comparisons, give the practical recommendation without treating event count alone as quality.
