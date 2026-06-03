# Local Video Subtitle Pipeline

English | [Chinese](README-CN.md)

This project generates Simplified Chinese SRT subtitles from local video files. The default pipeline is tuned for Japanese audio and runs fully offline after the required models are downloaded.

## What It Does

The one-command pipeline performs these steps:

1. Extract a 16 kHz mono WAV file from the input video with `ffmpeg`.
2. Transcribe Japanese audio into a Japanese SRT with local `faster-whisper-large-v3`.
3. Run an audio-aware second pass to fill likely missed speech in subtitle gaps.
4. Translate the filled Japanese SRT into Simplified Chinese with local `HY-MT1.5-7B-GGUF`.
5. Write a quality report for coverage, possible missed speech, duplicate-looking lines, and Japanese text left in Chinese subtitles.

When gap filling is enabled (the default), steps 2 and 3 run in a single process that loads the Whisper model once, instead of loading it twice. The translation step stays in its own process so the Whisper and translation models never share VRAM. All generated SRTs are sorted and de-overlapped so cues never overlap or go out of order.

In batch mode, videos are processed smallest first, and each video's audio (step 1) is extracted one step ahead in a background thread. Audio extraction is CPU/IO bound while recognition and translation are GPU bound, so extracting the next video while the current one is on the GPU hides extraction behind the GPU work instead of blocking on it. Extraction stays a single serial read stream, so this behaves the same on HDD and SSD.

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
│   ├── make_bilingual_ass.py        # Bilingual ASS (Chinese on top, Japanese below)
│   └── srt_utils.py                 # Shared SRT parsing, timing, and interval helpers
├── subtitles/
│   ├── ja/                          # Optional Japanese SRT storage
│   └── zh/                          # Optional Chinese SRT storage
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
- Translation context: previous 1 source subtitle in the one-command pipeline
- VAD: enabled with a sensitive default configuration
- Gap fill: enabled by default
- Quality report: enabled by default
- Extracted WAV audio: kept by default

Default gap-fill parameters:

- `--fill-min-gap-seconds 10`: only inspect subtitle gaps longer than 10 seconds.
- `--fill-min-speech-seconds 4`: fill only when the gap contains at least 4 seconds of VAD speech.
- `--fill-max-clip-seconds 45`: cap one fill clip at 45 seconds.
- `--fill-min-chars 3`: ignore very short fill results.

## Outputs

For `path/to/input.mp4`, the default outputs are:

- `work/input/input.wav`: extracted 16 kHz mono WAV audio.
- `work/input/input.ja.srt`: first-pass Japanese subtitles.
- `work/input/input.filled.ja.srt`: gap-filled Japanese subtitles used for translation.
- `work/input/input.fills.ja.srt`: only the second-pass added Japanese lines.
- `work/input/input.quality.txt`: quality report.
- `outputs/input.zh.srt`: final Chinese SRT.
- `path/to/input.zh.srt`: final Chinese SRT copied next to the input video. With
  `--bilingual`, the bilingual `input.zh.ass` is copied next to the video instead
  of the SRT (the SRT still stays in `outputs/`).

## Common Options

Set output path for a single video:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --output outputs/input.zh.srt
```

Set output directory for batch processing:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --output-dir outputs
```

Disable gap filling:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --skip-gap-fill
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

Reduce translation context if translated lines include previous subtitles:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

Use a more aggressive gap-fill setting:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 \
  --fill-min-gap-seconds 6 \
  --fill-min-speech-seconds 2
```

This may recover more quiet speech, but can also introduce less stable short lines.

Continue batch processing after one video fails:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --continue-on-error
```

## Step-by-Step Usage

Transcribe audio to Japanese SRT:

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output subtitles/ja/input.ja.srt \
  --model models/faster-whisper-large-v3 \
  --max-duration 10
```

Fill likely missed Japanese subtitles with WAV audio:

```bash
python scripts/fill_ja_srt_gaps.py subtitles/ja/input.ja.srt \
  --audio work/input/input.wav \
  --output subtitles/ja/input.filled.ja.srt \
  --fills-output subtitles/ja/input.fills.ja.srt
```

Translate Japanese SRT to Chinese SRT:

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.filled.ja.srt \
  --output subtitles/zh/input.zh.srt \
  --model-path models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf \
  --context-size 1
```

Build a bilingual ASS from the aligned Japanese and Chinese SRTs:

```bash
python scripts/make_bilingual_ass.py \
  --zh-srt subtitles/zh/input.zh.srt \
  --ja-srt subtitles/ja/input.filled.ja.srt \
  --output subtitles/zh/input.bilingual.ass
```

Generate a quality report:

```bash
python scripts/quality_report.py \
  --ja-srt subtitles/ja/input.filled.ja.srt \
  --zh-srt subtitles/zh/input.zh.srt \
  --audio work/input/input.wav \
  --output work/input/input.quality.txt
```

Translate only the first N entries for debugging:

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.ja.srt \
  --output subtitles/zh/input.sample.zh.srt \
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

Gap fill is enabled by default. It does not judge gaps by duration alone; it checks the WAV audio with VAD and only re-transcribes gaps with enough speech. For more aggressive filling, lower the gap or speech threshold.

### Duplicate-Looking Lines

Check the quality report, especially `Suspicious adjacent duplicate zh entries`. The ASR step already splits long internal word gaps and merges short adjacent fragments, while translation retries adjacent duplicate-looking output once without context.

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
- generated `outputs/` and `subtitles/`
- virtual environments and `__pycache__/`

## Future Work

- Add configurable ASR initial prompts for names, terms, products, and scene-specific vocabulary.
- Add a configurable glossary for recurring names and terms.
- Continue improving ASR post-processing for isolated symbols, meaningless short subtitles, OCR-like noise, and end-credit noise.
