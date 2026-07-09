# Local Video Subtitle Pipeline

English | [Chinese](README-CN.md)

This project generates Simplified Chinese SRT subtitles from local video files and writes
a bilingual Chinese/Japanese ASS by default. The default pipeline is tuned for Japanese
audio and runs fully offline after the required models are downloaded.

It ships two transcription backends, selectable with `--asr`:

- **`anime` (default)** — `litagin/anime-whisper` for text, WhisperSeg for weak-speech framing, semantic scene boundaries, and VAD-only timing. This is the recommended main line for the current JAV/anime-style material.
- **`qwen`** — `Qwen3-ASR-1.7B` for content plus `Qwen3-ForcedAligner-0.6B` for timing, over WhisperSeg speech frames with aligner fallback recovery. Useful as a cleaner text/timing comparison line.

…and two translation backends, selectable with `--translator`:

- **`galtransl` (default)** — `Sakura-GalTransl-7B-v3.7`, a Japanese→Chinese model GRPO-tuned for visual-novel dialogue. Smaller and faster than Sakura-14B with more colloquial output; follows a terminology table natively in its native `src->dst #note` format.
- **`sakura`** — `Sakura-14B-Qwen2.5-v1.0`, a larger light-novel/galgame model. Heavier but a useful second opinion on long, complex lines.

See [ASR Backends: Anime vs Qwen](#asr-backends-anime-vs-qwen) and [Translation Backends: GalTransl vs Sakura](#translation-backends-galtransl-vs-sakura) for feature-by-feature comparisons.

Suggested reading order: start with what the pipeline does, installation, and model
downloads, then use the one-command, default behavior, and common options sections. The
backend comparisons, step-by-step usage, and troubleshooting sections are for tuning,
quality review, or failure analysis.

## What It Does

The one-command pipeline performs these steps:

1. Extract a 16 kHz mono WAV file from the input video with `ffmpeg`.
2. Transcribe Japanese audio into a Japanese SRT with the selected ASR backend (`anime` by default).
3. Translate the Japanese SRT into Simplified Chinese with the selected translation backend (`galtransl` by default).
4. Generate a bilingual ASS by default (Chinese on top, Japanese below) and copy it next to the input video.
5. Optionally write a quality report for coverage, possible missed speech, duplicate-looking lines, and Japanese or non-Simplified text left in Chinese subtitles when `--quality-report` is set.

The default anime backend runs WJ-style ASR framing: semantic scene boundaries, WhisperSeg
grouped frames, anime-whisper text, and `vad_only` timing. It keeps each frame whole and
only splits very long comma-delimited runs for readability, without treating sentence
punctuation or `…` as split points. This avoids forced-aligner fragmentation while
keeping this project's translation, overlap cleanup, and ASS generation. Qwen remains available with
`--asr qwen` for cleaner text/timing comparisons, and anime can still be forced through
the aligner for diagnostics with `--anime-timestamp-mode aligner_fallback` or
`aligner_only`. The translation step runs in its own process so the ASR and translation
models never share VRAM. All generated SRTs are sorted and de-overlapped so cues never
overlap or go out of order.

In batch mode, videos are processed smallest first, and each video's audio (step 1) is extracted one step ahead in a background thread. Audio extraction is CPU/IO bound while recognition and translation are GPU bound, so extracting the next video while the current one is on the GPU hides extraction behind the GPU work instead of blocking on it. Extraction stays a single serial read stream to reduce random IO pressure on HDDs; avoid running multiple pipeline instances against the same mechanical disk.

No online API is required for inference. Model files are not included in this repository and should not be committed.

## Project Layout

```text
.
├── models/                         # Local models, not committed
│   ├── anime-whisper/               # Default anime ASR text model
│   ├── whisperseg/model.onnx        # Default anime weak-speech VAD model
│   ├── Qwen3-ASR-1.7B/              # Optional Qwen ASR model (content)
│   ├── Qwen3-ForcedAligner-0.6B/    # Optional Qwen/anime aligner diagnostics
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
├── tests/                           # Pytest unit tests for the pure helpers and batch pipeline
└── work/                            # Intermediate files (audio, intermediate SRTs)
```

## Requirements

Verified environment:

- OS: Ubuntu 24.04 / Linux x86_64
- Python: 3.11 or 3.12 (the current test host uses Python 3.12)
- FFmpeg: 6.1.1
- `qwen-asr`: 0.0.6 (Qwen ASR and optional forced-aligner diagnostics; pulls in `torch`, `transformers`, `librosa`, `soundfile`)
- `torch`: 2.10 with CUDA 12.8 (`cu128`) on an RTX 50-series (Blackwell) GPU
- `llama-cpp-python`: 0.3.23
- `huggingface-hub`: 0.36.2

Recommended hardware:

- GPU: NVIDIA GPU with around 12 GB VRAM is a comfortable target. The default anime
  backend loads anime-whisper plus WhisperSeg; Qwen comparison mode (1.7B ASR + 0.6B
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
  python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.23
```

## Download Models

Default one-command models:

- Anime ASR text: [`litagin/anime-whisper`](https://huggingface.co/litagin/anime-whisper)
- Anime weak-speech VAD: [`TransWithAI/Whisper-Vad-EncDec-ASMR-onnx`](https://huggingface.co/TransWithAI/Whisper-Vad-EncDec-ASMR-onnx)
- Translation: [`SakuraLLM/Sakura-GalTransl-7B-v3.7`](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)

Optional comparison/diagnostic models:

- Qwen ASR comparison: [`Qwen/Qwen3-ASR-1.7B`](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- Qwen forced aligner: [`Qwen/Qwen3-ForcedAligner-0.6B`](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B), required for `--asr qwen` and for anime `aligner_fallback` / `aligner_only` diagnostics, not for default anime `vad_only`

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

# Qwen comparison line and optional anime forced-aligner diagnostics
hf download Qwen/Qwen3-ASR-1.7B \
  --local-dir models/Qwen3-ASR-1.7B

hf download Qwen/Qwen3-ForcedAligner-0.6B \
  --local-dir models/Qwen3-ForcedAligner-0.6B

# Default translation model (Sakura-GalTransl-7B-v3.7, ~6.25 GB high-quality quant)
hf download SakuraLLM/Sakura-GalTransl-7B-v3.7 \
  Sakura-Galtransl-7B-v3.7.gguf \
  --local-dir models/Sakura-GalTransl-7B-v3.7-GGUF
```

Required files include:

```text
models/anime-whisper/config.json
models/anime-whisper/model.safetensors
models/whisperseg/model.onnx
models/Qwen3-ASR-1.7B/config.json
models/Qwen3-ASR-1.7B/model-00001-of-00002.safetensors
models/Qwen3-ASR-1.7B/model-00002-of-00002.safetensors
models/Qwen3-ForcedAligner-0.6B/config.json
models/Qwen3-ForcedAligner-0.6B/model.safetensors
models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf
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
+ vad_only timing), `galtransl` translation, Chinese SRT, and bilingual ASS. Add
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

In a batch, videos are processed in ascending file-size order so the smallest one
is ready first and the GPU starts sooner, and the next video's audio is extracted
in the background while the current video is being recognised and translated. No
extra flags are needed and nothing runs in parallel on the GPU.

If your videos are on a Windows drive mounted by WSL, use the generic mounted Linux path:

```bash
python scripts/video_to_zh_srt.py "/mnt/<drive>/<path-to-videos>"
```

Do not put private local paths in public documentation or issue reports.

## Configuration Files

The one-command interface is unchanged: pass the input video or directory on the
command line as usual. TOML config files are optional and are meant for saving a
repeatable set of tuning flags, so long commands do not need to be typed every run.

Print the effective defaults as a reusable flat TOML template:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --print-config > pipeline.toml
```

Edit the values you want to keep, then run with:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --config pipeline.toml
```

Config keys are the argparse destination names, using underscores. For example:

```toml
asr = "qwen"
translator = "galtransl"
qwen_batch_size = 16
lead_out_seconds = 0.8
min_display_seconds = 1.5
```

The TOML file is flat; sections such as `[asr]` or `[translation]` are rejected.
The per-run `input`/`output` paths are omitted from `--print-config` and always
given on the command line. Value flags given on the command line override the TOML
file. Plain one-way switches such as `quality_report = true` or `resume = true` cannot
be turned back off from the same command line; edit the TOML file or use a
separate config for those modes.

## ASR Backends: Anime vs Qwen

The backend is chosen with `--asr` (default `anime`):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4                 # Anime (default)
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen      # Qwen comparison line
```

### How the default anime line works

1. Semantic scene detection cuts the audio into 12-48 s acoustic scenes.
2. WhisperSeg runs inside each scene and groups speech into short frames using WJ-style
   anime defaults: `max_group=5.0`, `chunk_threshold=0.5`, `max_speech=5.0`, and
   `min_frame=0.1`.
3. `litagin/anime-whisper` transcribes each frame. The anime text cleaner removes known
   ellipsis-only and short repetition artifacts.
4. Default `vad_only` timing stays on the frame timeline and keeps each frame whole; it only
   applies a length-based readability split: a long segment can split at commas after 50
   content characters, and a comma-less run hard-caps at 80 content characters. Sentence
   punctuation and `…` never split (anime-whisper sprays sentence enders on every soft pause,
   so splitting on them over-fragments into sub-second flash cues). This avoids Qwen
   forced-aligner collapse/fragmentation while keeping cues on screen long enough to read.

Use `--anime-scene-backend none` for A/B tests, or run the Qwen comparison line with
`--asr qwen`.

### How the Qwen line works

1. WhisperSeg is the default Qwen framer (`--qwen-vad-backend whisperseg`). It uses the
   WJ qwen-style grouping values `max_group=6.0`, `chunk_threshold=1.0`,
   `max_speech=5.0`, `min_frame=0.1`, and `threshold=0.35`.
2. Qwen default recognition uses the short scene-padded WhisperSeg frames directly
   (`--qwen-whisperseg-context-mode none`). The `pad` and `merge` context modes remain
   available for experiments, but are not the default because longer merged windows
   increased Qwen hallucination and tail drift in current tests.
3. Clips are transcribed in batches by `Qwen3-ASR-1.7B` with the WJ-style
   generation knobs `max_new_tokens=4096`, `repetition_penalty=1.1`, and a dynamic
   budget of `20` tokens per audio second.
4. The model's punctuated `result.text` is the authoritative content; the separate
   `Qwen3-ForcedAligner-0.6B` supplies per-character timing. Sentences are split on
   punctuation and on large internal timing gaps, then timed from the aligner. Adjacent
   cues inside one clip are merged only when the pause is under 1.5 seconds and the
   merged cue stays within 80 content characters / 8 seconds.
5. Semantic scene splitting is on by default for Qwen, so WhisperSeg frames do not cross
   acoustic-scene boundaries. If the aligner collapses a clip's words into a bad timestamp
   span, the Qwen line uses VAD-guided fallback recovery before subtitle shaping.
   Step-down retry is implemented for experiments, but remains off by default.

For Qwen A/B runs, disable WhisperSeg/VAD cutting (fall back to uniform 30 s tiling)
with `--asr qwen --no-qwen-vad-chunks`.

### When to prefer which

| | **Anime (default)** | **Qwen (`--asr qwen`)** |
|---|---|---|
| Content quality | Best weak-speech recall in current WJ comparisons; can still mishear local phrases | Cleaner text in some normal speech; weaker on breathy/quiet dialogue |
| Timing drift | VAD-only timing avoids anime forced-aligner collapse | WhisperSeg framing + aligner fallback recovery greatly reduce the old Qwen drift/collapse failures |
| Speed | Whisper-large style generation per frame; slower than batched Qwen | Fast batched main pass |
| Recall on quiet speech | Strongest current default; review misheard phrases | Improved by WhisperSeg, still weaker than anime on breathy/quiet dialogue |
| Proper nouns / names | Can mishear names and rare terms | Can also mishear names and rare terms |
| Post-processing | Anime cleaner plus shared overlap/flash-cue hygiene | Shared hygiene plus Qwen runaway-repeat collapse; opt into hallucination filters with `--qwen-filter-hallucinations` |
| VRAM | anime-whisper plus WhisperSeg; aligner only for non-`vad_only` diagnostics | 1.7B + 0.6B, ~11.5 GB at default `--qwen-batch-size 24` |

**Recommendation:** use the default anime line for current JAV/anime-style material.
Use `--asr qwen` as a cleaner comparison line or when anime text mishears a local region.

## Translation Backends: GalTransl vs Sakura

The translator is chosen with `--translator` (default `galtransl`):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4                       # GalTransl (default)
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura   # Sakura-14B
```

Both run as GGUF models through `llama-cpp-python` in a process separate from ASR,
and share the same SRT parsing, context handling, terminology table, and display-timing
logic — only the model and prompt template differ. They also share the translation cache
and the kana/empty/adjacent-duplicate retries; GalTransl carries context as a 历史翻译
block of prior translations (its native v3 format), while Sakura uses source/translation
chat pairs.

| | **GalTransl (default)** | **Sakura (`--translator sakura`)** |
|---|---|---|
| Model | `Sakura-GalTransl-7B-v3.7` (visual-novel JA->ZH, GRPO-tuned) | `Sakura-14B-Qwen2.5-v1.0` (light-novel/galgame JA->ZH) |
| Style | Most natural, colloquial dialogue | Natural, slightly more literary |
| Terminology table | Native `src->dst #note` format, injected per line | Native GPT-dictionary format, injected per line |
| Size | 7B (~6.25 GB Q6) | 14B (~8-9 GB iq4xs) |

GalTransl is the default translator because it is smaller, lighter to run, and has matched
the project's dialogue samples well. Sakura-14B is heavier and useful as a second opinion
for long or suspicious lines. Actual speed and memory use depend on the GGUF quant, context
length, batch size, whether `llama-cpp-python` is GPU-enabled, and the specific GPU.

Both leave proper-noun mistakes from the ASR stage untouched (neither can fix a misheard
name), and all depend on the recognised Japanese being correct.

**Recommendation:** keep the default GalTransl translator for this kind of visual-novel /
dialogue content. Try `--translator sakura` for a second opinion on long, complex lines.

## Default Behavior

The one-command pipeline uses:

- ASR backend: `anime` (`models/anime-whisper` + `models/whisperseg/model.onnx`)
- Anime semantic scene pre-segmentation: on (`--anime-scene-backend semantic`; disable with `--anime-scene-backend none`)
- Anime timing mode: `vad_only` (`--anime-timestamp-mode vad_only`; aligner modes are diagnostic and require `models/Qwen3-ForcedAligner-0.6B`)
- Anime WhisperSeg frame defaults: `max_group=5.0`, `chunk_threshold=0.5`, `max_speech=5.0`, `min_frame=0.1`, `threshold=0.35`
- Anime semantic scene ASR pad: `--anime-scene-asr-pad-seconds 0.35`, matching WhisperJAV's padded `asr_processing` scene windows while keeping timeline cues on the frame timestamps
- Anime does not use Qwen's WhisperSeg context `pad` / `merge` path. With `vad_only` timing, extra neighboring context cannot be filtered by an aligner ownership pass, and current anime evaluations do not show a need for it.
- Anime cleaner: on for ellipsis-only fragments, leading soft ellipses, and short repetition artifacts; default `vad_only` keeps frame timing and only splits a frame at long comma-delimited runs (not sentence endings), then shared final hygiene removes overlaps and flash cues
- Qwen comparison line: available with `--asr qwen`. It defaults to WhisperSeg framing (`--qwen-vad-backend whisperseg`) with Qwen values `max_group=6.0`, `chunk_threshold=1.0`, `max_speech=5.0`, `min_frame=0.1`, `threshold=0.35`; use `--asr qwen --no-qwen-vad-chunks` for fixed 30 s tiling.
- Qwen context mode: default `--qwen-whisperseg-context-mode none`; `pad` and `merge` remain selectable experiments, but longer merged windows are not the default because they increased hallucination in current tests.
- Qwen timing, segmentation, and generation: default `--qwen-timestamp-mode aligner_fallback`, `--qwen-scene-backend semantic`, `--qwen-scene-asr-pad-seconds 0.35`, `--qwen-phrase-max-chars 80`, `--qwen-phrase-max-internal-gap 1.5`, `--qwen-max-new-tokens 4096`, `--qwen-repetition-penalty 1.1`, and `--qwen-max-tokens-per-second 20.0`. Step-down retry is implemented in the shared sub-script but not exposed as a top-level default path.
- Qwen `vad_only` timing is diagnostic only. If you explicitly set `--qwen-timestamp-mode vad_only`, also set `--qwen-whisperseg-context-mode none`; pure VAD timing cannot filter text recognized from padded/merged neighboring context, so the pipeline rejects that combination.
- Whisper-style hallucination filtering on Qwen output: off (opt in with `--asr qwen --qwen-filter-hallucinations`)
- Bare filler-interjection dropping: on for the shared qwen/anime sub-script. Cues that reduce entirely to a single filler mora (うん/ん/ねえ/あ …) and carry no dialogue are removed — either an isolated blip walled by `--anime-isolated-interjection-silence 3.0` seconds of silence on both sides in the default anime line, or a chain of 3+ such fillers in a row. Only cues that are *entirely* a filler are eligible, so any line containing real words always survives. Disable with `--anime-isolated-interjection-silence 0` for anime or `--qwen-isolated-interjection-silence 0` for qwen (also turns off the chain rule).
- Filler-repetition collapse: on for the shared qwen/anime sub-script. A run of the same filler repeated inside one cue (うんうんうん。, or うん、うん、うん、一人。 padding real speech) collapses to a single instance at the token-alignment level. The run only collapses when both edges sit on punctuation or the cue boundary, so repetition inside real words (ああいう) is never touched. Pass `--no-anime-collapse-filler-repetition` for anime or `--no-qwen-collapse-filler-repetition` for qwen A/B comparison.
- General runaway-repetition collapse: on in the shared qwen/anime sub-script. Consecutive phrase floods such as `行く` repeated many times are reduced to two copies before final subtitle output, while ordinary 2-3x emphasis is kept.
- Translation backend: `galtransl` (`models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf`); use `--translator sakura` for Sakura-14B
- Source language: Japanese, `ja`
- Translation context: previous 6 turns for GalTransl/Sakura by default. `--context-size 0` translates each line standalone
- Batch translation (GalTransl only, `--translate-batch-size`, default 8): up to N consecutive cues (never crossing a >10 s gap) are translated as one turn, so a sentence split across cues is seen whole. This fixes omitted-subject/person errors — e.g. third-person narration spread over several cues was otherwise mistranslated as first-person. It leans on GalTransl's "do not add/remove line breaks" contract to keep output 1:1 with input; line-count mismatches are retried as smaller strict batches, and any remaining unsafe output slots fall back to per-line translation without discarding the rest of the block. `0` or `1` disables batching.
- Chinese display timing: 0.5 seconds lead-out and 1.5 seconds minimum display duration
- Quality report: disabled by default for production subtitle runs; enable with `--quality-report` for tuning/testing
- Extracted WAV audio: kept by default

With `--asr qwen`, Qwen runs the WhisperSeg-framed main pass. Tune recall vs. clip count with
`--qwen-whisperseg-threshold`, `--qwen-whisperseg-max-group`, and
`--qwen-whisperseg-chunk-threshold`.
Use `--asr qwen --no-qwen-vad-chunks` when you want a fixed-tiling sanity check that
does not depend on speech-found clusters.

Qwen context `pad` / `merge` modes keep timing ownership tied to the original speech frames
while making Qwen hear more audio. They are available for experiments, but the default is
`--qwen-whisperseg-context-mode none`. Use `pad` to add bounded pre/post context without
merging frames, or `merge` to tune adjacent-frame merging. The target is a soft
target: below it the merger bridges gaps up to `merge-gap`, but once a merged window passes
it the tolerance tightens to `--qwen-whisperseg-context-after-target-gap` (0.2s) so the clip
ends at the next real pause instead of being cut mid-speech when the hard cap is reached;
`--qwen-whisperseg-context-hard-max-seconds` (35s) is the real safety cap and only bounds
genuinely gap-free speech. The pre/post context flags also apply in `merge` mode. For
dynamic context experiments, set `--qwen-whisperseg-context-pad-mode ratio` and tune
`--qwen-whisperseg-context-pad-ratio` plus min/max pad clamps.

Do not combine Qwen `vad_only` timing with `pad` or `merge` context. In that diagnostic
mode there is no aligner ownership filter, so text heard from neighboring context can
be emitted again in the current VAD region. Use
`--asr qwen --qwen-timestamp-mode vad_only --qwen-whisperseg-context-mode none` only
when you want to isolate Qwen text quality from forced-alignment behavior; for production
Qwen runs, keep the default `aligner_fallback + context none` path unless you are explicitly
testing `pad` / `merge`.

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

## Common Options

### Paths and batch runs

Set output path for a single video:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --output outputs/input.zh.srt
```

Set output directory for batch processing:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --output-dir outputs
```

Continue batch processing after one video fails:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --continue-on-error
```

Do not copy the final subtitle file (the bilingual ASS by default, or the SRT with `--no-bilingual`) next to the input video:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-copy-to-video-dir
```

### Backend selection

Select the ASR backend (default `anime`); use Qwen with:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen
```

Select the translation backend (default `galtransl`); use Sakura-14B with:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura
```

### Recall and gap recovery

Run the Qwen backend with fixed uniform tiling instead of WhisperSeg/VAD-cut clips
(useful as a framing sanity check, usually with more drift):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen --no-qwen-vad-chunks
```

Tune Qwen recall with its WhisperSeg framing knobs, or use `--asr qwen --no-qwen-vad-chunks`
for fixed-tiling comparisons.

### Reports, audio, and resume

Generate a quality report for tuning/test runs:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --quality-report
```

The quality report's audio-aware coverage checks can use ASR metadata or WhisperSeg.
The one-command anime path defaults the report to WhisperSeg so the report matches
anime framing; other paths use `auto`. Override it explicitly with
`--quality-vad-backend metadata`, `whisperseg`, or `auto`. Production subtitle runs do
not need the report. `--skip-quality-report` is kept only as a compatibility no-op
because reports are already off unless `--quality-report` is set.

Delete extracted WAV audio after processing:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --delete-audio
```

Reuse an already-extracted WAV instead of re-running `ffmpeg` (handy when re-running the
pipeline on the same video to tune ASR/translation):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --reuse-existing-audio
```

Resume an interrupted run — skips stages whose outputs already exist and look complete:
transcription (Japanese SRT exists and is non-empty), translation (Chinese SRT cue count
matches the source Japanese SRT), and audio extraction (WAV exists and is non-empty).
The ASS stage always reruns (fast, no GPU). If `--quality-report` is set, the quality
report also reruns. `--resume` implies `--reuse-existing-audio`:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --bilingual --resume
```

### Bilingual ASS and styling

A bilingual ASS (Chinese on top, Japanese below) is written by default. To write only the Chinese SRT instead:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-bilingual
```

This writes `outputs/input.zh.ass` and copies it next to the input video. In
bilingual mode only the ASS is placed beside the video (the SRT is not), while
`outputs/` still keeps both the SRT and the ASS. SRT cannot reliably style each
line differently, so the bilingual output is ASS: the Chinese line is larger and
coloured, the Japanese line is smaller and gray. Defaults can be changed with
`--bilingual-font` (default `Microsoft YaHei`, which covers both the Chinese and
Japanese lines on Windows; non-Windows players fall back via fontconfig),
`--bilingual-zh-font-size`, `--bilingual-ja-font-size`, `--bilingual-zh-colour`, and
`--bilingual-ja-colour` (colours use the ASS `&HAABBGGRR` format). The Japanese line
comes from the Japanese SRT used for translation (`.ja.srt`), so the two lines stay
aligned cue by cue.

In bilingual mode the Chinese line can also be **coloured by speaker gender**
(off by default; enable with `--colour-by-speaker`). Each cue's audio span is
classified male/female by an ECAPA-TDNN voice gender model (VoxCeleb-trained; see
[Download Models](#download-models)), which is far more robust on noisy/music-laden
audio than raw pitch. Only cues classified above `--gender-confidence` (default 0.6)
are recoloured — male deep sky blue, female pink; less certain cues keep the default
colour rather than risk a wrong guess. Recolour with `--bilingual-male-colour` /
`--bilingual-female-colour`. If the model is not downloaded, colouring is skipped and
a plain bilingual ASS is written. Only the Chinese line is recoloured; the Japanese
line stays gray.

Adjust display timing padding for the final Chinese SRT and bilingual ASS:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

These options only affect `outputs/input.zh.srt` and any generated ASS. The
Japanese SRT remains at the real speech timing, so quality analysis is not affected.
Standalone translation scripts default to
`0/0` for backward compatibility; the one-command pipeline defaults to
`0.5/1.5`.

Refresh existing batch outputs without rerunning ASR or translation:

```bash
python scripts/retime_existing_subtitles.py path/to/videos/ \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

This reads `outputs/<name>.zh.srt` and the matching Japanese SRT from
`work/<name>/<name>.ja.srt`,
writes `outputs/<name>.retimed.zh.srt` and `outputs/<name>.retimed.zh.ass`,
then copies the refreshed ASS next to each video as `<name>.zh.ass`. Use
`--dry-run` to check matches first, and `--no-copy-to-video-dir` to only write
the files under `outputs/`.

### Translation and resource tuning

Reduce translation context if translated lines include previous subtitles:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

Reduce ASR batch size if your GPU runs out of VRAM (`--qwen-batch-size` for
`--asr qwen`):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --qwen-batch-size 8
```

## Step-by-Step Usage

Transcribe audio to Japanese SRT with the default anime path through the shared
Qwen/anime sub-script:

```bash
python scripts/transcribe_ja_srt_qwen.py work/input/input.wav \
  work/input/input.ja.srt \
  --text-backend anime \
  --text-model models/anime-whisper \
  --timestamp-mode vad_only \
  --vad-backend whisperseg \
  --whisperseg-model models/whisperseg/model.onnx
```

Or run the Qwen comparison backend directly:

```bash
python scripts/transcribe_ja_srt_qwen.py work/input/input.wav \
  work/input/input.ja.srt \
  --text-backend qwen \
  --model models/Qwen3-ASR-1.7B \
  --forced-aligner models/Qwen3-ForcedAligner-0.6B
```

For fast offline post-processing tuning, dump the raw ASR + aligner stream once with
`--raw-output work/input/input.raw.json`, then rebuild cues from it without the model
using `--from-raw work/input/input.raw.json`.

Translate Japanese SRT to Chinese SRT with the default GalTransl translator:

```bash
python scripts/translate_srt_galtransl.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --context-size 6 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

Or with the Sakura-14B translator:

```bash
python scripts/translate_srt_sakura.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --context-size 6 \
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

Audio-aware coverage metrics in this report can use `--vad-backend metadata`,
`whisperseg`, or `auto`. Use `metadata` when the ASR metadata already carries speech
regions, and `whisperseg` to match the anime line.

Translate only the first N entries for debugging:

```bash
python scripts/translate_srt_galtransl.py work/input/input.ja.srt \
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
Missing Qwen ASR model: .../models/Qwen3-ASR-1.7B
Missing Qwen forced aligner: .../models/Qwen3-ForcedAligner-0.6B
Missing GalTransl model: .../models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf
```

Download the models again and keep the default directory and file names. Anime-whisper,
WhisperSeg, and GalTransl are required for the default line; Qwen models are required for
`--asr qwen` and for anime forced-aligner diagnostics; the Sakura model is only required
for `--translator sakura`.

### Translation Is Slow

Usually `llama-cpp-python` is running on CPU or the GPU does not have enough VRAM. Run the CUDA check above. CPU translation still works, but long videos will take much longer.

If Qwen ASR fails with CUDA out-of-memory, lower `--qwen-batch-size` from its default
`24`.

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

With `--asr qwen`, WhisperSeg decides where speech-cut clips are created. If a speech
island is missed, first try lowering `--qwen-whisperseg-threshold` or adjusting
`--qwen-whisperseg-max-group` / `--qwen-whisperseg-chunk-threshold`, or use
`--asr qwen --no-qwen-vad-chunks` to tile the whole timeline uniformly so no region is
skipped by speech framing.

### Duplicate-Looking Lines

Check the quality report, especially `suspicious_adjacent_duplicates`, `japanese_kana_left`, and `possible_japanese_or_traditional_left`. The ASR step already splits long internal word gaps and merges short adjacent fragments, while translation supplies context as chat history (the current turn carries only the current line), which avoids fusing the previous line into the output at the source. The default GalTransl translator (and Sakura) also self-corrects two failure modes per line: leaked Japanese kana triggers up to two standalone retries (the second with a sampling nudge), and a translation identical to the previous line's while the source differs triggers one standalone retry with a repetition penalty — the duplicate is kept if the model insists, since different sources can genuinely share a rendering. `possible_japanese_or_traditional_left` is a conservative review hint for kanji-only leftovers or non-Simplified characters; it does not filter subtitles automatically.

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

- Continue A/B review of the default anime line against the current Qwen comparison line, especially weak-speech recall, local mishears, and readability splits.
- Improve Qwen text accuracy without re-enabling long merged context by default unless manual review shows hallucination and tail drift stay controlled.
- Qwen gap recapture has been removed; continue improving Qwen recall through WhisperSeg/scene framing and text recognition quality instead of a second ASR pass.
- HY-MT and the legacy Whisper ASR backend have been removed; the pipeline now exposes two ASR backends (`anime`/`qwen`) and two translators (`galtransl`/`sakura`).
- Continue improving ASR post-processing for isolated symbols, meaningless short subtitles, OCR-like noise, and end-credit noise.
