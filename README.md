# Local Video Subtitle Pipeline

English | [Chinese](README-CN.md)

This project generates Simplified Chinese SRT subtitles from local video files. The default pipeline is tuned for Japanese audio and runs fully offline after the required models are downloaded.

It ships two transcription backends, selectable with `--asr`:

- **`qwen` (default)** — `Qwen3-ASR-1.7B` for content plus `Qwen3-ForcedAligner-0.6B` for timing, over speech-aware (VAD-cut) clips. Cleaner output and tighter timing; this is the recommended main line.
- **`whisper`** — the legacy `faster-whisper-large-v3` sliding pass with an optional audio-aware `--gap-fill` recall stage.

…and three translation backends, selectable with `--translator`:

- **`galtransl` (default)** — `Sakura-GalTransl-7B-v3.7`, a Japanese→Chinese model GRPO-tuned for visual-novel dialogue. Smaller and faster than Sakura-14B with more colloquial output; follows a terminology table natively in its native `src->dst #note` format.
- **`sakura`** — `Sakura-14B-Qwen2.5-v1.0`, a larger light-novel/galgame model. Heavier but a useful second opinion on long, complex lines.
- **`hymt`** — `Hy-MT2-7B`, a general translation model.

See [ASR Backends: Qwen vs Whisper](#asr-backends-qwen-vs-whisper) and [Translation Backends: GalTransl vs Sakura vs HY-MT](#translation-backends-galtransl-vs-sakura-vs-hy-mt) for feature-by-feature comparisons.

## What It Does

The one-command pipeline performs these steps:

1. Extract a 16 kHz mono WAV file from the input video with `ffmpeg`.
2. Transcribe Japanese audio into a Japanese SRT with the selected ASR backend (`qwen` by default).
3. Translate the Japanese SRT into Simplified Chinese with the selected translation backend (`galtransl` by default).
4. Write a quality report for coverage, possible missed speech, duplicate-looking lines, and Japanese or non-Simplified text left in Chinese subtitles.

The default Qwen backend cuts clips on silence with a loose VAD to reduce timing drift,
transcribes those clips in batches, and times each sentence from the forced aligner. In
current project tests it has been less prone to Whisper-style looping/hallucination, so
the heavy Whisper filters are off by default and there is no separate gap-fill stage. If
you suspect the VAD-cut pass missed speech, use `--no-qwen-vad-chunks` to fall back to
uniform timeline tiling for comparison. The translation step runs in its own process so
the ASR and translation models never share VRAM. All generated SRTs are sorted and
de-overlapped so cues never overlap or go out of order.

With `--asr whisper`, step 2 runs the sliding-window Whisper pass, and `--gap-fill`
adds an audio-aware second pass to recover more quiet or missed speech (slower, and more
likely to introduce hallucinated or misheard lines — review the quality report and
gap-fill metadata for important outputs).

In batch mode, videos are processed smallest first, and each video's audio (step 1) is extracted one step ahead in a background thread. Audio extraction is CPU/IO bound while recognition and translation are GPU bound, so extracting the next video while the current one is on the GPU hides extraction behind the GPU work instead of blocking on it. Extraction stays a single serial read stream to reduce random IO pressure on HDDs; avoid running multiple pipeline instances against the same mechanical disk.

No online API is required for inference. Model files are not included in this repository and should not be committed.

## Project Layout

```text
.
├── models/                         # Local models, not committed
│   ├── Qwen3-ASR-1.7B/              # Default ASR model (content)
│   ├── Qwen3-ForcedAligner-0.6B/    # Default aligner (timing)
│   ├── Sakura-GalTransl-7B-v3.7-GGUF/ # Default translation model
│   ├── Sakura-14B-Qwen2.5-v1.0-GGUF/ # Alternate (larger) translation model
│   ├── faster-whisper-large-v3/     # Legacy CTranslate2 Whisper ASR model
│   ├── Hy-MT2-7B-GGUF/              # Optional HY-MT translation model
│   └── voice-gender-classifier/     # Optional ECAPA gender model (bilingual colouring)
├── outputs/                         # Final Chinese SRT files
├── scripts/
│   ├── video_to_zh_srt.py           # One-command video-to-Chinese-SRT pipeline
│   ├── transcribe_ja_srt_qwen.py    # WAV/audio to Japanese SRT (default Qwen backend)
│   ├── transcribe_ja_srt.py         # WAV/audio to Japanese SRT (legacy Whisper backend)
│   ├── fill_ja_srt_gaps.py          # Audio-aware Japanese SRT gap filling
│   ├── quality_report.py            # Subtitle quality report
│   ├── translate_srt_galtransl.py   # Japanese SRT to Chinese SRT (default Sakura-GalTransl)
│   ├── translate_srt_sakura.py      # Japanese SRT to Chinese SRT (Sakura-14B)
│   ├── translate_srt_hymt.py        # Japanese SRT to Chinese SRT (HY-MT)
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
- Python: 3.11
- FFmpeg: 6.1.1
- `qwen-asr`: 0.0.6 (default ASR backend; pulls in `torch`, `transformers`, `librosa`, `soundfile`)
- `torch`: 2.10 with CUDA 12.8 (`cu128`) on an RTX 50-series (Blackwell) GPU
- `faster-whisper`: 1.2.1 (legacy ASR backend)
- `llama-cpp-python`: 0.3.23
- `huggingface-hub`: 0.36.2

Recommended hardware:

- GPU: NVIDIA GPU with around 12 GB VRAM is a comfortable target. The default Qwen
  backend (1.7B ASR + 0.6B aligner) peaks near 11.5 GB at the default `--qwen-batch-size 24`;
  on a 12 GB card that is tight, so lower it to `16` if you hit out-of-memory. The legacy
  Whisper backend fits in about 10 GB. Translation runs in a separate process, so it does
  not stack on top of ASR.
- CPU: 8 cores or more.
- RAM: 16 GB minimum, 32 GB recommended.
- Disk: at least 20 GB free for the default models and outputs.

The default Qwen backend requires a CUDA GPU. The legacy Whisper backend
(`--asr whisper`) tries CUDA first and falls back to CPU int8 if CUDA is unavailable;
CPU-only execution works, but long videos will be much slower.

> GPU/driver note: `qwen-asr` runs on PyTorch, so the installed `torch` must match your
> GPU. On very new GPUs (e.g. NVIDIA Blackwell / RTX 50-series) the default PyPI wheel may
> not have kernels for your compute capability — install a matching CUDA build first, e.g.
> `pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio`.

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

- ASR (content): [`Qwen/Qwen3-ASR-1.7B`](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- ASR (timing): [`Qwen/Qwen3-ForcedAligner-0.6B`](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)
- Translation: [`SakuraLLM/Sakura-GalTransl-7B-v3.7`](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)

Download them to the default paths:

```bash
mkdir -p models

# Default Qwen ASR backend (transcription + forced aligner)
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

The optional `hymt` translator (`--translator hymt`) needs
[`tencent/Hy-MT2-7B-GGUF`](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) instead.
Use `HY-MT2-7B-Q6_K.gguf` by default for quality; choose `Q4_K_M` if memory is tight,
or `Q8_0` if you want the largest quantized file:

```bash
hf download tencent/Hy-MT2-7B-GGUF HY-MT2-7B-Q6_K.gguf \
  --local-dir models/Hy-MT2-7B-GGUF
```

The legacy Whisper backend (`--asr whisper`) additionally needs
[`Systran/faster-whisper-large-v3`](https://huggingface.co/Systran/faster-whisper-large-v3):

```bash
hf download Systran/faster-whisper-large-v3 \
  --local-dir models/faster-whisper-large-v3
```

```text
models/faster-whisper-large-v3/model.bin
models/faster-whisper-large-v3/config.json
models/faster-whisper-large-v3/tokenizer.json
models/faster-whisper-large-v3/vocabulary.json
models/faster-whisper-large-v3/preprocessor_config.json
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

## ASR Backends: Qwen vs Whisper

The backend is chosen with `--asr` (default `qwen`):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4                 # Qwen (default)
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper   # legacy Whisper
```

### How the default Qwen line works

1. A loose sliding-window VAD (`--qwen-vad-threshold 0.1`) finds speech and groups it
   into clusters. The VAD places Qwen clips near speech starts, which reduces
   leading-anchor drift, but a missed speech island can still reduce recall.
2. Each cluster becomes a clip anchored at the real speech-start time (long clusters are
   split with overlap). Clips are transcribed in batches by `Qwen3-ASR-1.7B`.
3. The model's punctuated `result.text` is the authoritative content; the separate
   `Qwen3-ForcedAligner-0.6B` supplies per-character timing. Sentences are split on
   punctuation and on large internal timing gaps, then timed from the aligner.
4. Because each clip starts where speech starts, the first token is anchored to real
   audio instead of the clip edge, which removes most leading-token drift.

Disable the VAD cutting (fall back to uniform 30 s tiling) with `--no-qwen-vad-chunks`.

### When to prefer which

| | **Qwen (default)** | **Whisper (`--asr whisper`)** |
|---|---|---|
| Content quality | Cleaner in current tests; heavy hallucination filters are off by default | More prone to hallucination/looping on quiet audio; needs the built-in filters |
| Timing drift | Lower — VAD-cut clips anchor cues to real speech onset | Higher on long quiet stretches |
| Speed | Fast batched main pass; no gap-fill stage | Comparable main pass; `--gap-fill` adds a slower second pass |
| Recall on quiet speech | Good in current tests; verify with the quality report and use fixed tiling if VAD-cut clips look suspicious | Add `--gap-fill` to push recall further |
| Proper nouns / names | Weaker — can mishear names and rare terms | Similar weakness; neither is reliable on unseen names |
| Post-processing | Minimal (overlap + flash-cue hygiene, plus dropping bare filler interjections like うん/あ that carry no dialogue); opt into Whisper-style filters with `--qwen-filter-hallucinations` | Full compression/looping/duplicate/hallucination filtering |
| VRAM | 1.7B + 0.6B, ~11.5 GB at default `--qwen-batch-size 24` (lower to `16` on 12 GB cards) | large-v3, ~10 GB (less with smaller `--main-local-batch-size`) |
| Cost of VAD cutting | ~2× clips vs uniform tiling, so the main pass is a bit slower in exchange for less drift | n/a |

**Recommendation:** keep the default Qwen line for general use. Use `--asr whisper`
`--gap-fill` when you specifically need to squeeze out more quiet/low-energy speech and
are willing to review more unstable lines, or when a CUDA GPU is unavailable (Whisper has
a CPU fallback; Qwen requires CUDA).

## Translation Backends: GalTransl vs Sakura vs HY-MT

The translator is chosen with `--translator` (default `galtransl`):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4                       # GalTransl (default)
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura   # Sakura-14B
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator hymt     # HY-MT
```

All three run as GGUF models through `llama-cpp-python` in a process separate from ASR,
and share the same SRT parsing, context handling, terminology table, and display-timing
logic — only the model and prompt template differ. GalTransl and Sakura also share the
translation cache and the kana/empty/adjacent-duplicate retries; GalTransl carries
context as a 历史翻译 block of prior translations (its native v3 format), Sakura uses
source/translation chat pairs, and HY-MT2 follows its documented single-user-prompt
shape with matched terminology plus previous Chinese translations as background.

| | **GalTransl (default)** | **Sakura (`--translator sakura`)** | **HY-MT (`--translator hymt`)** |
|---|---|---|---|
| Model | `Sakura-GalTransl-7B-v3.7` (visual-novel JA→ZH, GRPO-tuned) | `Sakura-14B-Qwen2.5-v1.0` (light-novel/galgame JA→ZH) | `Hy-MT2-7B` (general translation) |
| Style | Most natural, colloquial dialogue | Natural, slightly more literary | More literal, occasionally stiff |
| Terminology table | Native `src->dst #note` format, injected per line | Native GPT-dictionary format, injected per line | Matched terms only, injected in Hy-MT2's documented reference format |
| Size | 7B (~6.25 GB Q6) | 14B (~8–9 GB iq4xs) | 7B (~6.16 GB Q6) |

On a 2-hour title (1491 cues, same Japanese SRT, RTX 5080), GalTransl translated in
~1m36s vs Sakura-14B's ~2m32s (~1.6× faster) with lower process memory, fewer
adjacent-duplicate translations, and dialogue that read at least as naturally in a
side-by-side sample. Because GalTransl (~6 GB) and the Qwen ASR stack (~6 GB) both fit in
16 GB, they can in principle stay co-resident.

All three leave proper-noun mistakes from the ASR stage untouched (none can fix a misheard
name), and all depend on the recognised Japanese being correct.

**Recommendation:** keep the default GalTransl translator for this kind of visual-novel /
dialogue content. Try `--translator sakura` for a second opinion on long, complex lines,
or `--translator hymt` for more formal/general material.

## Default Behavior

The one-command pipeline uses:

- ASR backend: `qwen` (`models/Qwen3-ASR-1.7B` + `models/Qwen3-ForcedAligner-0.6B`)
- Qwen VAD-cut clips: on (`--qwen-vad-chunks`; disable with `--no-qwen-vad-chunks`)
- Qwen VAD threshold: `--qwen-vad-threshold 0.1` (places speech-cut clips; lower may recover quieter speech but creates more clips)
- Qwen clip length / overlap: `--qwen-chunk-seconds 30` with `--qwen-chunk-overlap-seconds 3`
- Gap recapture: on. After the main pass, subtitle gaps of at least `--qwen-recapture-min-gap 10` seconds get a second VAD look at the more sensitive `--qwen-recapture-vad-threshold 0.05`; gaps with at least `--qwen-recapture-min-speech 2` seconds of detected speech are re-transcribed while the model is still loaded, recovering quiet speech the main VAD missed. Recaptured bare interjections are removed by the same filler filters as the main pass. Disable with `--qwen-recapture-min-gap 0`
- Whisper-style hallucination filtering on Qwen output: off (opt in with `--qwen-filter-hallucinations`)
- Bare filler-interjection dropping on Qwen output: on. Cues that reduce entirely to a single filler mora (うん/ん/ねえ/あ …) and carry no dialogue are removed — either an isolated blip walled by `--qwen-isolated-interjection-silence 3.0` seconds of silence on both sides, or a chain of 3+ such fillers in a row (the signature of VAD slicing a music bed into blips). Only cues that are *entirely* a filler are eligible, so any line containing real words always survives. Disable with `--qwen-isolated-interjection-silence 0` (also turns off the chain rule)
- Filler-repetition collapse: on. A run of the same filler repeated inside one cue (うんうんうん。, or うん、うん、うん、一人。 padding real speech) collapses to a single instance at the token-alignment level, so the surviving cue keeps aligner-exact timing. The run only collapses when both edges sit on punctuation or the cue boundary, so repetition inside real words (ああいう) is never touched; a whole-cue repetition becomes a single filler that the silence/chain gates above then judge as usual. Pass `--collapse-filler-repetition`/`--no-collapse-filler-repetition` to the transcription script for A/B comparison
- Translation backend: `galtransl` (`models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf`); use `--translator sakura` for Sakura-14B or `--translator hymt` for HY-MT
- Source language: Japanese, `ja`
- Translation context: backend-specific default context (galtransl/sakura: previous 6 turns; hymt: previous 2 Chinese translations as Hy-MT2 background information). `--context-size 0` translates each line standalone
- Chinese display timing: 0.5 seconds lead-out and 1.5 seconds minimum display duration
- Gap fill: not used by the Qwen backend (use `--no-qwen-vad-chunks` for a fixed-tiling Qwen comparison, or `--asr whisper --gap-fill` for the legacy recall pass)
- Quality report: enabled by default
- Extracted WAV audio: kept by default

The Qwen backend has no gap-fill stage; its VAD-cut main pass is the only recognition
pass. Tune recall vs. clip count with `--qwen-vad-threshold` (default 0.1; lower keeps
more quiet speech) and `--qwen-vad-max-cluster-gap` (default 2.0; higher merges nearby
speech into fewer, longer clips and runs faster). Use `--no-qwen-vad-chunks` when you
want a fixed-tiling sanity check that does not depend on VAD-found clusters.

### Whisper backend defaults (`--asr whisper`)

When you select the legacy backend, these apply instead:

- ASR model: `models/faster-whisper-large-v3`
- Whisper previous-text conditioning: disabled by default
- Max subtitle display duration: 10 seconds
- VAD: batched sliding-window local VAD over the whole WAV (the only main pass)
- Gap fill: off by default (opt in with `--gap-fill`)

There are no pipeline presets; the single batched sliding-window pass is the
default. Tune recall vs. cleanliness with `--main-local-vad-threshold` (default
0.6; lower keeps more quiet speech but adds hallucinations to filter) and
`--main-local-vad-max-cluster-gap` (default 2.0). The remaining Whisper-specific
detail below applies only to `--asr whisper`.

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
`--main-local-vad-threshold 0.6`, then builds ASR clips from merged speech
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
- `work/input/pipeline.log`: full pipeline log with per-stage timestamps (stdout + stderr of every subprocess). Appended across runs, survives terminal disconnects and reboots.
- `work/input/input.quality.txt`: quality report.
- `work/metrics.jsonl`: one JSON line of key quality metrics per processed video (entries, VAD coverage, kana residue, adjacent duplicates, recapture stats). Shared across videos and runs, for comparing tuning changes over time.
- `outputs/input.zh.srt`: final Chinese SRT.
- `path/to/input.zh.ass`: bilingual ASS copied next to the input video. Bilingual
  output is on by default, so the ASS (not the SRT) is the artifact placed beside the
  video; the Chinese SRT still stays in `outputs/`. With `--no-bilingual`, the Chinese
  SRT is copied next to the video instead.

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

Select the ASR backend (default `qwen`); use the legacy Whisper pipeline with:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper
```

Select the translation backend (default `galtransl`); use Sakura-14B or HY-MT with:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator hymt
```

Run the default Qwen backend with fixed uniform tiling instead of VAD-cut clips
(faster, slightly more drift):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-qwen-vad-chunks
```

The audio-aware gap-fill stage belongs to the Whisper backend; enable it with:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper --gap-fill
```

Disable quality report generation:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --skip-quality-report
```

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
The ASS and quality-report stages always rerun (fast, no GPU). `--resume` implies
`--reuse-existing-audio`:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --bilingual --resume
```

Do not copy the final subtitle file (the bilingual ASS by default, or the SRT with `--no-bilingual`) next to the input video:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-copy-to-video-dir
```

A bilingual ASS (Chinese on top, Japanese below) is written by default. To write only the Chinese SRT instead:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-bilingual
```

This writes `outputs/input.zh.ass` and copies it next to the input video. In
bilingual mode only the ASS is placed beside the video (the SRT is not), while
`outputs/` still keeps both the SRT and the ASS. SRT cannot reliably style each
line differently, so the bilingual output is ASS: the Chinese line is larger and
coloured, the Japanese line is smaller and gray. Defaults can be changed with
`--bilingual-zh-font-size`, `--bilingual-ja-font-size`, `--bilingual-zh-colour`,
`--bilingual-ja-colour` (colours use the ASS `&HAABBGGRR` format), and `--font`
(default `Microsoft YaHei`, which covers both the Chinese and Japanese lines on Windows;
non-Windows players fall back via fontconfig). The Japanese line comes from the
Japanese SRT used for translation (`.ja.srt` by default, `.filled.ja.srt` with
`--gap-fill`), so the two lines stay aligned cue by cue.

In bilingual mode the Chinese line can also be **coloured by speaker gender**
(off by default; enable with `--colour-by-speaker`). Each cue's audio span is
classified male/female by an ECAPA-TDNN voice gender model (VoxCeleb-trained; see
[Download Models](#download-models)), which is far more robust on breathy/music-laden
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
Japanese SRT remains at the real speech timing, so gap filling and quality
analysis are not affected. Standalone translation scripts default to
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

Recover more quiet speech with the Whisper backend's optional gap-fill stage:

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper --gap-fill
```

Gap fill re-examines subtitle gaps and may recover more quiet speech, but it is
slower and can introduce less stable short lines.

Reduce ASR batch size if your GPU runs out of VRAM (`--qwen-batch-size` for the
default Qwen backend, `--main-local-batch-size` for `--asr whisper`):

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --qwen-batch-size 8
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper --main-local-batch-size 8
```

Continue batch processing after one video fails:

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --continue-on-error
```

## Step-by-Step Usage

Transcribe audio to Japanese SRT with the default Qwen backend (VAD-cut clips):

```bash
python scripts/transcribe_ja_srt_qwen.py work/input/input.wav \
  work/input/input.ja.srt \
  --model models/Qwen3-ASR-1.7B \
  --forced-aligner models/Qwen3-ForcedAligner-0.6B \
  --vad-chunks
```

For fast offline post-processing tuning, dump the raw ASR + aligner stream once with
`--raw-output work/input/input.raw.json`, then rebuild cues from it without the model
using `--from-raw work/input/input.raw.json`.

Or transcribe with the legacy Whisper backend:

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output work/input/input.ja.srt \
  --model models/faster-whisper-large-v3 \
  --max-duration 10
```

Fill likely missed Japanese subtitles with WAV audio (Whisper backend only):

```bash
python scripts/fill_ja_srt_gaps.py work/input/input.ja.srt \
  --audio work/input/input.wav \
  --output work/input/input.filled.ja.srt \
  --fills-output work/input/input.fills.ja.srt \
  --fills-metadata-output work/input/input.fills.tsv
```

Translate Japanese SRT to Chinese SRT with the default GalTransl translator:

```bash
python scripts/translate_srt_galtransl.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --context-size 6 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

Or with the Sakura-14B / HY-MT translator (same CLI, different model):

```bash
python scripts/translate_srt_sakura.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --context-size 6 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5

python scripts/translate_srt_hymt.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --model-path models/Hy-MT2-7B-GGUF/HY-MT2-7B-Q6_K.gguf \
  --context-size 2 \
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
Missing Qwen ASR model: .../models/Qwen3-ASR-1.7B
Missing Qwen forced aligner: .../models/Qwen3-ForcedAligner-0.6B
Missing GalTransl model: .../models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf
Missing Whisper model: .../models/faster-whisper-large-v3/model.bin
Missing HY-MT model: .../models/Hy-MT2-7B-GGUF/HY-MT2-7B-Q6_K.gguf
```

Download the models again and keep the default directory and file names. The Qwen and
GalTransl models are only required for the default backends; the Sakura model is only
required for `--translator sakura`, the Whisper model only for `--asr whisper`, and the
HY-MT model only for `--translator hymt`.

### Translation Is Slow

Usually `llama-cpp-python` is running on CPU or the GPU does not have enough VRAM. Run the CUDA check above. CPU translation still works, but long videos will take much longer.

If ASR fails with CUDA out-of-memory, lower the batch size: `--qwen-batch-size` for the
default Qwen backend (default `24`), or `--main-local-batch-size` for `--asr whisper`
(default `24`, throughput-oriented and possibly too high for smaller GPUs).

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

With the default Qwen backend, the VAD decides where speech-cut clips are created. It is
loose by default (`--qwen-vad-threshold 0.1`), but if a speech island is missed it may
not be sent to Qwen. Lower the threshold, raise `--qwen-vad-max-cluster-gap` (default
2.0), or use `--no-qwen-vad-chunks` to tile the whole timeline uniformly so no region is
skipped.

With `--asr whisper`, the sliding-window main pass already scans the whole WAV with
local VAD. If you prefer more recall, lower `--main-local-vad-threshold` (default 0.6)
or raise `--main-local-vad-max-cluster-gap` (default 2.0); both select more audio at the
cost of more clips and more hallucinations to filter.

For even more recall, add `--gap-fill`. It does not judge gaps by duration alone;
it runs per-gap local VAD on each eligible subtitle gap and only re-transcribes
gaps with enough speech, then cleans the results with the same filters as the main
pass.

### Duplicate-Looking Lines

Check the quality report, especially `suspicious_adjacent_duplicates`, `japanese_kana_left`, and `possible_japanese_or_traditional_left`. The ASR step already splits long internal word gaps and merges short adjacent fragments, while translation supplies context as chat history (the current turn carries only the current line), which avoids fusing the previous line into the output at the source. The default GalTransl translator (and Sakura) also self-corrects two failure modes per line: leaked Japanese kana triggers up to two standalone retries (the second with a sampling nudge), and a translation identical to the previous line's while the source differs triggers one standalone retry with a repetition penalty — the duplicate is kept if the model insists, since different sources can genuinely share a rendering. `possible_japanese_or_traditional_left` is a conservative review hint for kanji-only leftovers or non-Simplified characters; it does not filter subtitles automatically.

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
