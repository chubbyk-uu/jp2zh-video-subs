# Local Video Subtitle Pipeline

English | [Chinese](README-CN.md)

This project generates Simplified Chinese SRT subtitles from local video files. The default pipeline is tuned for Japanese audio and runs fully offline after the required models are downloaded.

## What It Does

The one-command pipeline performs these steps:

1. Extract a 16 kHz mono WAV file from the input video with `ffmpeg`.
2. Transcribe Japanese audio into a Japanese SRT with local `faster-whisper-large-v3`.
3. Optionally run an audio-aware second pass (`--gap-fill`) to fill likely missed speech in subtitle gaps.
4. Translate the Japanese SRT into Simplified Chinese with local `HY-MT1.5-7B-GGUF`.
5. Write a quality report for coverage, possible missed speech, duplicate-looking lines, and Japanese or non-Simplified text left in Chinese subtitles.

The default main recognition pass already produces useful coverage for many videos. Add `--gap-fill` when you want to recover more quiet or missed speech; it increases processing time and can also introduce more hallucinated or misheard subtitles, so review the quality report and gap-fill metadata for important outputs. When gap filling is enabled, steps 2 and 3 run in a single process that loads the Whisper model once, instead of loading it twice. The translation step stays in its own process so the Whisper and translation models never share VRAM. All generated SRTs are sorted and de-overlapped so cues never overlap or go out of order.

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
- VAD: batched sliding-window local VAD over the whole WAV (the only main pass)
- Gap fill: off by default (opt in with `--gap-fill`)
- Quality report: enabled by default
- Extracted WAV audio: kept by default

There are no pipeline presets; the single batched sliding-window pass is the
default. Tune recall vs. cleanliness with `--main-local-vad-threshold` (default
0.5; lower keeps more quiet speech but adds hallucinations to filter) and
`--main-local-vad-max-cluster-gap` (default 2.0).

Optional gap fill (`--gap-fill`) re-examines subtitle gaps to recover speech the
precision-tuned main pass missed. It runs per-gap local VAD on each eligible gap
(`--gap-local-vad-threshold 0.60`); gaps of at least
`--gap-local-vad-window-min-gap-seconds 6` use 5-second windows with 3-second
overlap, shorter gaps use a single per-gap scan. Candidate clips are transcribed
with `--gap-local-asr-pad-seconds 1.0` in the same batched pass as the main stage.
Gap-fill gates default aggressive
(`--fill-min-gap-seconds 2`, `--fill-min-speech-seconds 1`, `--fill-min-chars 1`,
`--max-fill-compression-ratio 25`) and the same cleaning filters are reused, but
the extra recall is inherently less stable than the main pass. It increases
processing time and can surface more low-confidence, hallucinated, or misheard
candidates, so review `input.quality.txt` and `input.fills.tsv` when accuracy matters.

The main pass uses 8-second windows with 4-second overlap at
`--main-local-vad-threshold 0.5`, then builds ASR clips from merged speech
clusters (`--main-local-asr-pad-seconds 0.3`, `--main-local-vad-max-cluster-gap 2.0`,
`--main-local-asr-max-clip-seconds 30`). Clips are transcribed in one batched pass
(`BatchedInferencePipeline`, `--main-local-batch-size 24`); clips are capped at the
30s Whisper window so none are truncated. `--main-local-vad-dry-run` prints the
selection coverage (clusters, clips, covered minutes, coverage%) without running
Whisper, for fast parameter sweeps. Cleaning filters (compression-ratio,
noise/looping-repetition, adjacent-near-duplicate, and repeat-hallucination filters,
plus a `--min-cue-seconds 0.3` floor that drops overlap-squeezed flash cues) run on
the main-pass output. The same batched transcription and cleaning are reused by the
optional `--gap-fill` stage.

The default ASR batch size (`--main-local-batch-size 24`) is throughput-oriented
and can use substantial GPU memory. If CUDA runs out of memory or the GPU has
less VRAM, lower it first, for example to `12`, `8`, or `4`.

Because the aggressive gates re-transcribe near-silent clips, gap fill also drops Whisper
hallucinations. The hard list is limited to platform/subtitle boilerplate (`ご視聴…`,
`チャンネル登録`, `それではまた`, …) plus clear subtitle labels/context-mismatched set
phrases (`笑い声`, `拍手`, `アーメン`). Ordinary dialogue such as greetings, thanks, and
farewells is not filtered by text alone. A confidence-aware frequency backstop considers
phrases repeated at least 10 times across one video's fills, but only removes the phrase when
the repeated group is also likely near-silence (`--hallucination-repeat-no-speech-prob 0.75`)
or low-confidence (`--hallucination-repeat-avg-logprob -0.80`). A small high-risk repeat
phrase set also has an absolute repeat cap (`--hallucination-high-risk-max-repeats 3`).
Filter reasons (`hallucination`, `hallucination_repeat`, `noise`, `context_duplicate`, …) are recorded per row in
`input.fills.tsv`. Gap fill also drops longer low-confidence entries with weak
local VAD support (`low_confidence_low_vad_support`) using
`--fill-support-min-chars 8`, `--fill-support-avg-logprob -0.95`,
`--fill-support-no-speech-prob 0.45`, `--fill-support-vad-threshold 0.5`,
and `--fill-support-max-ratio 0.45`.

## Outputs

For `path/to/input.mp4`, the default outputs are:

- `work/input/input.wav`: extracted 16 kHz mono WAV audio.
- `work/input/input.ja.srt`: main-pass Japanese subtitles used for translation by default.
- `work/input/input.quality.txt`: quality report.
- `outputs/input.zh.srt`: final Chinese SRT.
- `path/to/input.zh.srt`: final Chinese SRT copied next to the input video. With
  `--bilingual`, the bilingual `input.zh.ass` is copied next to the video instead
  of the SRT (the SRT still stays in `outputs/`).

With `--gap-fill`, the pipeline also writes:

- `work/input/input.filled.ja.srt`: gap-filled Japanese subtitles used for translation.
- `work/input/input.fills.ja.srt`: only the second-pass added Japanese lines.
- `work/input/input.fills.tsv`: gap-fill confidence metadata and filter reasons.

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
To also run the audio-aware gap fill stage for more recall:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --gap-fill
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
(colours use the ASS `&HAABBGGRR` format). The Japanese line comes from the
Japanese SRT used for translation (`.ja.srt` by default, `.filled.ja.srt` with
`--gap-fill`), so the two lines stay aligned cue by cue.

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

Recover more quiet speech with the optional gap-fill stage:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --gap-fill
```

Gap fill re-examines subtitle gaps and may recover more quiet speech, but it is
slower and can introduce less stable short lines.

Reduce ASR batch size if your GPU runs out of VRAM:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --main-local-batch-size 8
```

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
python scripts/translate_srt_hymt.py work/input/input.ja.srt \
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
  --ja-srt work/input/input.ja.srt \
  --output outputs/input.zh.ass
```

Generate a quality report:

```bash
python scripts/quality_report.py \
  --ja-srt work/input/input.ja.srt \
  --zh-srt outputs/input.zh.srt \
  --audio work/input/input.wav \
  --output work/input/input.quality.txt
```

If you ran `fill_ja_srt_gaps.py`, use `work/input/input.filled.ja.srt` for
translation, ASS, and quality reporting, and pass
`--fills-metadata work/input/input.fills.tsv` to the quality report.

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

If ASR fails with CUDA out-of-memory, lower `--main-local-batch-size`; the default
`24` is intended for throughput and may be too high for smaller GPUs.

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

The sliding-window main pass already scans the whole WAV with local VAD. If you
prefer more recall, lower `--main-local-vad-threshold` (default 0.5) or raise
`--main-local-vad-max-cluster-gap` (default 2.0); both select more audio at the
cost of more clips and more hallucinations to filter.

For even more recall, add `--gap-fill`. It does not judge gaps by duration alone;
it runs per-gap local VAD on each eligible subtitle gap and only re-transcribes
gaps with enough speech, then cleans the results with the same filters as the main
pass.

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
- Continue improving ASR post-processing for isolated symbols, meaningless short subtitles, OCR-like noise, and end-credit noise.
