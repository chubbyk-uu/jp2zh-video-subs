# 本地视频字幕生成流水线

[English](README.md) | 中文说明

这个项目用于从本地视频生成简体中文字幕 SRT，并默认生成中日双语 ASS。当前默认流程面向日语语音，下载好模型后，推理过程全部在本地完成。

项目提供两套识别后端，用 `--asr` 选择：

- **`anime`（默认）**——用 `litagin/anime-whisper` 出文本，WhisperSeg 做弱语音切分，semantic scene 做场景边界，默认 `vad_only` 定时。它是当前 JAV/anime 风格素材的推荐主线。
- **`qwen`**——用 `Qwen3-ASR-1.7B` 出文本内容，配 `Qwen3-ForcedAligner-0.6B` 出时间轴，默认在 WhisperSeg 语音 frame 上识别，并带 aligner fallback recovery。适合作为更干净的文本/时间轴对比线。

以及两套翻译后端，用 `--translator` 选择：

- **`galtransl`（默认）**——`Sakura-GalTransl-7B-v3.7`，针对视觉小说台词做了 GRPO 强化训练的日译中模型。比 Sakura-14B 更小更快、译文更口语，原生支持 `src->dst #备注` 格式的术语表。
- **`sakura`**——`Sakura-14B-Qwen2.5-v1.0`，更大的轻小说/galgame 模型，更重，但在长难句上可作第二意见。

逐项对比与选型建议见 [docs/BACKENDS.md](docs/BACKENDS.md)。

配置文件、默认行为、常用参数、后端对比、单步运行、排障等进阶内容都在 [docs/](docs/) 下（见文末[文档 / 延伸阅读](#文档--延伸阅读)）。

## 项目功能

一键流程会执行以下步骤：

1. 用 `ffmpeg` 从视频抽取 16 kHz 单声道 WAV 音频。
2. 用所选识别后端（默认 `anime`）识别日语并生成日语 SRT。
3. 用所选翻译后端（默认 `galtransl`）把日语 SRT 翻译成简体中文字幕 SRT。
4. 默认生成中日双语 ASS（中文在上、日文在下），并复制到输入视频同目录。
5. 调参/测试时可加 `--quality-report` 输出质量报告，用于检查覆盖率、可能漏识别的语音、疑似重复字幕，以及中文字幕里的日文或非简体残留。

默认的 anime 后端采用 WJ-style 识别框架（semantic scene + WhisperSeg 短语音 frame + `litagin/anime-whisper` 文本 + `vad_only` 定时）；`--asr qwen` 是更干净的文本/时间轴对比线。两条线各自怎么工作、字幕怎么切分详见 [docs/BACKENDS.md](docs/BACKENDS.md)。翻译阶段是独立进程，识别模型和翻译模型不会同时占用显存。所有生成的 SRT 都会排序并消除时间重叠，字幕不会互相重叠或乱序。

批量处理时，视频按文件大小从小到大处理，并且每个视频的音频（第 1 步）会由后台线程提前一个抽取。抽音频是 CPU/IO 密集、识别和翻译是 GPU 密集，所以“当前视频在 GPU 上跑的同时，提前抽下一个视频的音频”能把提取藏进 GPU 时间里，而不是卡在它前面。提取始终保持单路串行读取，以降低机械盘随机 IO 压力；同一块机械盘上不建议同时跑多个流水线。

项目不依赖在线 API。模型文件不包含在仓库里，也不建议提交到 Git。

## 目录结构

```text
.
├── models/                         # 本地模型目录，不提交
│   ├── anime-whisper/               # 默认 anime ASR 文本模型
│   ├── whisperseg/model.onnx        # 默认 anime 弱语音 VAD 模型
│   ├── Qwen3-ASR-1.7B/              # 可选 Qwen ASR 模型（文本内容）
│   ├── Qwen3-ForcedAligner-0.6B/    # 可选 Qwen/anime 对齐诊断模型
│   ├── Sakura-GalTransl-7B-v3.7-GGUF/ # 默认翻译模型
│   ├── Sakura-14B-Qwen2.5-v1.0-GGUF/ # 备选（更大）翻译模型
│   └── voice-gender-classifier/     # 可选 ECAPA 性别模型（双语上色用）
├── outputs/                         # 最终中文字幕输出
├── scripts/
│   ├── video_to_zh_srt.py           # 一键视频到中文字幕
│   ├── transcribe_ja_srt_qwen.py    # 音频到日语 SRT（Qwen/anime 共用后端）
│   ├── quality_report.py            # 字幕质量报告
│   ├── translate_srt_galtransl.py   # 日语 SRT 到中文字幕（默认 Sakura-GalTransl）
│   ├── translate_srt_sakura.py      # 日语 SRT 到中文字幕（Sakura-14B）
│   ├── retime_existing_subtitles.py # 基于已有产物批量重定时并刷新 ASS
│   ├── make_bilingual_ass.py        # 双语 ASS（中文在上，日文在下）+ 说话人性别上色
│   ├── ecapa_gender.py              # vendoring 的 ECAPA-TDNN 声纹性别分类器
│   └── srt_utils.py                 # 共享的 SRT 解析、时间和区间工具
├── docs/                            # 详细文档（后端对比、使用详解）
├── tests/                           # 纯函数与批处理流水线的 pytest 单元测试
└── work/                            # 中间文件（音频、各阶段 SRT）
```

## 运行环境

已验证环境：

- OS：Ubuntu 24.04 / Linux x86_64
- Python：3.11 或 3.12（当前测试主机使用 Python 3.12）
- FFmpeg：6.1.1
- `qwen-asr`：0.0.6（Qwen 识别和可选 forced-aligner 诊断；会带入 `torch`、`transformers`、`librosa`、`soundfile`）
- `onnxruntime-gpu`：1.27.0（默认 anime 后端的 WhisperSeg VAD；由脚本直接导入，不随 `qwen-asr` 带入——CPU-only 主机改装 `onnxruntime`）
- `torch`：2.10，CUDA 12.8（`cu128`），在 RTX 50 系（Blackwell）显卡上验证
- `llama-cpp-python`：0.3.23
- `huggingface-hub`：0.36.2

推荐硬件：

- GPU：建议 NVIDIA GPU，显存 12 GB 左右即可。默认 anime 后端加载 anime-whisper 和 WhisperSeg；Qwen 对比线（1.7B 识别 + 0.6B 对齐）在默认 `--qwen-batch-size 24` 下峰值约 11.5 GB，遇到显存不足把它降到 `16`。翻译是独立进程，不会叠加在识别之上。
- CPU：建议 8 核以上。
- 内存：建议 16 GB 以上，32 GB 更稳。
- 磁盘：至少预留 20 GB，用于模型和生成文件。

默认 anime 后端和 Qwen 对比线都需要 CUDA GPU。

> GPU/驱动提示：`qwen-asr` 基于 PyTorch，安装的 `torch` 必须匹配显卡。在很新的显卡上（如 NVIDIA Blackwell / RTX 50 系），PyPI 默认 wheel 可能没有对应算力的核函数——先装匹配的 CUDA 版本，例如 `pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio`。

## 安装依赖

创建并激活 Python 3.11 或 3.12 虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

安装 FFmpeg：

```bash
sudo apt update
sudo apt install -y ffmpeg
```

`llama-cpp-python` 从 PyPI 安装时通常是 CPU 版。如果希望翻译阶段使用 GPU，需要在安装 CUDA Toolkit 和编译工具链后重新编译安装：

```bash
CMAKE_ARGS='-DGGML_CUDA=on' FORCE_CMAKE=1 \
  python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.23
```

## 下载模型

一键默认流程需要的模型：

- Anime ASR 文本：[`litagin/anime-whisper`](https://huggingface.co/litagin/anime-whisper)
- Anime 弱语音 VAD：[`TransWithAI/Whisper-Vad-EncDec-ASMR-onnx`](https://huggingface.co/TransWithAI/Whisper-Vad-EncDec-ASMR-onnx)
- 翻译模型：[`SakuraLLM/Sakura-GalTransl-7B-v3.7`](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)

可选对比/诊断模型：

- Qwen 对比线：[`Qwen/Qwen3-ASR-1.7B`](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- Qwen forced aligner：[`Qwen/Qwen3-ForcedAligner-0.6B`](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)，`--asr qwen` 和 anime 的 `aligner_fallback` / `aligner_only` 诊断模式需要；默认 anime `vad_only` 不需要

`hf` 命令由 `requirements.txt` 里的 `huggingface-hub` 提供。下载到脚本默认目录：

```bash
mkdir -p models

# 默认 anime 识别后端
hf download litagin/anime-whisper \
  --local-dir models/anime-whisper

mkdir -p models/whisperseg
hf download TransWithAI/Whisper-Vad-EncDec-ASMR-onnx \
  model.onnx \
  --revision 6ac29e2cbf2f4f8e9b639861766a8639dd666e9c \
  --local-dir models/whisperseg

# Qwen 对比线（识别 + 强制对齐；anime forced-aligner 诊断也会用）
hf download Qwen/Qwen3-ASR-1.7B \
  --local-dir models/Qwen3-ASR-1.7B

hf download Qwen/Qwen3-ForcedAligner-0.6B \
  --local-dir models/Qwen3-ForcedAligner-0.6B

# 默认翻译模型（Sakura-GalTransl-7B-v3.7，约 6.25GB 高质量量化档）
hf download SakuraLLM/Sakura-GalTransl-7B-v3.7 \
  Sakura-Galtransl-7B-v3.7.gguf \
  --local-dir models/Sakura-GalTransl-7B-v3.7-GGUF
```

默认流程至少应包含：

```text
models/anime-whisper/config.json
models/anime-whisper/model.safetensors
models/whisperseg/model.onnx
models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf
```

Qwen 对比线 / forced-aligner 诊断还需要：

```text
models/Qwen3-ASR-1.7B/config.json
models/Qwen3-ASR-1.7B/model-00001-of-00002.safetensors
models/Qwen3-ASR-1.7B/model-00002-of-00002.safetensors
models/Qwen3-ForcedAligner-0.6B/config.json
models/Qwen3-ForcedAligner-0.6B/model.safetensors
```

更大的 `sakura` 翻译（`--translator sakura`）改用
[`SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF`](https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF)：

```bash
hf download SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF \
  sakura-14b-qwen2.5-v1.0-iq4xs.gguf \
  --local-dir models/Sakura-14B-Qwen2.5-v1.0-GGUF
```

双语字幕的说话人性别上色（加 `--colour-by-speaker` 开启）需要 ECAPA 声纹性别模型
[`JaesungHuh/voice-gender-classifier`](https://huggingface.co/JaesungHuh/voice-gender-classifier)（约 60 MB，仅依赖 torch）。它是可选的——不下载也能正常输出双语 ASS，只是不上色：

```bash
hf download JaesungHuh/voice-gender-classifier \
  --local-dir models/voice-gender-classifier
```

```text
models/voice-gender-classifier/model.safetensors
models/voice-gender-classifier/config.json
```

## 一条命令生成中文字幕

处理单个视频：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4
```

这条命令就是默认主线：`anime` 识别（anime-whisper + WhisperSeg + semantic scene +
`vad_only` 定时）、`galtransl` 翻译、生成中文 SRT 和双语 ASS。调参/测试时加
`--quality-report` 才生成质量报告。常用变体：

```bash
# 默认识别 + 默认翻译（Anime + GalTransl）
python scripts/video_to_zh_srt.py path/to/input.mp4

# 默认 anime 识别，但关闭 semantic scene 做 A/B 对比
python scripts/video_to_zh_srt.py path/to/input.mp4 --anime-scene-backend none

# Qwen 对比线
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen

# 保持默认 anime 识别，只切换翻译模型
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura
```

批量处理目录下的常见视频文件：

```bash
python scripts/video_to_zh_srt.py path/to/videos/
```

递归处理子目录：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --recursive
```

批量的处理顺序（小文件优先）和音频后台预抽取见开头的[项目功能](#项目功能)，无需额外参数。

如果在 WSL 里处理 Windows 盘里的视频，请使用泛化后的 Linux 挂载路径：

```bash
python scripts/video_to_zh_srt.py "/mnt/<drive>/<path-to-videos>"
```

公开文档、Issue 或日志里不要写入真实本机路径。

更多用法（配置文件、完整默认行为、所有常用参数、单步运行、CUDA 验证、排障）见 [docs/USAGE.md](docs/USAGE.md)。

## 输出文件

以 `path/to/input.mp4` 为例，默认输出：

- `work/input/input.wav`：抽取出来的 16 kHz 单声道音频。
- `work/input/input.ja.srt`：主识别日语字幕，默认也是翻译输入。
- `work/input/pipeline.log`：完整流水线日志，记录每个子进程的时间戳、stdout 和 stderr。追加模式，终端断连或系统重启也不会丢。
- `work/input/input.quality.txt`：质量报告，仅在加 `--quality-report` 时生成。
- `work/metrics.jsonl`：仅在加 `--quality-report` 时，每处理一个视频追加一行 JSON 关键质量指标（条数、VAD 覆盖率、假名残留、相邻重复）。跨视频跨运行共用一个文件，方便对比调参前后的变化。
- `outputs/input.zh.srt`：最终中文字幕。
- `path/to/input.zh.ass`：拷贝到输入视频同目录的双语 ASS。双语输出默认开启，所以放到视频同目录的是 ASS 而**不是** SRT（中文 SRT 仍保留在 `outputs/`）。加 `--no-bilingual` 时，改为把中文 SRT 拷到视频同目录。

日语 SRT 保持识别到的真实语音时间，用于 VAD 覆盖率和质量报告。
中文字幕 SRT 是最终显示字幕：一键流程会轻微延长每条字幕的结束时间，
避免短句在语音结束瞬间立刻消失。双语 ASS 的时间轴来自中文字幕 SRT；
ASS 里的日文只按字幕序号对齐贡献文本。

## 文档 / 延伸阅读

- [docs/BACKENDS.md](docs/BACKENDS.md) — 识别后端（Anime vs Qwen）与翻译后端（GalTransl vs Sakura）逐项对比、工作方式、选型建议。
- [docs/USAGE.md](docs/USAGE.md) — 配置文件、完整默认行为、所有常用参数、单步运行、CUDA 验证、常见问题排障。

## 测试

纯函数部分（SRT 解析、时间换算、区间计算、噪声/重复判定、翻译清洗）有 `pytest` 单元测试覆盖，不需要模型或 GPU：

```bash
python -m pip install pytest
python -m pytest tests/ -q
```

## Git 提交建议

建议提交：

- `README.md`、`README-CN.md`、`docs/`、`requirements.txt`
- `scripts/`
- `tests/`
- `.gitignore` 与目录占位文件

不要提交：

- `models/`
- 私有输入视频
- `work/`
- 生成的 `outputs/`
- 虚拟环境和 `__pycache__/`

## 后续改进

- 继续对比默认 anime 主线和当前 Qwen 对比线，重点看弱语音召回、局部误听和可读性切分。
- 继续优化 Qwen 文本准确率；除非人工复核证明幻觉和尾部漂移不会回退，否则不把长 merge 上下文重新设为默认。
- Qwen 空窗补捞 / recapture 已移除；后续继续通过 WhisperSeg/scene framing 和文本识别质量来提升 Qwen 召回，而不是再跑二次 ASR。
- HY-MT 翻译后端和旧版 Whisper ASR 后端已移除；现在流水线提供两套 ASR 后端（`anime`/`qwen`）和两套翻译后端（`galtransl`/`sakura`）。
- 继续改进 ASR 后处理，减少孤立符号、无意义短字幕、乱码和片尾噪声词。
