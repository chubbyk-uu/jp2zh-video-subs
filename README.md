# Local Video Subtitle Pipeline

English | [Chinese](README-CN.md)

This project generates Simplified Chinese SRT subtitles from local video files. The default pipeline is tuned for Japanese audio and runs fully offline after the required models are downloaded.

## What It Does

The one-command pipeline performs these steps:

1. Extract a 16 kHz mono WAV file from the input video with `ffmpeg`.
2. Transcribe Japanese audio into a Japanese SRT with local `faster-whisper-large-v3`.
3. Run an audio-aware second pass to fill likely missed speech in subtitle gaps.
4. Translate the filled Japanese SRT into Simplified Chinese with local `HY-MT1.5-7B-GGUF`.
5. Write a quality report for coverage, possible missed speech, duplicate-looking lines, and Japanese or non-Simplified text left in Chinese subtitles.

When gap filling is enabled (the default), steps 2 and 3 run in a single process that loads the Whisper model once, instead of loading it twice. The translation step stays in its own process so the Whisper and translation models never share VRAM. All generated SRTs are sorted and de-overlapped so cues never overlap or go out of order.

In batch mode, videos are processed smallest first, and each video's audio (step 1) is extracted one step ahead in a background thread. Audio extraction is CPU/IO bound while recognition and translation are GPU bound, so extracting the next video while the current one is on the GPU hides extraction behind the GPU work instead of blocking on it. Extraction stays a single serial read stream to reduce random IO pressure on HDDs; avoid running multiple pipeline instances against the same mechanical disk.

No online API is required for inference. Model files are not included in this repository and should not be committed.

## Project Layout

```text
.
├── models/                         # Local models, not committed
│   ├── faster-whisper-large-v3/     # CTranslate2 Whisper ASR model
│   └── HY-MT1.5-7B-GGUF/            # GGUF translation model
├── outputs/                         # Final Chinese SRT files
├── scripts/
│   ├── video_to_zh_srt.py           # One-command video-to-Chinese-SRT pipeline
│   ├── transcribe_ja_srt.py         # WAV/audio to Japanese SRT
│   ├── fill_ja_srt_gaps.py          # Audio-aware Japanese SRT gap filling
│   ├── quality_report.py            # Subtitle quality report
│   ├── translate_srt_hymt.py        # Japanese SRT to Chinese SRT
│   ├── retime_existing_subtitles.py # Retiming + ASS refresh from existing outputs
│   ├── make_bilingual_ass.py        # Bilingual ASS (Chinese on top, Japanese below)
│   └── srt_utils.py                 # Shared SRT parsing, timing, and interval helpers
├── tests/                           # Pytest unit tests for the pure helpers and batch pipeline
└── work/                            # Intermediate files (audio, intermediate SRTs)
```

## Requirements

Verified environment:

- OS: Ubuntu 24.04 / Linux x86_64
- Python: 3.11
- FFmpeg: 6.1.1
- `faster-whisper`: 1.2.1
- `llama-cpp-python`: 0.3.23
- `huggingface-hub`: 1.15.0

Recommended hardware:

- GPU: NVIDIA GPU with 12 GB VRAM or more is recommended.
- CPU: 8 cores or more.
- RAM: 16 GB minimum, 32 GB recommended.
- Disk: at least 10 GB free for the default models and outputs.

CPU-only execution works, but long videos will be much slower. The ASR script tries CUDA first and falls back to CPU int8 if CUDA is unavailable.

## Installation

Create and activate a Python 3.11 virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Install FFmpeg:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

`llama-cpp-python` installed from PyPI is usually CPU-only. If you want GPU acceleration for translation, reinstall it with CUDA support after installing the CUDA toolkit and build tools:

```bash
CMAKE_ARGS='-DGGML_CUDA=on' FORCE_CMAKE=1 \
  python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.23
```

## Download Models

Default models:

- ASR: [`Systran/faster-whisper-large-v3`](https://huggingface.co/Systran/faster-whisper-large-v3)
- Translation: [`tencent/HY-MT1.5-7B-GGUF`](https://huggingface.co/tencent/HY-MT1.5-7B-GGUF)

Download them to the default paths:

```bash
mkdir -p models

hf download Systran/faster-whisper-large-v3 \
  --local-dir models/faster-whisper-large-v3

hf download tencent/HY-MT1.5-7B-GGUF HY-MT1.5-7B-Q4_K_M.gguf \
  --local-dir models/HY-MT1.5-7B-GGUF
```

Required files include:

```text
models/faster-whisper-large-v3/model.bin
models/faster-whisper-large-v3/config.json
models/faster-whisper-large-v3/tokenizer.json
models/faster-whisper-large-v3/vocabulary.json
models/faster-whisper-large-v3/preprocessor_config.json
models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

## One-Command Usage

Process one video:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4
```

Process all supported video files in a directory:

```bash
python scripts/video_to_zh_srt.py path/to/videos/
```

Process subdirectories as well:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --recursive
```

In a batch, videos are processed in ascending file-size order so the smallest one
is ready first and the GPU starts sooner, and the next video's audio is extracted
in the background while the current video is being recognised and translated. No
extra flags are needed and nothing runs in parallel on the GPU.

If your videos are on a Windows drive mounted by WSL, use the generic mounted Linux path:

```bash
python scripts/video_to_zh_srt.py "/mnt/<drive>/<path-to-videos>"
```

Do not put private local paths in public documentation or issue reports.

## Default Behavior

The one-command pipeline uses:

- ASR model: `models/faster-whisper-large-v3`
- Translation model: `models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf`
- Source language: Japanese, `ja`
- Whisper previous-text conditioning: disabled by default
- Max subtitle display duration: 10 seconds
- Translation context: previous 1 dialogue turn as chat history (previous source/translation pair; the current turn carries only the current line). 0 translates each line standalone
- Chinese display timing: 0.5 seconds lead-out and 1.5 seconds minimum display duration
- VAD: enabled with a sensitive default configuration
- Gap fill: enabled by default
- Pipeline preset: `--preset coverage`
- Quality report: enabled by default
- Extracted WAV audio: kept by default

The default `coverage` ASR and gap-fill settings intentionally favor subtitle coverage.
They are sensitive and aggressive so quiet or short speech is less likely to be
missed. The tradeoff is slower processing and a higher chance of Whisper
hallucinations, so review `work/input/input.quality.txt` and `work/input/input.fills.tsv`
when accuracy matters.

Pipeline presets:

| Preset | Use When | Main Settings |
| --- | --- | --- |
| `fast` | You want a quicker, more conservative pass with fewer hallucinations and can accept more missed quiet speech. | `--vad-threshold 0.20`, `--fill-min-gap-seconds 6`, `--fill-min-speech-seconds 2`, `--fill-min-clip-seconds 1.0`, `--fill-clip-pad-seconds 0.6`, `--fill-existing-pad-seconds 0.3`, `--fill-max-existing-overlap-seconds 0.5` |
| `coverage` | Default. You want higher subtitle coverage and are willing to review more low-confidence fill candidates. | `--vad-threshold 0.05`, `--fill-min-gap-seconds 2`, `--fill-min-speech-seconds 1`, `--fill-min-clip-seconds 0.6`, `--fill-clip-pad-seconds 0.4`, `--fill-existing-pad-seconds 0.1`, `--fill-max-existing-overlap-seconds 1.0` |
| `high-coverage` | You need the highest coverage on long videos where full-audio VAD misses speech inside subtitle gaps. | Same as `coverage`, plus `--gap-local-vad` and `--gap-local-vad-threshold 0.60`; gap fill uses per-gap local VAD instead of full-audio VAD |

All presets use `--fill-max-clip-seconds 45`, `--fill-min-chars 3`,
`--fill-max-cluster-gap 2.0`, `--fill-duplicate-window-seconds 8.0`, and
`--max-fill-compression-ratio 25`. You can override any preset value by passing
the specific option after choosing the preset, for example
`--preset fast --vad-threshold 0.25`.

Default `coverage` gap-fill parameters:

- `--fill-min-gap-seconds 2`: inspect subtitle gaps longer than 2 seconds (aggressive, to
  catch the short low-energy reactions the main pass misses).
- `--fill-min-speech-seconds 1`: fill when the gap contains at least 1 second of VAD speech.
- `--fill-max-clip-seconds 45`: cap one fill clip at 45 seconds.
- `--fill-min-chars 3`: ignore very short fill results.
- `--max-fill-compression-ratio 25`: drop extreme repetitive fill outputs, while keeping
  moderate compression-ratio entries for review/reporting.

Optional gap-local VAD is available with `--gap-local-vad`. Enable it when you
need higher coverage on long videos where full-audio VAD misses speech inside
subtitle gaps. With this option, the gap-fill stage does not use full-audio VAD
to decide candidate clips; it runs VAD directly on each eligible subtitle gap
using `--gap-local-vad-threshold 0.60` by default. Gaps at least
`--gap-local-vad-window-min-gap-seconds 10` are scanned with 5-second windows
and 3-second overlap; the windows only discover speech positions, and the final
ASR clips are still built from merged speech clusters. Gap-local clips get extra
ASR context (`--gap-local-asr-pad-seconds 3`) and are split at
`--gap-local-asr-max-clip-seconds 45` with `--gap-local-asr-overlap-seconds 5`.
This can recover more speech, but it further increases processing time and can
surface more low-confidence fill candidates.

The default main pass is sliding-window VAD (`--main-local-vad`, on by default;
use `--no-main-local-vad` for the legacy whole-file VAD pass). It uses 8-second
windows with 4-second overlap at `--main-local-vad-threshold 0.5`, then builds ASR
clips from merged speech clusters (`--main-local-asr-pad-seconds 0.3`,
`--main-local-vad-max-cluster-gap 2.0`, `--main-local-asr-max-clip-seconds 30`). Clips
are transcribed in one batched pass (`BatchedInferencePipeline`,
`--main-local-batch-size 24`); clips are capped at the 30s Whisper window so none are
truncated. `--main-local-vad-dry-run` prints the selection coverage (clusters, clips,
covered minutes, coverage%) without running Whisper, for fast parameter sweeps. The
same cleaning gap fill used (compression-ratio, noise/looping-repetition,
adjacent-near-duplicate, and repeat-hallucination filters, plus a `--min-cue-seconds 0.3`
floor that drops overlap-squeezed flash cues) runs on the main-pass output, so it
replaces the separate gap-fill stage. Gap fill is off by default; opt in with
`--gap-fill` (usually together with `--no-main-local-vad`).

Because the aggressive gates re-transcribe near-silent clips, gap fill also drops Whisper
hallucinations. The hard list is limited to platform/subtitle boilerplate (`ご視聴…`,
`チャンネル登録`, `それではまた`, …) plus clear subtitle labels/context-mismatched set
phrases (`笑い声`, `拍手`, `アーメン`). Ordinary dialogue such as greetings, thanks, and
farewells is not filtered by text alone. A confidence-aware frequency backstop considers
phrases repeated at least 10 times across one video's fills, but only removes the phrase when
the repeated group is also likely near-silence (`--hallucination-repeat-no-speech-prob 0.75`)
or low-confidence (`--hallucination-repeat-avg-logprob -0.80`). A small high-risk repeat
phrase set also has an absolute repeat cap (`--hallucination-high-risk-max-repeats 3`).
Filter reasons (`hallucination`, `hallucination_repeat`, `noise`, …) are recorded per row in
`input.fills.tsv`.

## Outputs

For `path/to/input.mp4`, the default outputs are:

- `work/input/input.wav`: extracted 16 kHz mono WAV audio.
- `work/input/input.ja.srt`: first-pass Japanese subtitles.
- `work/input/input.filled.ja.srt`: gap-filled Japanese subtitles used for translation.
- `work/input/input.fills.ja.srt`: only the second-pass added Japanese lines.
- `work/input/input.fills.tsv`: gap-fill confidence metadata and filter reasons.
- `work/input/input.quality.txt`: quality report.
- `outputs/input.zh.srt`: final Chinese SRT.
- `path/to/input.zh.srt`: final Chinese SRT copied next to the input video. With
  `--bilingual`, the bilingual `input.zh.ass` is copied next to the video instead
  of the SRT (the SRT still stays in `outputs/`).

Japanese SRT files keep the recognized speech timing and are used for gap
analysis, VAD coverage, and quality reports. The Chinese SRT is the display
subtitle: the one-command pipeline slightly extends its cue end times so short
lines do not disappear immediately when speech ends. Bilingual ASS files take
their timing from the Chinese SRT; Japanese text in ASS is aligned by subtitle
index only.

## Common Options

Set output path for a single video:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --output outputs/input.zh.srt
```

Set output directory for batch processing:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --output-dir outputs
```

The default pipeline is the batched sliding-window main pass with no gap fill.
To run the legacy whole-file VAD pass plus the audio-aware gap fill instead:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-main-local-vad --gap-fill
```

Disable quality report generation:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --skip-quality-report
```

Delete extracted WAV audio after processing:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --delete-audio
```

Do not copy the final subtitle file (the SRT, or the ASS with `--bilingual`) next to the input video:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-copy-to-video-dir
```

Also write a bilingual subtitle (Chinese on top, Japanese below):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --bilingual
```

This writes `outputs/input.zh.ass` and copies it next to the input video. In
bilingual mode only the ASS is placed beside the video (the SRT is not), while
`outputs/` still keeps both the SRT and the ASS. SRT cannot reliably style each
line differently, so the bilingual output is ASS: the Chinese line is larger and
coloured, the Japanese line is smaller and gray. Defaults can be changed with
`--bilingual-zh-font-size`,
`--bilingual-ja-font-size`, `--bilingual-zh-colour`, and `--bilingual-ja-colour`
(colours use the ASS `&HAABBGGRR` format). The Japanese line is the gap-filled
SRT used for translation, so the two lines stay aligned cue by cue.

Adjust display timing padding for the final Chinese SRT and bilingual ASS:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

These options only affect `outputs/input.zh.srt` and any generated ASS. The
Japanese SRT remains at the real speech timing, so gap filling and quality
analysis are not affected. Standalone `translate_srt_hymt.py` defaults to
`0/0` for backward compatibility; the one-command pipeline defaults to
`0.5/1.5`.

Refresh existing batch outputs without rerunning ASR or translation:

```bash
python scripts/retime_existing_subtitles.py path/to/videos/ \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

This reads `outputs/<name>.zh.srt` and the matching Japanese SRT from
`work/<name>/<name>.filled.ja.srt` (falling back to `<name>.ja.srt` if needed),
writes `outputs/<name>.retimed.zh.srt` and `outputs/<name>.retimed.zh.ass`,
then copies the refreshed ASS next to each video as `<name>.zh.ass`. Use
`--dry-run` to check matches first, and `--no-copy-to-video-dir` to only write
the files under `outputs/`.

Reduce translation context if translated lines include previous subtitles:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

Use the faster conservative preset:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --preset fast
```

Use the highest-coverage preset:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --preset high-coverage
```

`high-coverage` may recover more quiet speech, but it is slower and can
introduce less stable short lines.

Continue batch processing after one video fails:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --continue-on-error
```

## Step-by-Step Usage

Transcribe audio to Japanese SRT:

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output work/input/input.ja.srt \
  --model models/faster-whisper-large-v3 \
  --max-duration 10
```

Fill likely missed Japanese subtitles with WAV audio:

```bash
python scripts/fill_ja_srt_gaps.py work/input/input.ja.srt \
  --audio work/input/input.wav \
  --output work/input/input.filled.ja.srt \
  --fills-output work/input/input.fills.ja.srt \
  --fills-metadata-output work/input/input.fills.tsv
```

Translate Japanese SRT to Chinese SRT:

```bash
python scripts/translate_srt_hymt.py work/input/input.filled.ja.srt \
  --output outputs/input.zh.srt \
  --model-path models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf \
  --context-size 1 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

Build a bilingual ASS from the aligned Japanese and Chinese SRTs:

```bash
python scripts/make_bilingual_ass.py \
  --zh-srt outputs/input.zh.srt \
  --ja-srt work/input/input.filled.ja.srt \
  --output outputs/input.zh.ass
```

Generate a quality report:

```bash
python scripts/quality_report.py \
  --ja-srt work/input/input.filled.ja.srt \
  --zh-srt outputs/input.zh.srt \
  --audio work/input/input.wav \
  --fills-metadata work/input/input.fills.tsv \
  --output work/input/input.quality.txt
```

Translate only the first N entries for debugging:

```bash
python scripts/translate_srt_hymt.py work/input/input.ja.srt \
  --output outputs/input.sample.zh.srt \
  --limit 20
```

## CUDA Check

Check whether `llama-cpp-python` was built with CUDA:

```bash
python - <<'PY'
import llama_cpp
info = llama_cpp.llama_print_system_info()
print(info.decode() if isinstance(info, bytes) else info)
PY
```

If the output includes `CUDA`, `CUDA0`, or `offloaded ... layers to GPU`, translation can use the GPU.

## Testing

The pure helper functions (SRT parsing, timing, interval math, noise/duplicate detection, translation cleanup) are covered by `pytest` and do not need the models or a GPU:

```bash
python -m pip install pytest
python -m pytest tests/ -q
```

## Troubleshooting

### Missing Models

If you see errors like:

```text
Missing Whisper model: .../models/faster-whisper-large-v3/model.bin
Missing HY-MT model: .../models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

Download the models again and keep the default directory and file names.

### Translation Is Slow

Usually `llama-cpp-python` is running on CPU or the GPU does not have enough VRAM. Run the CUDA check above. CPU translation still works, but long videos will take much longer.

### `ffmpeg` Not Found

Install FFmpeg and confirm it is on `PATH`:

```bash
sudo apt install -y ffmpeg
ffmpeg -version
```

### Translated Lines Include Previous Subtitles

Lower or disable translation context:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

### Some Speech Is Missed

The default sliding-window main pass already scans the whole WAV with local VAD,
so it covers speech the legacy whole-file VAD would miss without a separate fill
stage. If you prefer more recall, lower `--main-local-vad-threshold` (default
0.5) or raise `--main-local-vad-max-cluster-gap` (default 2.0); both select more
audio at the cost of more clips and more hallucinations to filter.

To fall back to the legacy two-pass behavior, run `--no-main-local-vad --gap-fill`.
Gap fill then does not judge gaps by duration alone; it checks the WAV audio with
VAD and only re-transcribes gaps with enough speech. `fast` and `coverage` use
full-audio VAD for this check; `high-coverage` or `--gap-local-vad` runs VAD
directly on each eligible gap.

### Duplicate-Looking Lines

Check the quality report, especially `suspicious_adjacent_duplicates`, `japanese_kana_left`, and `possible_japanese_or_traditional_left`. The ASR step already splits long internal word gaps and merges short adjacent fragments, while translation supplies context as chat history (the current turn carries only the current line), which avoids fusing the previous line into the output at the source, and retries once without history if Japanese kana leaks into a translation. `possible_japanese_or_traditional_left` is a conservative review hint for kanji-only leftovers or non-Simplified characters; it does not filter subtitles automatically.

### Low-Confidence or Hallucinated Gap Fills

Gap-fill lines are added on quiet or uncertain audio, so they are the most likely
to be misheard or hallucinated. For each gap-fill entry the pipeline records the
Whisper confidence to `work/<name>/<name>.fills.tsv`, and the quality report
summarises it under `[Gap Fill Metadata]`, including `low_confidence_kept_entries`,
`repeated_kept_fill_phrases`, and sample lists. The confidence signals are:

- `avg_logprob`: average token log-probability; **lower is less confident** (flagged below `--warn-avg-logprob-below`, default `-0.80`).
- `no_speech_prob`: probability the clip is not speech; **higher means more likely a hallucination on near-silence** (flagged above `--warn-no-speech-prob-above`, default `0.50`).
- `compression_ratio`: text repetitiveness; **higher means more repetitive/garbled** (flagged above `--warn-compression-ratio-above`, default `2.20`).

Use the sample lists to spot-check those timestamps in the Japanese SRT, and tighten or loosen the thresholds to taste. `repeated_kept_fill_phrases` is report-only by default at 3 kept repeats; it does not delete subtitles. Extreme fill `compression_ratio` values are filtered by `--max-fill-compression-ratio` before translation. This only covers the second-pass gap fills, not the first-pass transcription.

## Git Policy

Commit source files and documentation:

- `README.md`, `README-CN.md`, `requirements.txt`
- `scripts/`
- `tests/`
- `.gitignore` and placeholder files

Do not commit:

- `models/`
- private input videos
- `work/`
- generated `outputs/`
- virtual environments and `__pycache__/`

## Future Work

- Add configurable ASR initial prompts for names, terms, products, and scene-specific vocabulary.
- Add a configurable glossary for recurring names and terms.
- Continue improving ASR post-processing for isolated symbols, meaningless short subtitles, OCR-like noise, and end-credit noise.
