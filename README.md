# Local Video Subtitle Pipeline

[中文版 README](README_CN.md)

This project automatically generates Simplified Chinese SRT subtitles from video files. The default pipeline targets Japanese speech:

1. Extract a 16 kHz mono WAV track from the video with `ffmpeg`.
2. Transcribe Japanese audio into a source-language SRT with the local `faster-whisper-large-v3` model.
3. Translate the source SRT into Simplified Chinese with the local `HY-MT1.5-7B-GGUF` model.

All inference runs locally; no online APIs are required. The model files must be downloaded the first time you reproduce the setup and should not be committed to GitHub.

## Directory Layout

```text
.
├── models/                         # Local model files, do not commit
│   ├── faster-whisper-large-v3/     # CTranslate2-format Whisper ASR model
│   └── HY-MT1.5-7B-GGUF/            # GGUF translation model
├── outputs/                         # Final Chinese subtitle output
├── scripts/
│   ├── video_to_zh_srt.py           # One-shot: video → Chinese SRT
│   ├── transcribe_ja_srt.py         # Audio → Japanese SRT
│   └── translate_srt_hymt.py        # Source SRT → Chinese SRT
├── subtitles/
│   ├── ja/                          # Optional: Japanese SRT archive
│   └── zh/                          # Optional: Chinese SRT archive
├── videos/                          # Input videos
└── work/                            # Intermediate files
```

## Environment

Verified setup:

- OS: Ubuntu 24.04 / Linux x86_64
- Python: 3.11
- FFmpeg: 6.1.1
- `faster-whisper`: 1.2.1
- `llama-cpp-python`: 0.3.23
- `huggingface-hub`: 1.15.0

Recommended hardware:

- GPU: an NVIDIA GPU with 12 GB VRAM or more is preferred. With less VRAM, lower the concurrency, fall back to CPU, or pick smaller ASR/translation models.
- CPU: 8 cores or more.
- RAM: 16 GB minimum, 32 GB recommended.
- Disk: keep at least 10 GB free. The two default models take roughly:
  - `faster-whisper-large-v3`: ~2.9 GB
  - `HY-MT1.5-7B-Q4_K_M.gguf`: ~4.4 GB

CPU-only execution works but is noticeably slower. The scripts try CUDA first; if CUDA is not available for ASR, they fall back to CPU int8 automatically.

## Install Dependencies

A Python 3.11 virtual environment is recommended:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

Install the Python dependencies:

```bash
python -m pip install -r requirements.txt
```

> ⚠️ **Note:** The `llama-cpp-python` wheel on PyPI is the **CPU-only prebuilt** version, so the translation step will not use the GPU.
> If you have an NVIDIA GPU, rebuild from source on top of the previous step (the CUDA Toolkit and a build toolchain must already be installed):
>
> ```bash
> CMAKE_ARGS='-DGGML_CUDA=on' FORCE_CMAKE=1 \
>   python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.23
> ```
>
> After the rebuild, verify with the "CUDA verification" section below that the output contains `CUDA` / `offloaded ... layers to GPU`.

Install FFmpeg:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

## Download the Models

The models live on Hugging Face:

- ASR: [`Systran/faster-whisper-large-v3`](https://huggingface.co/Systran/faster-whisper-large-v3)
- Translation: [`tencent/HY-MT1.5-7B-GGUF`](https://huggingface.co/tencent/HY-MT1.5-7B-GGUF)

Download them with `huggingface-hub` into the script defaults:

```bash
mkdir -p models

hf download Systran/faster-whisper-large-v3 \
  --local-dir models/faster-whisper-large-v3

hf download tencent/HY-MT1.5-7B-GGUF HY-MT1.5-7B-Q4_K_M.gguf \
  --local-dir models/HY-MT1.5-7B-GGUF
```

After the download finishes, the directories should at least contain:

```text
models/faster-whisper-large-v3/model.bin
models/faster-whisper-large-v3/config.json
models/faster-whisper-large-v3/tokenizer.json
models/faster-whisper-large-v3/vocabulary.json
models/faster-whisper-large-v3/preprocessor_config.json
models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

If the `hf` command is not available, make sure the virtual environment is active and install:

```bash
python -m pip install -U huggingface-hub
```

Alternatively, download via Git LFS:

```bash
git lfs install
git clone https://huggingface.co/Systran/faster-whisper-large-v3 models/faster-whisper-large-v3
git clone https://huggingface.co/tencent/HY-MT1.5-7B-GGUF models/HY-MT1.5-7B-GGUF
```

## One-Shot Chinese Subtitles

Drop a video into `videos/`, then run:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4
```

Defaults:

- ASR model: `models/faster-whisper-large-v3`
- Translation model: `models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf`
- ASR language: Japanese (`ja`)
- Whisper `condition_on_previous_text`: off by default, to reduce cross-line bleed and hallucinations on long videos
- Max display time per subtitle line: 10 s by default, to avoid stretched lines over silence
- Translation context: previous 2 source lines by default; short lines, ellipses, and suspected bleed are re-translated without context
- VAD: an aggressive configuration is used by default to minimize missed low-volume dialogue
- Intermediate files: `work/<video_filename>/`

When the run finishes you get:

- `work/input/input.ja.srt`: intermediate Japanese subtitles
- `outputs/input.zh.srt`: final Chinese subtitles
- `videos/input.zh.srt`: a copy of the Chinese SRT next to the input video

Batch-process every video in a directory:

```bash
python scripts/video_to_zh_srt.py videos/
```

By default, common video files in the directory are processed in filename order, including `.mp4`, `.mkv`, `.mov`, `.avi`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.ts`. To recurse into subdirectories:

```bash
python scripts/video_to_zh_srt.py videos/ --recursive
```

## Common Options

Set an explicit output path:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt
```

Set an output directory for batch mode:

```bash
python scripts/video_to_zh_srt.py videos/ --output-dir outputs
```

The default baseline is already tuned to the `stable` profile. To change the translation context window:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --context-size 3
```

If the translator starts dragging earlier lines into the current output, lower the context:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --context-size 1
```

Cap the maximum display time per subtitle:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --max-duration 8
```

Re-enable Whisper's previous-text conditioning:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --condition-on-previous-text
```

For long videos with a lot of quiet dialogue, leaving this flag off is recommended. Turning it on can recover more fillers and particles, but it also makes repetition, cross-line bleed, and fragmentation more likely.

Keep the extracted WAV around for debugging:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --keep-audio
```

Skip copying the final SRT next to the input video:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --no-copy-to-video-dir
```

Pick a different scratch directory:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --work-dir work
```

Keep going through the rest of the batch when one video fails:

```bash
python scripts/video_to_zh_srt.py videos/ --continue-on-error
```

## Single Steps

Just the ASR step:

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output subtitles/ja/input.ja.srt \
  --model models/faster-whisper-large-v3 \
  --max-duration 10
```

Translation only, given an existing source SRT:

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.ja.srt \
  --output subtitles/zh/input.zh.srt \
  --model-path models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf \
  --context-size 2
```

Limit the translation to the first N lines for quick smoke tests:

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.ja.srt \
  --output subtitles/zh/input.sample.zh.srt \
  --limit 20
```

## CUDA Verification

Check whether `llama-cpp-python` has CUDA enabled:

```bash
python - <<'PY'
import llama_cpp
info = llama_cpp.llama_print_system_info()
print(info.decode() if isinstance(info, bytes) else info)
PY
```

If you see `CUDA`, `CUDA0`, or `offloaded ... layers to GPU` in the output, the translator is on the GPU.

If only CPU instruction sets are listed, reinstall the CUDA build:

```bash
CMAKE_ARGS='-DGGML_CUDA=on' FORCE_CMAKE=1 \
  python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.23
```

The ASR stage uses `faster-whisper` with CUDA. The script first tries:

```python
WhisperModel(model_name_or_path, device="cuda", compute_type="float16")
```

If CUDA initialization fails, it falls back to:

```python
WhisperModel(model_name_or_path, device="cpu", compute_type="int8")
```

## Reproduction Checklist

Before running, confirm:

- `ffmpeg -version` prints a version banner.
- `python --version` is 3.11 or compatible.
- `models/faster-whisper-large-v3/model.bin` exists.
- `models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf` exists.
- The input video exists, e.g. `videos/input.mp4`.
- `outputs/` and `work/` are writable.

Minimal smoke test:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4
```

To quickly sanity-check only the translation chain, prepare a short SRT and use `--limit`:

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.ja.srt \
  --output outputs/input.sample.zh.srt \
  --limit 5
```

## FAQ

### Missing model files

Errors like:

```text
Missing Whisper model: .../models/faster-whisper-large-v3/model.bin
Missing HY-MT model: .../models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

Re-download per the "Download the Models" section, keeping the directory and file names exactly as listed.

### Translation is very slow

The usual cause is `llama-cpp-python` running on CPU, or GPU VRAM being too small so some layers spill onto CPU. Run the CUDA verification first. If you cannot use a GPU, CPU still works but long videos take a long time.

### `ffmpeg` not found

Install FFmpeg and make sure it is on `PATH`:

```bash
sudo apt install -y ffmpeg
ffmpeg -version
```

### Translated lines bleed from earlier subtitles

The translator uses the previous 2 lines as context by default. If the translation grows too long or starts to bleed earlier content, lower the context:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --context-size 1
```

The script also disables context automatically for short lines, ellipses, and fillers, and re-translates without context when the output is clearly too long.

### Subtitle timing too long

The ASR script enables word-level timestamps and caps abnormally long lines to `--max-duration`. The default cap is 10 s, the current `stable` baseline. If lines still linger too long, drop the cap to 8 s:

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --max-duration 8
```

### Non-Japanese input

The default is `language="ja"`, tuned for Japanese audio. For English, Chinese, or other languages, pass `--language` and adjust the translation prompt accordingly.

## GitHub Commit Notes

Committed in the repo:

- `README.md`, `README_CN.md`, `requirements.txt`
- `scripts/`
- `.gitignore` and `.gitkeep` placeholders in each directory

Not committed (excluded via `.gitignore`):

- `models/`: local models, downloaded from Hugging Face per above
- `videos/`: input videos
- `work/`: intermediate files
- `outputs/`, `subtitles/`: generated results
- `__pycache__/` and virtualenv directories

## Roadmap

- Merge over-fragmented subtitles. The `stable` baseline carries enough information, but single- or two-character lines can still appear around quiet breaths and long silences; adjacent fragments should be merged automatically.
- Add a Whisper `initial_prompt` glossary to improve recognition of proper nouns, person names, product terms, and scene-specific vocabulary.
- Add a term-replacement table to fix common recognition mistakes.
- Add ASR post-processing to filter isolated punctuation, meaningless short lines, garbled English, and end-of-video noise tokens.
- Add a quality report listing suspect subtitles: ultra-short fragments, repeated short lines, overlapping timing, blanks, garbled text, leftover Japanese, overly long translations, and so on.
- Support batch processing of a directory of videos.
- Support multiple output formats: source SRT, Chinese SRT, bilingual SRT, etc.
