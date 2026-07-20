# Local Video Subtitle Pipeline

English | [Chinese](README-CN.md)

This project generates Simplified Chinese SRT subtitles from local video files and writes
a bilingual Chinese/Japanese ASS by default. The default pipeline is tuned for Japanese
audio and runs fully offline after the required models are downloaded.

Windows users can start with the portable desktop GUI in the
[`v0.1.0 Beta 2` release](https://github.com/chubbyk-uu/jp2zh-video-subs/releases/tag/v0.1.0-beta.2).
It bundles the application runtime and FFmpeg, but not third-party model weights; follow
`INSTALL-EN.txt` or `INSTALL-CN.txt` on the release page to download models with the bundled
Hugging Face CLI. The command-line workflow remains fully supported for source installations
and advanced use.

It ships two transcription backends, selectable with `--asr`:

- **`anime` (default)** — `litagin/anime-whisper` for text, WhisperSeg for weak-speech framing, semantic scene boundaries, and Qwen forced alignment with automatic VAD fallback. This is the recommended main line for the current JAV/anime-style material.
- **`qwen`** — `Qwen3-ASR-1.7B` for content plus `Qwen3-ForcedAligner-0.6B` for timing, over WhisperSeg speech frames with aligner fallback recovery. Useful as a cleaner text/timing comparison line.

…and two translation backends, selectable with `--translator`:

- **`galtransl` (default)** — `Sakura-GalTransl-7B-v3.7`, a Japanese→Chinese model GRPO-tuned for visual-novel dialogue. Smaller and faster than Sakura-14B with more colloquial output; follows a terminology table natively in its native `src->dst #note` format.
- **`sakura`** — `Sakura-14B-Qwen2.5-v1.0`, a larger light-novel/galgame model. Heavier but a useful second opinion on long, complex lines.

See [docs/BACKENDS.md](docs/BACKENDS.md) (Chinese) for feature-by-feature backend comparisons.

For tuning, backend comparisons, all options, step-by-step usage, and troubleshooting,
see the detailed docs under [docs/](docs/) (Chinese; listed in [Documentation](#documentation)).

## What It Does

The one-command pipeline performs these steps:

1. Extract a 16 kHz mono WAV file from the input video with `ffmpeg`.
2. Transcribe Japanese audio into a Japanese SRT with the selected ASR backend (`anime` by default).
3. Translate the Japanese SRT into Simplified Chinese with the selected translation backend (`galtransl` by default).
4. Generate a bilingual ASS by default (Chinese on top, Japanese below) and copy it next to the input video.
5. Optionally write a quality report for coverage, possible missed speech, duplicate-looking lines, and Japanese or non-Simplified text left in Chinese subtitles when `--quality-report` is set.

The default anime backend runs WJ-style ASR framing (semantic scene boundaries, WhisperSeg
grouped frames, anime-whisper text, and forced alignment with local/whole-frame VAD fallback); `--asr qwen` is the cleaner
text/timing comparison line. How each line works and how cues are shaped is detailed in
[docs/BACKENDS.md](docs/BACKENDS.md). The translation step runs in its own process so the
ASR and translation models never share VRAM. All generated SRTs are sorted and
de-overlapped so cues never overlap or go out of order.

In batch mode, videos are processed smallest first, and each video's audio (step 1) is extracted one step ahead in a background thread. Audio extraction is CPU/IO bound while recognition and translation are GPU bound, so extracting the next video while the current one is on the GPU hides extraction behind the GPU work instead of blocking on it. Extraction stays a single serial read stream to reduce random IO pressure on HDDs; avoid running multiple pipeline instances against the same mechanical disk.

No online API is required for inference. Model files are not included in this repository and should not be committed.

## Project Layout

```text
.
├── models/                         # Local models, not committed
│   ├── anime-whisper/               # Default anime ASR text model
│   ├── whisperseg/model.onnx        # Default anime weak-speech VAD model
│   ├── Qwen3-ASR-1.7B/              # Optional Qwen ASR model (content)
│   ├── Qwen3-ForcedAligner-0.6B/    # Default Anime/Qwen timing model
│   ├── Sakura-GalTransl-7B-v3.7-GGUF/ # Default translation model
│   ├── Sakura-14B-Qwen2.5-v1.0-GGUF/ # Alternate (larger) translation model
│   └── voice-gender-classifier/     # Optional ECAPA gender model (bilingual colouring)
├── outputs/                         # Final subtitles (Chinese SRT and bilingual ASS)
├── scripts/
│   ├── video_to_zh_srt.py           # One-command video-to-Chinese-SRT pipeline
│   ├── transcribe_ja_srt_qwen.py    # WAV/audio to Japanese SRT (Qwen/anime shared backend)
│   ├── quality_report.py            # Subtitle quality report
│   ├── translate_srt_galtransl.py   # Japanese SRT to Chinese SRT (default Sakura-GalTransl)
│   ├── translate_srt_sakura.py      # Japanese SRT to Chinese SRT (Sakura-14B)
│   ├── retime_existing_subtitles.py # Retiming + ASS refresh from existing outputs
│   ├── make_bilingual_ass.py        # Bilingual ASS (Chinese on top, Japanese below) + speaker colouring
│   ├── ecapa_gender.py              # Vendored ECAPA-TDNN voice gender classifier
│   └── srt_utils.py                 # Shared SRT parsing, timing, and interval helpers
├── docs/                            # Detailed docs (backend comparison, usage)
├── tests/                           # Pytest unit tests for the pure helpers and batch pipeline
└── work/                            # Intermediate files (audio, intermediate SRTs)
```

## Requirements

Verified environment:

- OS: Ubuntu 24.04 / Linux x86_64
- Python: 3.11 or 3.12 (the current test host uses Python 3.12)
- FFmpeg: 6.1.1
- `qwen-asr`: 0.0.6 (Qwen ASR and forced-aligner runtime; pulls in `torch`, `transformers`, `librosa`, `soundfile`)
- `onnxruntime-gpu`: 1.27.0 (WhisperSeg VAD for the default anime backend; imported directly, not pulled in by `qwen-asr` — on a CPU-only host install `onnxruntime` instead)
- `torch`: 2.12 on an RTX 50-series (Blackwell) GPU
- `llama-cpp-python`: 0.3.33 (CUDA build for GPU translation)
- `numpy`: 2.4.6 (`<2.5` is required by the installed `numba` used for semantic scenes)
- `huggingface-hub`: 0.36.2

Recommended hardware:

- GPU: NVIDIA GPU with around 12 GB VRAM is a comfortable target. The default anime
  backend loads anime-whisper and the forced aligner sequentially, plus WhisperSeg; Qwen comparison mode (1.7B ASR + 0.6B
  aligner) peaks near 11.5 GB at the default `--qwen-batch-size 24`, so lower it to `16`
  if you hit out-of-memory. Translation runs in a separate process, so it does not stack
  on top of ASR.
- CPU: 8 cores or more.
- RAM: 16 GB minimum, 32 GB recommended.
- Disk: at least 20 GB free for the default models and outputs.

The default anime backend and the Qwen comparison backend require a CUDA GPU.

> GPU/driver note: `qwen-asr` runs on PyTorch, so the installed `torch` must match your
> GPU. On very new GPUs (e.g. NVIDIA Blackwell / RTX 50-series) the default PyPI wheel may
> not have kernels for your compute capability — install a matching CUDA build first, e.g.
> `pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio`.

## Installation

Create and activate a Python 3.11 or 3.12 virtual environment:

```bash
python3 -m venv .venv
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
  python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.33
```

## Download Models

Default one-command models:

- Anime ASR text: [`litagin/anime-whisper`](https://huggingface.co/litagin/anime-whisper)
- Anime weak-speech VAD: [`TransWithAI/Whisper-Vad-EncDec-ASMR-onnx`](https://huggingface.co/TransWithAI/Whisper-Vad-EncDec-ASMR-onnx)
- Anime/Qwen timing: [`Qwen/Qwen3-ForcedAligner-0.6B`](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)
- Translation: [`SakuraLLM/Sakura-GalTransl-7B-v3.7`](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)

Optional comparison models:

- Qwen ASR comparison: [`Qwen/Qwen3-ASR-1.7B`](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)

The `hf` command is installed by `huggingface-hub` from `requirements.txt`. Download
models to the default paths:

```bash
mkdir -p models

# Default anime ASR backend
hf download litagin/anime-whisper \
  --local-dir models/anime-whisper

mkdir -p models/whisperseg
hf download TransWithAI/Whisper-Vad-EncDec-ASMR-onnx \
  model.onnx \
  --revision 6ac29e2cbf2f4f8e9b639861766a8639dd666e9c \
  --local-dir models/whisperseg

# Default Anime timing and Qwen timing
hf download Qwen/Qwen3-ForcedAligner-0.6B \
  --local-dir models/Qwen3-ForcedAligner-0.6B

# Optional Qwen ASR comparison line
hf download Qwen/Qwen3-ASR-1.7B \
  --local-dir models/Qwen3-ASR-1.7B

# Default translation model (Sakura-GalTransl-7B-v3.7, ~6.25 GB high-quality quant)
hf download SakuraLLM/Sakura-GalTransl-7B-v3.7 \
  Sakura-Galtransl-7B-v3.7.gguf \
  --local-dir models/Sakura-GalTransl-7B-v3.7-GGUF
```

Default required files:

```text
models/anime-whisper/config.json
models/anime-whisper/model.safetensors
models/whisperseg/model.onnx
models/Qwen3-ForcedAligner-0.6B/config.json
models/Qwen3-ForcedAligner-0.6B/model.safetensors
models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf
```

Qwen comparison additionally needs:

```text
models/Qwen3-ASR-1.7B/config.json
models/Qwen3-ASR-1.7B/model-00001-of-00002.safetensors
models/Qwen3-ASR-1.7B/model-00002-of-00002.safetensors
```

The larger `sakura` translator (`--translator sakura`) needs
[`SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF`](https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF) instead:

```bash
hf download SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF \
  sakura-14b-qwen2.5-v1.0-iq4xs.gguf \
  --local-dir models/Sakura-14B-Qwen2.5-v1.0-GGUF
```

Bilingual speaker colouring (opt-in with `--colour-by-speaker`) needs the ECAPA voice
gender model [`JaesungHuh/voice-gender-classifier`](https://huggingface.co/JaesungHuh/voice-gender-classifier)
(~60 MB, torch-only). It is optional — without it the bilingual ASS is still written,
just uncoloured:

```bash
hf download JaesungHuh/voice-gender-classifier \
  --local-dir models/voice-gender-classifier
```

```text
models/voice-gender-classifier/model.safetensors
models/voice-gender-classifier/config.json
```

## One-Command Usage

Process one video:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4
```

That command is the default line: `anime` ASR (anime-whisper + WhisperSeg + semantic scene
+ forced alignment with VAD fallback), `galtransl` translation, Chinese SRT, and bilingual ASS. Add
`--quality-report` for tuning/test runs. Common variants:

```bash
# Default ASR + default translation (Anime + GalTransl)
python scripts/video_to_zh_srt.py path/to/input.mp4

# Default anime ASR, but disable semantic scene pre-segmentation for A/B testing
python scripts/video_to_zh_srt.py path/to/input.mp4 --anime-scene-backend none

# Qwen comparison line
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen

# Keep default anime ASR, but switch the translator
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura
```

Process all supported video files in a directory:

```bash
python scripts/video_to_zh_srt.py path/to/videos/
```

Process subdirectories as well:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --recursive
```

Batch order (smallest first) and background audio prefetch are described in
[What It Does](#what-it-does); no extra flags are needed.

If your videos are on a Windows drive mounted by WSL, use the generic mounted Linux path:

```bash
python scripts/video_to_zh_srt.py "/mnt/<drive>/<path-to-videos>"
```

Do not put private local paths in public documentation or issue reports.

For config files, the full default-behavior reference, all common options, step-by-step
per-script usage, the CUDA check, and troubleshooting, see [docs/USAGE.md](docs/USAGE.md) (Chinese).

## Desktop GUI

### Windows portable beta

The easiest Windows entry point is the portable
[`v0.1.0 Beta 2` release](https://github.com/chubbyk-uu/jp2zh-video-subs/releases/tag/v0.1.0-beta.2):

1. Download every `jp2zh-video-subs-windows-x64-cuda-program.7z.*` volume.
2. Put all volumes in one directory and extract `.7z.001` with 7-Zip or NanaZip.
3. Open a Command Prompt in the extracted `jp2zh-video-subs` folder and follow
   `INSTALL-EN.txt` (or `INSTALL-CN.txt`) to download the required models with the bundled
   `runtime\Scripts\hf.exe`.
4. Double-click `jp2zh字幕工具.exe`.

That executable name is specific to the already-published Beta 2 archive. Current development
builds and the next portable beta use the language-neutral `jp2zh-subtitle-tool.exe` name.

No system Python, FFmpeg, or CUDA Toolkit installation is required. A working NVIDIA driver
is still required. The release contains no model weights, user or sample videos, subtitles, or
similar content.
On first launch, missing-model checks list the files that must be downloaded. Until
`models\whisperseg\model.onnx` exists, the device panel reports speech segmentation as
"not checked (model missing)" instead of guessing CPU. With the model installed, it reports
CUDA, CPU, or a probe failure from a real ONNX Runtime session; use **Refresh** after changing
model files.

The GUI supports video/folder drag-and-drop, a visible task queue, Anime/Qwen and
GalTransl/Sakura selectors, common subtitle settings, live overall progress with detailed stage
status, collapsible logs, cancellation, retry, remembered settings, model-file checks, and
successful-job cleanup policies. Expanded videos run sequentially so multiple model instances
do not stack their VRAM usage.

The Windows package embeds Python 3.12, FFmpeg, PyTorch CUDA, ONNX Runtime CUDA, and CUDA-enabled
llama.cpp. It has passed relocation to paths containing spaces and Chinese characters, native
EXE startup without WSL, all three CUDA probes with the models installed, and end-to-end Anime +
GalTransl processing. Qwen + GalTransl, Anime + Sakura 14B, and speaker colouring were also
validated before publication. Current native CUDA evidence covers one RTX 5080 system only, so
other NVIDIA GPU/driver combinations remain beta feedback rather than a broad compatibility
claim.

### Run the GUI from source

The same PySide6 GUI is available from a source checkout:

```bash
python -m pip install -r requirements-gui.txt
python scripts/run_gui.py
```

The GUI drives the existing CLI pipeline rather than maintaining a separate inference path.
`packaging/windows/` contains the pinned runtime inputs and reproducible Windows staging scripts.

## Outputs

For `path/to/input.mp4`, the default outputs are:

- `work/input/input.wav`: extracted 16 kHz mono WAV audio.
- `work/input/input.ja.srt`: main-pass Japanese subtitles used for translation by default.
- `work/input/pipeline.log`: full pipeline log with per-stage timestamps (stdout + stderr of every subprocess). Appended across runs, survives terminal disconnects and reboots.
- `work/input/input.quality.txt`: quality report, only when `--quality-report` is set.
- `work/metrics.jsonl`: one JSON line of key quality metrics per processed video, only when `--quality-report` is set (entries, VAD coverage, kana residue, adjacent duplicates). Shared across videos and runs, for comparing tuning changes over time.
- `outputs/input.zh.srt`: final Chinese SRT.
- `path/to/input.zh.ass`: bilingual ASS copied next to the input video. Bilingual
  output is on by default, so the ASS (not the SRT) is the artifact placed beside the
  video; the Chinese SRT still stays in `outputs/`. With `--no-bilingual`, the Chinese
  SRT is copied next to the video instead.

Japanese SRT files keep the recognized speech timing and are used for gap
analysis, VAD coverage, and quality reports. The Chinese SRT is the display
subtitle: the one-command pipeline slightly extends its cue end times so short
lines do not disappear immediately when speech ends. Bilingual ASS files take
their timing from the Chinese SRT; Japanese text in ASS is aligned by subtitle
index only.
By default, a Chinese cue over 20 visible characters (including punctuation) is
shown on two lines after the `。？！.!?` nearest its midpoint. It remains one SRT/ASS
cue with the same timing; cues without suitable punctuation are not hard-split. Use
`--display-wrap-max-chars 0` to disable this or pass another threshold.

## Documentation

The detailed reference docs are maintained in Chinese only:

- [docs/BACKENDS.md](docs/BACKENDS.md) — ASR (Anime vs Qwen) and translation (GalTransl vs Sakura) backend comparisons, how each line works, and when to prefer which.
- [docs/USAGE.md](docs/USAGE.md) — config files, full default behavior, all common options, step-by-step per-script usage, the CUDA check, and troubleshooting.
- [docs/GUI_TEST_PLAN.md](docs/GUI_TEST_PLAN.md) — executable GUI test matrix, Windows portable acceptance cases, and run/defect record templates (Chinese).

## Testing

The pure helper functions (SRT parsing, timing, interval math, noise/duplicate detection, translation cleanup) are covered by `pytest` and do not need the models or a GPU:

```bash
python -m pip install pytest
python -m pytest tests/ -q
```

## Git Policy

Commit source files and documentation:

- `README.md`, `README-CN.md`, tracked public documents under `docs/`, `requirements.txt`
- `scripts/`
- `tests/`
- `.gitignore` and placeholder files

Do not commit:

- `models/`
- private input videos
- `work/`
- generated `outputs/`
- the local project plan `docs/PLAN.md`
- virtual environments and `__pycache__/`

## Future Work

- Continue A/B review of the default anime line against the current Qwen comparison line, especially weak-speech recall, local mishears, and readability splits.
- Improve Qwen text accuracy without re-enabling long merged context by default unless manual review shows hallucination and tail drift stay controlled.
- Qwen gap recapture has been removed; continue improving Qwen recall through WhisperSeg/scene framing and text recognition quality instead of a second ASR pass.
- HY-MT and the legacy Whisper ASR backend have been removed; the pipeline now exposes two ASR backends (`anime`/`qwen`) and two translators (`galtransl`/`sakura`).
- Continue improving ASR post-processing for isolated symbols, meaningless short subtitles, OCR-like noise, and end-credit noise.
