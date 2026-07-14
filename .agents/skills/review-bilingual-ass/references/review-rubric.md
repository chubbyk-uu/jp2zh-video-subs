# Bilingual ASS review rubric

## Evidence priority

Use evidence in this order:

1. Narrative continuity and adjacent question/answer or cause/effect pairs.
2. Established character names, relationships, titles, and recurring terminology from the full ASS.
3. Japanese grammar, conjugation, particles, collocations, and discourse conventions.
4. Agreement between Japanese and Chinese when both independently make sense.
5. An optional alternate ASR aligned to the same time span.
6. Plausibility based only on sound similarity.

Levels 1–4 are sufficient for a single-ASR review. Level 5 strengthens a decision but is never required. Level 6 alone is not sufficient to edit.

## Discovery threshold versus correction threshold

Keep these thresholds separate:

- **Discovery threshold:** low. Mark any cue whose Japanese does not parse, whose Chinese has to invent a meaning, whose polarity or referent may be reversed, or whose word boundaries resemble a plausible ASR merge.
- **Correction threshold:** high. Edit only after the evidence case below is satisfied.

Do not use “be conservative” to suppress suspects. A false-positive suspect can be resolved as unchanged; an unmarked cue bypasses every later safeguard.

For every sequential reading chunk, record:

| Field | Required content |
|---|---|
| Range | Inclusive event range, covering the file once with no gaps or overlaps. |
| Surface suspects | Event numbers whose Japanese vocabulary, grammar, dialect, or segmentation is questionable; write `none` explicitly when empty. |
| Direction suspects | Event numbers with possible Chinese/Japanese polarity, subject, agency, tense, quantity, referent, or action-state mismatch. |
| Context suspects | Event numbers added after later story or glossary evidence became available. |
| Final disposition | Counts of confirmed, unresolved, and unchanged-clear suspects. |

The chunk ledger proves discovery coverage; the evidence ledger proves correction quality. Both are required.

## Evidence case: required before editing

For every proposed text change, write these six short fields before touching the reviewed copy:

| Field | Required content |
|---|---|
| Raw | Exact original Japanese and Chinese text. |
| Proposal | Exact replacement Japanese and Chinese text. |
| Source trace | Which raw syllables, characters, OCR-like substitutions, or word boundary support the proposal. Exact transcription is not required, but the candidate must not be unrelated to the raw form. |
| Original failure | The concrete contradiction, impossible meaning, broken grammar, or missing antecedent caused by the original reading. “The proposal sounds more natural” is insufficient. |
| Context | The preceding/following cue, established term, or plot fact that resolves the ambiguity. |
| Alternatives | At least one plausible competing reading, or an explicit statement that none remains. Do not edit if a competing reading remains equally plausible. |

Context is valid evidence and may support a reasonable reconstruction. It cannot be used as a license to write a preferred new line without explaining the raw form and why the existing reading fails.

## Confirmed correction threshold

Edit literal defects when at least one strong condition holds:

- A nearby reply uniquely determines the intended word or action.
- A name/title has already been established and the current form is a clear homophone or OCR-like error.
- The Japanese is ungrammatical and one minimal correction restores a standard construction that fits the scene.
- The Chinese introduces a person, object, action, or plot fact absent from the Japanese and context.
- The text contains corrupted Unicode, non-Japanese intrusions in the Japanese line, or an impossible term with a uniquely supported replacement.
- Multiple independent signals agree, including an optional alternate ASR.

Edit inferential ASR corrections only when the evidence case shows all of the following:

1. The proposal has a plausible source trace in the raw text.
2. The original creates a concrete failure, not merely an unusual scene or awkward wording.
3. The proposal resolves that failure through adjacent dialogue, a stable glossary item, grammar, or a specific narrative fact.
4. No equally plausible candidate remains in the available evidence.

For example, an apparent `バスター` may be corrected to `バイト` only when the surrounding exchange establishes a current work shift and no action, person, or object can support “buster/explosion”; record that reasoning. An apparent `来たん…` may be expanded to `勃ってきたんです` only after checking the raw fragment and the surrounding progression of the same physical reaction. Do not alter it again from the reviewed copy; reopen the original evidence case instead.

Do not edit when the choice depends on unseen mouth movement, an unclear proper noun with no later reuse, a moan or distorted voice with several plausible readings, or stylistic preference.

## Required review passes

### Full-context pass

Read the entire subtitle and establish:

- character list and aliases;
- speaker relationships;
- organization names and ranks;
- timeline and major plot transitions;
- repeated technical, sexual, or setting-specific vocabulary.

### Local language pass

Check Japanese particles, verb forms, homophones, word boundaries, duplicated chunk edges, and malformed fixed expressions. Check whether the Chinese preserves subject, polarity, agency, tense, and referents.

First inspect Japanese without allowing the Chinese to make a broken cue seem meaningful. Then inspect the alignment separately. If both languages contain the same bizarre image, treat that as one ASR hypothesis and ask whether a different word boundary explains the raw form.

Build a dialect/idiolect glossary from repeated clear examples before interpreting apparent negatives or malformed endings. In particular, do not map a regional affirmative onto a similar standard-Japanese negative. For example:

- `よか` can mean “good” in Hakata speech; `よかねぇ` is not standard `よくねえ` (“not good”).
- `来んね` can be an invitation meaning “come here,” not a prohibition.
- A raw `日本芝の目で男はよかねえ` must enter the suspect list: `日本酒飲める男はよかねぇ` accounts for the sound, parses normally, and is confirmed when the next cue continues discussing men and drinking.

### Contradiction pass

Inspect every short exchange as a chain, not isolated cues. Prioritize:

- question followed by direct answer;
- accusation followed by denial or correction;
- pronoun or name followed by identity information;
- promise followed by consequence;
- repeated requests such as returning, stopping, or continuing.

This pass catches fluent semantic errors such as translating `振られた` as rain when the next line says “I dumped her.”

### Consistency pass

Search every spelling of names, titles, and glossary terms. Distinguish a surname plus title from similar common nouns. Do not expand a short title when the speaker naturally uses the short form.

### Risk pass

Re-read all edits from the original, not from the reviewed text. For each change, verify source trace, original failure, and direction-sensitive meaning: negation, tense, agency, quantity, and state change. Downgrade uncertain reconstructions to unresolved notes. Explicit content is not itself evidence of an error and must not be sanitized.

### Unchanged-event miss pass

After the edit risk pass, re-read every unchanged event once more with the final glossary and full plot context. Focus on missed ASR segmentation, fluent-but-false Chinese, dialect polarity, and opening or chunk-boundary cues. Do not polish style. Record any newly discovered suspect in the original ledger before deciding it.

Replay the first and last 15 events and the first and last 3 events of each reading chunk even if they were already marked clear. Early cues lack established context during the first read; chunk edges are where attention and sentence continuations most often fail.

## One-edit rule

Keep the primary ASS unchanged while developing candidates. Freeze the ledger first, then create the reviewed copy and apply exactly one final text replacement per event. Never use the edited line as evidence for a second edit. If a later observation changes the decision, discard that event's decision, return to the original cue and its neighbors, replace the ledger entry, then generate the final replacement again.

## Optional alternate-ASR comparison

Align by overlapping time ranges, not event index. Use the alternate only to:

- propose a candidate where the primary is malformed;
- confirm a name or ordinary word;
- identify missing coverage or duplicated chunk boundaries;
- compare error modes.

Never replace the primary wholesale. Different segmentation means raw event counts are not directly comparable. Report:

- confirmed changes / total events;
- coverage start and end;
- over-segmentation and very short events;
- obvious phonetic fragments;
- fluent but contextually false hallucinations.

## Report contents

Include:

- input and output names;
- total and changed event counts;
- whether alternate evidence was available;
- complete sequential chunk coverage with surface, direction, and context suspect IDs;
- reconciled counts where `total = changed + unresolved + unchanged clear`;
- table columns: time, original, corrected, reason;
- normalized glossary;
- unresolved items requiring audio;
- structural validation and parser result;
- original and reviewed SHA-256 values.
