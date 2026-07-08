# 本地视频字幕生成流水线

[English](README.md) | 中文说明

这个项目用于从本地视频生成简体中文字幕 SRT，并默认生成中日双语 ASS。当前默认流程面向日语语音，下载好模型后，推理过程全部在本地完成。

项目提供三套识别后端，用 `--asr` 选择：

- **`anime`（默认）**——用 `litagin/anime-whisper` 出文本，WhisperSeg 做弱语音切分，semantic scene 做场景边界，默认 `vad_only` 定时。它是当前 JAV/anime 风格素材的推荐主线。
- **`qwen`**——用 `Qwen3-ASR-1.7B` 出文本内容，配 `Qwen3-ForcedAligner-0.6B` 出时间轴，默认在 WhisperSeg 语音 frame 上识别，并带 aligner fallback recovery。适合作为更干净的文本/时间轴对比线。
- **`whisper`**——旧的 `faster-whisper-large-v3` 滑窗主识别，可选 `--gap-fill` 音频补漏阶段。

以及三套翻译后端，用 `--translator` 选择：

- **`galtransl`（默认）**——`Sakura-GalTransl-7B-v3.7`，针对视觉小说台词做了 GRPO 强化训练的日译中模型。比 Sakura-14B 更小更快、译文更口语，原生支持 `src->dst #备注` 格式的术语表。
- **`sakura`**——`Sakura-14B-Qwen2.5-v1.0`，更大的轻小说/galgame 模型，更重，但在长难句上可作第二意见。
- **`hymt`**——`Hy-MT2-7B`，通用翻译模型。

逐项对比见 [识别后端：Anime vs Qwen vs Whisper](#识别后端anime-vs-qwen-vs-whisper) 和 [翻译后端：GalTransl vs Sakura vs HY-MT](#翻译后端galtransl-vs-sakura-vs-hy-mt)。

阅读顺序建议：先看项目功能、安装依赖和下载模型，再看一条命令、默认行为和常用参数。后端对比、单步运行和排障章节用于调参、复查质量或定位失败。

## 项目功能

一键流程会执行以下步骤：

1. 用 `ffmpeg` 从视频抽取 16 kHz 单声道 WAV 音频。
2. 用所选识别后端（默认 `anime`）识别日语并生成日语 SRT。
3. 用所选翻译后端（默认 `galtransl`）把日语 SRT 翻译成简体中文字幕 SRT。
4. 默认生成中日双语 ASS（中文在上、日文在下），并复制到输入视频同目录。
5. 调参/测试时可加 `--quality-report` 输出质量报告，用于检查覆盖率、可能漏识别的语音、疑似重复字幕，以及中文字幕里的日文或非简体残留。

默认的 anime 后端采用 WJ-style 路线：semantic scene 先切 12-48 秒场景，WhisperSeg 在场景内生成短语音 frame，`litagin/anime-whisper` 出文本，默认 `vad_only` 把文本分布到语音区间上。这样可以避开 anime 文本走 forced aligner 时出现的碎片化/坍缩，同时继续使用本项目的字幕塑形、翻译、去重叠和 ASS 生成链。Qwen 仍可用 `--asr qwen` 作为更干净的对比线；anime 也可以用 `--anime-timestamp-mode aligner_fallback` 或 `aligner_only` 强制走对齐器做诊断。翻译阶段是独立进程，识别模型和翻译模型不会同时占用显存。所有生成的 SRT 都会排序并消除时间重叠，字幕不会互相重叠或乱序。

用 `--asr whisper` 时，第 2 步走 Whisper 滑窗主识别，`--gap-fill` 再加一个音频补漏阶段捞回更多轻声/漏识别语音（更慢，也更容易引入幻觉或听错的字幕，重要输出建议复查质量报告和补漏元数据）。

批量处理时，视频按文件大小从小到大处理，并且每个视频的音频（第 1 步）会由后台线程提前一个抽取。抽音频是 CPU/IO 密集、识别和翻译是 GPU 密集，所以"当前视频在 GPU 上跑的同时，提前抽下一个视频的音频"能把提取藏进 GPU 时间里，而不是卡在它前面。提取始终保持单路串行读取，以降低机械盘随机 IO 压力；同一块机械盘上不建议同时跑多个流水线。

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
│   ├── faster-whisper-large-v3/     # 旧版 CTranslate2 Whisper ASR 模型
│   ├── Hy-MT2-7B-GGUF/              # 可选 HY-MT 翻译模型
│   └── voice-gender-classifier/     # 可选 ECAPA 性别模型（双语上色用）
├── outputs/                         # 最终中文字幕输出
├── scripts/
│   ├── video_to_zh_srt.py           # 一键视频到中文字幕
│   ├── transcribe_ja_srt_qwen.py    # 音频到日语 SRT（Qwen/anime 共用后端）
│   ├── transcribe_ja_srt.py         # 音频到日语 SRT（旧版 Whisper 后端）
│   ├── fill_ja_srt_gaps.py          # 基于 WAV 的日语字幕二阶段补漏
│   ├── quality_report.py            # 字幕质量报告
│   ├── translate_srt_galtransl.py   # 日语 SRT 到中文字幕（默认 Sakura-GalTransl）
│   ├── translate_srt_sakura.py      # 日语 SRT 到中文字幕（Sakura-14B）
│   ├── translate_srt_hymt.py        # 日语 SRT 到中文字幕（HY-MT）
│   ├── retime_existing_subtitles.py # 基于已有产物批量重定时并刷新 ASS
│   ├── make_bilingual_ass.py        # 双语 ASS（中文在上，日文在下）+ 说话人性别上色
│   ├── ecapa_gender.py              # vendoring 的 ECAPA-TDNN 声纹性别分类器
│   └── srt_utils.py                 # 共享的 SRT 解析、时间和区间工具
├── tests/                           # 纯函数与批处理流水线的 pytest 单元测试
└── work/                            # 中间文件（音频、各阶段 SRT）
```

## 运行环境

已验证环境：

- OS：Ubuntu 24.04 / Linux x86_64
- Python：3.11 或 3.12（当前测试主机使用 Python 3.12）
- FFmpeg：6.1.1
- `qwen-asr`：0.0.6（Qwen 识别和可选 forced-aligner 诊断；会带入 `torch`、`transformers`、`librosa`、`soundfile`）
- `torch`：2.10，CUDA 12.8（`cu128`），在 RTX 50 系（Blackwell）显卡上验证
- `faster-whisper`：1.2.1（旧版识别后端；质量报告在 `--quality-vad-backend silero` 或 `auto` 选中它时也会使用）
- `llama-cpp-python`：0.3.23
- `huggingface-hub`：0.36.2

推荐硬件：

- GPU：建议 NVIDIA GPU，显存 12 GB 左右即可。默认 anime 后端加载 anime-whisper 和 WhisperSeg；Qwen 对比线（1.7B 识别 + 0.6B 对齐）在默认 `--qwen-batch-size 24` 下峰值约 11.5 GB，遇到显存不足把它降到 `16`。旧版 Whisper 后端约 10 GB。翻译是独立进程，不会叠加在识别之上。
- CPU：建议 8 核以上。
- 内存：建议 16 GB 以上，32 GB 更稳。
- 磁盘：至少预留 20 GB，用于模型和生成文件。

默认 anime 后端和 Qwen 对比线都需要 CUDA GPU。旧版 Whisper 后端（`--asr whisper`）会优先尝试 CUDA，CUDA 不可用时自动回退到 CPU int8；CPU 也能跑，但长视频明显更慢。

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

下载完成后，至少应包含：

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

更大的 `sakura` 翻译（`--translator sakura`）改用
[`SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF`](https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF)：

```bash
hf download SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF \
  sakura-14b-qwen2.5-v1.0-iq4xs.gguf \
  --local-dir models/Sakura-14B-Qwen2.5-v1.0-GGUF
```

可选 `hymt` 翻译（`--translator hymt`）改用
[`tencent/Hy-MT2-7B-GGUF`](https://huggingface.co/tencent/Hy-MT2-7B-GGUF)。
默认建议下载 `HY-MT2-7B-Q6_K.gguf`，效果优先；显存/内存紧张时可换
`Q4_K_M`，想试更大的量化文件可换 `Q8_0`：

```bash
hf download tencent/Hy-MT2-7B-GGUF HY-MT2-7B-Q6_K.gguf \
  --local-dir models/Hy-MT2-7B-GGUF
```

旧版 Whisper 后端（`--asr whisper`）还需要
[`Systran/faster-whisper-large-v3`](https://huggingface.co/Systran/faster-whisper-large-v3)：

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

# Qwen 对比线，并开启 Qwen 空窗补捞（不是 Whisper 的 --gap-fill）
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen \
  --qwen-recapture-min-gap 10 \
  --qwen-recapture-min-speech 2 \
  --qwen-recapture-vad-threshold 0.05

# 旧版 Whisper 识别，并开启 Whisper 二阶段补漏
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper --gap-fill

# 保持默认 anime 识别，只切换翻译模型
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator hymt
```

批量处理目录下的常见视频文件：

```bash
python scripts/video_to_zh_srt.py path/to/videos/
```

递归处理子目录：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --recursive
```

批量处理时，视频按文件大小升序处理，最小的最先就绪、GPU 更早开工；同时下一个视频的音频会在后台提取，与当前视频的识别和翻译重叠。无需额外参数，GPU 上也不会并行跑任务。

如果在 WSL 里处理 Windows 盘里的视频，请使用泛化后的 Linux 挂载路径：

```bash
python scripts/video_to_zh_srt.py "/mnt/<drive>/<path-to-videos>"
```

公开文档、Issue 或日志里不要写入真实本机路径。

## 配置文件

一键命令的用法不变：输入视频或目录仍然写在命令行里。TOML 配置文件是可选功能，主要用来保存一套可复用的调参组合，避免每次输入很长的命令。

打印当前完整生效配置，作为可复用的扁平 TOML 模板：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --print-config > pipeline.toml
```

修改需要固定的值后，用配置文件运行：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --config pipeline.toml
```

配置 key 使用 argparse 的目标名，也就是下划线形式。例如：

```toml
asr = "qwen"
translator = "galtransl"
qwen_batch_size = 16
lead_out_seconds = 0.8
min_display_seconds = 1.5
```

TOML 必须是扁平结构；`[asr]`、`[translation]` 这类 section 会被拒绝。`input`/`output` 属于每次运行的 IO 参数，不会出现在 `--print-config` 的输出里，输入路径始终在命令行传入。命令行传入的普通取值参数会覆盖 TOML。`gap_fill = true`、`quality_report = true`、`resume = true` 这类单向开关一旦在 TOML 里设为 `true`，同一条命令无法用 `--no-*` 关掉；需要修改 TOML，或为不同模式准备不同配置文件。

## 识别后端：Anime vs Qwen vs Whisper

用 `--asr` 选择后端（默认 `anime`）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4                 # Anime（默认）
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen      # Qwen 对比线
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper   # 旧版 Whisper
```

### 默认 Anime 主线的工作方式

1. semantic scene 先把整段音频切成 12-48 秒的声学场景。
2. WhisperSeg 在每个场景内检测并组合短语音 frame，anime 默认与 WJ 对齐：`max_group=5.0`、`chunk_threshold=0.5`、`max_speech=5.0`、`min_frame=0.1`。
3. `litagin/anime-whisper` 逐 frame 识别文本，anime cleaner 清理省略号-only 和短重复伪迹。
4. 默认 `vad_only` 定时把文本分布到检测到的语音区间上，避免 anime 文本走 Qwen forced aligner 时的坍缩/碎片化。

需要对比时可以用 `--asr qwen`；也可用 `--anime-scene-backend none` 关闭 semantic scene 做 A/B。

### Qwen 主线的工作方式

1. Qwen 默认用 WhisperSeg 做 frame（`--qwen-vad-backend whisperseg`），使用 WJ qwen 风格参数：`max_group=6.0`、`chunk_threshold=1.0`、`max_speech=5.0`、`min_frame=0.1`、`threshold=0.35`。
2. 原子 WhisperSeg frame 默认会先合并成更长的 Qwen 识别窗口：`--qwen-whisperseg-context-mode merge`、`merge_gap=2.0`、软 `target=18`、`after_target_gap=0.2`、`hard_max=35`、固定前后各 `2.0` 秒 pad。这样让 Qwen 听到更多上下文，但 cue 归属仍锁在原始语音 frame 上。
3. 合并后的切片分批送入 `Qwen3-ASR-1.7B`；生成参数默认也是 WJ 风格：`max_new_tokens=4096`、`repetition_penalty=1.1`、动态预算 `20` tokens/音频秒。
4. 模型带标点的 `result.text` 作为权威文本内容；单独的 `Qwen3-ForcedAligner-0.6B` 给出逐字时间。句子按标点和较大的内部时间间隙切分，再由对齐器定时。
5. 如果 forced aligner 把一个切片的词压到异常时间段里，Qwen 线会先用 VAD-guided fallback recovery 修复，再进入字幕塑形。semantic scene 和 step-down retry 都已实现但默认关闭；这是 Qwen 消融后的当前选择。

Qwen A/B 对比时，如果想关掉 VAD 切片、回退到固定 30 秒均匀平铺，用
`--asr qwen --no-qwen-vad-chunks`；如果想对比旧的滑窗 VAD 路径，用
`--asr qwen --qwen-vad-backend current`。

### 怎么选

| | **Anime（默认）** | **Qwen（`--asr qwen`）** | **Whisper（`--asr whisper`）** |
|---|---|---|---|
| 文本质量 | 当前 WJ 对比里弱语音召回最好；局部短句仍可能误听 | 正常语音有时更干净；喘息/轻声弱一些 | 安静音频上更易幻觉/循环，需要内置过滤 |
| 时间漂移 | VAD-only 避免 anime forced-aligner 坍缩 | WhisperSeg frame + aligner fallback recovery 明显减少旧 Qwen 的漂移/坍缩问题 | 长段安静处更大 |
| 速度 | Whisper-large 风格逐 frame 生成，慢于批量 Qwen | 批量主识别快；默认不跑补捞 | 主识别相当；`--gap-fill` 多一个更慢的二阶段 |
| 轻声召回 | 当前默认最强；重点复查误听短句 | WhisperSeg 后已有改善，但喘息/轻声仍弱于 anime；可用 recapture 提高覆盖 | 加 `--gap-fill` 进一步提升 |
| 专有名词/人名 | 可能听错人名和生僻词 | 同样可能听错 | 同样弱；三者对没见过的人名都不可靠 |
| 后处理 | anime cleaner + 共享的重叠/闪字幕清理 | 共享清理 + Qwen 失控重复折叠；想要 Whisper 那套过滤用 `--qwen-filter-hallucinations` | 完整的压缩比/循环/去重/幻觉过滤 |
| 显存 | anime-whisper + WhisperSeg；只有非 `vad_only` 诊断模式才加载 aligner | 1.7B + 0.6B，默认 `--qwen-batch-size 24` 约 11.5 GB | large-v3，约 10 GB |

**推荐：** 当前 JAV/anime 风格素材默认使用 Anime 主线。局部误听明显时，用 `--asr qwen` 做对比；需要和旧流程比较，或没有 CUDA 显卡时，再用 Whisper（`--asr whisper`，需要二阶段补漏时加 `--gap-fill`）。

## 翻译后端：GalTransl vs Sakura vs HY-MT

用 `--translator` 选择翻译后端（默认 `galtransl`）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4                       # GalTransl（默认）
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura   # Sakura-14B
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator hymt     # HY-MT
```

三者都是 GGUF 模型，通过 `llama-cpp-python` 在和 ASR 独立的进程里运行，共用同一套 SRT 解析、上下文处理、术语表和显示时序逻辑——只有模型和 prompt 模板不同。GalTransl 和 Sakura 还共用翻译缓存与假名/空译文/相邻重复三类重试；GalTransl 用 `历史翻译` 块承载上文译文（它原生的 v3 格式），Sakura 用 source/译文 对话配对，HY-MT2 按官方单 user prompt 组织，当前句命中的术语才注入，前文中文译文作为背景信息。

| | **GalTransl（默认）** | **Sakura（`--translator sakura`）** | **HY-MT（`--translator hymt`）** |
|---|---|---|---|
| 模型 | `Sakura-GalTransl-7B-v3.7`（视觉小说日译中，GRPO 强化） | `Sakura-14B-Qwen2.5-v1.0`（轻小说/galgame 日译中） | `Hy-MT2-7B`（通用翻译） |
| 风格 | 最自然、口语化的台词 | 自然，略偏书面 | 偏直译，偶尔生硬 |
| 术语表 | 原生 `src->dst #备注` 格式，按句注入 | 原生 GPT 字典格式，按句注入 | 只注入当前句命中的术语，使用 Hy-MT2 官方参考翻译格式 |
| 体量 | 7B（约 6.25 GB Q6） | 14B（约 8–9 GB iq4xs） | 7B（约 6.16 GB Q6） |

GalTransl 是默认翻译后端，主要原因是模型更小、推理更轻，当前项目样例里台词风格也更贴近日常口语。Sakura-14B 更重，适合作为长难句或可疑译文的第二意见；HY-MT 更通用，但对这类台词内容通常更直译。实际速度和显存取决于 GGUF 量化、上下文长度、批大小、`llama-cpp-python` 是否启用 GPU，以及具体显卡。

三者都修不了 ASR 阶段听错的专名（识别错了翻译救不回来），都依赖识别出的日文本身正确。

**推荐：** 这类视觉小说/台词内容保持默认 GalTransl。长难句想要第二意见时试 `--translator sakura`，更正式/通用的内容用 `--translator hymt`。

## 默认行为

一键流程默认使用：

- 识别后端：`anime`（`models/anime-whisper` + `models/whisperseg/model.onnx`）
- Anime semantic scene 预切分：开启（`--anime-scene-backend semantic`；用 `--anime-scene-backend none` 关闭）
- Anime 定时模式：`vad_only`（`--anime-timestamp-mode vad_only`；aligner 诊断模式需要 `models/Qwen3-ForcedAligner-0.6B`）
- Anime WhisperSeg frame 默认值：`max_group=5.0`、`chunk_threshold=0.5`、`max_speech=5.0`、`min_frame=0.1`、`threshold=0.35`
- Anime 不使用 Qwen 的 WhisperSeg context `pad` / `merge` 路径。`vad_only` 定时没有 aligner ownership pass 来过滤邻近上下文，而且目前 anime 评估也没有显示需要这层额外上下文。
- Anime cleaner：开启，清理省略号-only 片段和短重复伪迹；之后仍走共享字幕塑形，删除重叠和闪字幕
- Qwen 对比线：用 `--asr qwen` 开启。默认使用 WhisperSeg frame（`--qwen-vad-backend whisperseg`），Qwen 参数为 `max_group=6.0`、`chunk_threshold=1.0`、`max_speech=5.0`、`min_frame=0.1`、`threshold=0.35`；用 `--asr qwen --qwen-vad-backend current` 对比旧滑窗 VAD 路径，或用 `--asr qwen --no-qwen-vad-chunks` 做固定 30 秒平铺。
- Qwen 长上下文识别：默认开启。原子 WhisperSeg frame 会以 `--qwen-whisperseg-context-mode merge` 合并，默认 `--qwen-whisperseg-context-merge-gap 2.0`、软 `--qwen-whisperseg-context-target-seconds 18`、`--qwen-whisperseg-context-after-target-gap 0.2`、`--qwen-whisperseg-context-hard-max-seconds 35`，并固定前后各补 `--qwen-whisperseg-context-pre-seconds 2.0` / `--qwen-whisperseg-context-post-seconds 2.0` 秒。
- Qwen 定时与生成：默认 `--qwen-timestamp-mode aligner_fallback`、`--qwen-max-new-tokens 4096`、`--qwen-repetition-penalty 1.1`、`--qwen-max-tokens-per-second 20.0`。semantic scene 可用 `--qwen-scene-backend semantic` 打开，但默认关闭；step-down retry 已在共享子脚本实现，但不是顶层默认路径。
- Qwen `vad_only` 定时只作为诊断模式使用。显式设置 `--qwen-timestamp-mode vad_only` 时，必须同时设置 `--qwen-whisperseg-context-mode none`；纯 VAD 定时无法过滤从前后 pad/merge 上下文里听到的邻近文本，所以管线会拒绝这种组合。
- Qwen 空窗补捞：默认关闭（`--qwen-recapture-min-gap 0`），且只适用于 `--asr qwen`。需要高覆盖率的 Qwen 对比时，可设为正数，例如 `--qwen-recapture-min-gap 10`：主识别结束后，对满足长度的字幕空窗用更灵敏的 `--qwen-recapture-vad-threshold 0.05` 再做一遍 VAD；检出语音合计不少于 `--qwen-recapture-min-speech 2` 秒的空窗会趁模型还在显存里二次识别。
- 对 Qwen 输出的 Whisper 式幻觉过滤：关闭（用 `--asr qwen --qwen-filter-hallucinations` 开启）
- 纯语气词过滤：共享 qwen/anime 子脚本默认开启。整条归一化后只剩一个单语气词（うん/ん/ねえ/あ 等）、不含台词的 cue 会被丢弃——默认 anime 线是两侧各有 `--anime-isolated-interjection-silence 3.0` 秒静默的孤立单条，或连续 3 条及以上的语气词链。只有**整条等于单语气词**的 cue 才会被删，所以任何含实词的台词都会保留。anime 用 `--anime-isolated-interjection-silence 0` 关闭，qwen 用 `--qwen-isolated-interjection-silence 0` 关闭（同时关掉成链规则）。
- 语气词重复拼接折叠：共享 qwen/anime 子脚本默认开启。同一条 cue 里同一语气词的连续重复（「うんうんうん。」，或「うん、うん、うん、一人。」这种包着真实台词的）会被折成一个。重复 run 两端必须落在标点或 cue 边界才折叠，所以真词内部的重复（ああいう）绝不会被碰。anime 可用 `--no-anime-collapse-filler-repetition` 做 A/B，qwen 用 `--no-qwen-collapse-filler-repetition`。
- 通用失控重复折叠：共享 qwen/anime 子脚本默认开启。类似「行く」连续重复很多次的短语 flood 会在最终字幕前折成两个，普通 2-3 次强调会保留。
- 翻译后端：`galtransl`（`models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf`）；用 `--translator sakura` 切 Sakura-14B、`--translator hymt` 切 HY-MT
- 识别语言：日语 `ja`
- 翻译上下文：按后端使用不同默认值（galtransl/sakura 默认前 6 轮；hymt 默认前 2 条中文译文作为 Hy-MT2 背景信息）；设为 0 则逐句独立翻译
- 批量翻译（仅 GalTransl，`--translate-batch-size`，默认 8）：把至多 N 条连续字幕（不跨越 >10 秒间隔）作为一轮一起翻译，让被切成多条 cue 的整句能被完整看到，从而纠正省略主语/人称错误——例如跨多条 cue 的第三人称旁白此前会被误译成第一人称。它依赖 GalTransl「不要擅自增减换行」的契约保证输出与输入逐行 1:1；行数不匹配会先拆成更小的严格批量重试，仍不可靠的输出槽位才逐条回退，不会丢掉同块里已经可靠的译文。设为 `0` 或 `1` 关闭批量。
- 中文字幕显示时间：默认尾延 0.5 秒，并保证最短显示 1.5 秒
- Whisper 式二阶段补漏：anime 和 Qwen 后端不使用 `--gap-fill`；Qwen 自己的空窗补捞由 `--asr qwen --qwen-recapture-min-gap > 0` 开启。需要对比时，用 `--asr qwen --no-qwen-vad-chunks` 做固定平铺 Qwen 识别，或用 `--asr whisper --gap-fill` 走旧版补漏。
- 质量报告：生产字幕默认关闭；调参/测试时用 `--quality-report` 开启
- 抽取音频：默认保留 WAV，方便复查和调参

使用 `--asr qwen` 时，Qwen 默认只跑 WhisperSeg-framed 主识别；开启 `--qwen-recapture-min-gap` 后，才会在主识别之后对字幕空窗做一次更灵敏的 VAD+ASR 补捞。用
`--qwen-whisperseg-threshold`、`--qwen-whisperseg-max-group`、`--qwen-whisperseg-chunk-threshold`
在召回和切片数之间权衡；只有想对比旧滑窗 VAD 路径时才使用
`--asr qwen --qwen-vad-backend current` 以及 `--qwen-vad-threshold` 等旧参数。需要不依赖语音簇的兜底对比时，用 `--asr qwen --no-qwen-vad-chunks`。

Qwen 长上下文恢复现在是 Qwen 默认路径，用于让 Qwen 听到更多上下文，同时保留当前时间轴保护。需要回到一帧一切片时，用
`--qwen-whisperseg-context-mode none`；只想补前后音频但不合并 frame 时，用
`--qwen-whisperseg-context-mode pad`；需要调相邻 frame 合并时，用
`--qwen-whisperseg-context-mode merge` 配合
`--qwen-whisperseg-context-target-seconds` / `--qwen-whisperseg-context-merge-gap`。
`target-seconds` 是软目标：未达目标时按 `merge-gap` 桥接间隔，一旦合并窗口超过软目标，容忍度收紧到 `--qwen-whisperseg-context-after-target-gap`（0.2 秒），从而在下一个真实停顿处收尾，而不是等撞到硬上限时被句中硬切；真正的安全上限由
`--qwen-whisperseg-context-hard-max-seconds`（35 秒）控制，只约束真正无停顿的连续语音。前后补音频参数在 `merge`
模式下同样生效；需要动态补音频实验时，使用
`--qwen-whisperseg-context-pad-mode ratio`，再用
`--qwen-whisperseg-context-pad-ratio` 和 min/max pad 限制范围。

不要把 Qwen `vad_only` 定时和 `pad` / `merge` 上下文一起开。这个诊断模式没有
aligner ownership filter，Qwen 从邻近上下文里听到的文本可能再次落到当前 VAD
区域里，形成整句重复。只在需要隔离“文本识别质量”和“forced aligner 行为”时使用
`--asr qwen --qwen-timestamp-mode vad_only --qwen-whisperseg-context-mode none`；正式跑
Qwen 字幕时保持默认的 `aligner_fallback + merge` 路径。

### Whisper 后端默认值（`--asr whisper`）

选用旧版后端时，改为以下默认：

- 识别模型：`models/faster-whisper-large-v3`
- Whisper 前文串联：默认关闭，减少长视频串文和幻觉
- 单条字幕最大显示时长：默认 10 秒
- VAD：整片批处理滑窗局部 VAD（唯一的主识别）
- 二阶段补漏：默认关闭（用 `--gap-fill` 开启）

没有流程预设，唯一的批处理滑窗主识别就是默认。用 `--main-local-vad-threshold`
（默认 0.6，调低能捞回更多轻声但幻觉变多）和 `--main-local-vad-max-cluster-gap`
（默认 2.0）在召回和干净度之间权衡。下面剩余的 Whisper 细节只适用于 `--asr whisper`。

可选的二阶段补漏（`--gap-fill`）会重新检查字幕空窗，捞回偏精度的主识别漏掉的语音。
它对每个达到门槛的空窗跑逐空窗局部 VAD（`--gap-local-vad-threshold 0.60`）；达到
`--gap-local-vad-window-min-gap-seconds 6` 秒的空窗用 5 秒窗口、3 秒重叠扫描，更短的
空窗用单次扫描。候选片段带 `--gap-local-asr-pad-seconds 1.0` 的上下文，
并和主识别走同一个批处理。补漏门槛默认激进
（`--fill-min-gap-seconds 2`、`--fill-min-speech-seconds 1`、`--fill-min-chars 1`、
`--max-fill-compression-ratio 25`），并复用同一套清洗过滤；但额外召回本身比主识别更不稳定。
它会拉长处理时间，也可能带来更多低置信度、幻觉或听错的候选，对准确率要求高时复查
`input.quality.txt` 和 `input.fills.tsv`。

主识别用 8 秒窗口、4 秒重叠、`--main-local-vad-threshold 0.6` 扫描整段 WAV，
再把合并后的语音簇送入 ASR（`--main-local-asr-pad-seconds 0.3`、
`--main-local-vad-max-cluster-gap 2.0`、`--main-local-asr-max-clip-seconds 30`）。所有片段用
`BatchedInferencePipeline` 一次批量转写（`--main-local-batch-size 24`），并限制在 30 秒
Whisper 窗口内以免被截断。`--main-local-vad-dry-run` 可只打印选区覆盖率而不跑 Whisper，便于扫参。
清洗过滤（压缩比、噪声/循环重复、相邻近似去重、重复幻觉过滤，外加
`--min-cue-seconds 0.3` 丢弃 overlap 挤压出的一闪而过 cue）会作用于主识别输出。
同一套批处理转写和清洗也被可选的 `--gap-fill` 阶段复用。

默认 ASR 批大小（`--main-local-batch-size 24`）偏向吞吐量，会占用较多显存。
如果 CUDA 显存不够或显卡较小，优先把它调低，例如 `12`、`8` 或 `4`。

由于激进门槛会对接近静音的片段重新识别，补漏阶段同时会过滤 Whisper 幻觉。硬过滤清单只保留平台/字幕套话
（`ご視聴…`、`チャンネル登録`、`それではまた` 等）以及明显字幕标签/语境错配短语
（`笑い声`、`拍手`、`アーメン`）。问候、感谢、告别等普通对话不会只因为文本命中就被删除。
频次兜底会检查同一视频补漏中重复至少 10 次的短语，但只有该重复组同时像近静音幻觉
（`--hallucination-repeat-no-speech-prob 0.75`）或低置信度
（`--hallucination-repeat-avg-logprob -0.80`）时才自动删除。少量高风险重复短语另有绝对重复上限
（`--hallucination-high-risk-max-repeats 3`）。每条的过滤原因
（`hallucination`、`hallucination_repeat`、`noise`、`context_duplicate` 等）会记录在 `input.fills.tsv` 中。
补漏还会过滤“较长、低置信度、局部 VAD 支持弱”的条目，原因记为
`low_confidence_low_vad_support`；相关默认值包括 `--fill-support-min-chars 8`、
`--fill-support-avg-logprob -0.95`、`--fill-support-no-speech-prob 0.45`、
`--fill-support-vad-threshold 0.5` 和 `--fill-support-max-ratio 0.45`。

## 输出文件

以 `path/to/input.mp4` 为例，默认输出：

- `work/input/input.wav`：抽取出来的 16 kHz 单声道音频。
- `work/input/input.ja.srt`：主识别日语字幕，默认也是翻译输入。
- `work/input/pipeline.log`：完整流水线日志，记录每个子进程的时间戳、stdout 和 stderr。追加模式，终端断连或系统重启也不会丢。
- `work/input/input.quality.txt`：质量报告，仅在加 `--quality-report` 时生成。
- `work/metrics.jsonl`：仅在加 `--quality-report` 时，每处理一个视频追加一行 JSON 关键质量指标（条数、VAD 覆盖率、假名残留、相邻重复、补捞统计）。跨视频跨运行共用一个文件，方便对比调参前后的变化。
- `outputs/input.zh.srt`：最终中文字幕。
- `path/to/input.zh.ass`：拷贝到输入视频同目录的双语 ASS。双语输出默认开启，所以放到视频同目录的是 ASS 而**不是** SRT（中文 SRT 仍保留在 `outputs/`）。加 `--no-bilingual` 时，改为把中文 SRT 拷到视频同目录。

加 `--gap-fill` 时，还会额外输出：

- `work/input/input.filled.ja.srt`：补漏后的日语字幕，也是补漏模式下的翻译输入。
- `work/input/input.fills.ja.srt`：二阶段新增的日语字幕片段。
- `work/input/input.fills.tsv`：补漏置信度元数据和过滤原因。

日语 SRT 保持识别到的真实语音时间，用于补漏、VAD 覆盖率和质量报告。
中文字幕 SRT 是最终显示字幕：一键流程会轻微延长每条字幕的结束时间，
避免短句在语音结束瞬间立刻消失。双语 ASS 的时间轴来自中文字幕 SRT；
ASS 里的日文只按字幕序号对齐贡献文本。

## 常用参数

### 路径与批处理

指定单个视频的输出路径：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --output outputs/input.zh.srt
```

批量处理时指定输出目录：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --output-dir outputs
```

批量处理时，如果某个视频失败后继续处理后面的视频：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --continue-on-error
```

不把最终字幕拷贝到输入视频同目录：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-copy-to-video-dir
```

### 后端选择

选择识别后端（默认 `anime`），改用 Qwen 或旧版 Whisper 流程：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper
```

选择翻译后端（默认 `galtransl`），改用 Sakura-14B 或 HY-MT：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator hymt
```

### 召回与补捞

Qwen 后端用固定均匀平铺代替 WhisperSeg/VAD 切片（适合作为 framing 兜底对比，通常漂移更大）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen --no-qwen-vad-chunks
```

Qwen 后端没有 `--gap-fill` 阶段；它的可选补捞叫 recapture，主识别结束后只检查满足门槛的字幕空窗：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen \
  --qwen-recapture-min-gap 10 \
  --qwen-recapture-min-speech 2 \
  --qwen-recapture-vad-threshold 0.05
```

Whisper 后端的二阶段音频补漏才使用 `--gap-fill`，这样开启：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper --gap-fill
```

### 质量报告、音频和续跑

为调参/测试生成质量报告：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --quality-report
```

质量报告的音频覆盖率检查可以使用 ASR metadata、WhisperSeg 或 Silero/faster-whisper VAD。一键 anime 路径默认让质量报告使用 WhisperSeg，以匹配 anime 的切分方式；其他路径使用 `auto`。可以用 `--quality-vad-backend metadata`、`whisperseg`、`silero` 或 `auto` 显式指定。生产字幕通常不需要质量报告。`--skip-quality-report` 仅保留兼容性，因为未指定 `--quality-report` 时本来就不会生成报告。

处理完成后删除抽取出来的 WAV：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --delete-audio
```

复用已抽取的 WAV、跳过重新 `ffmpeg`（在同一视频上反复跑流程调 ASR/翻译时很方便）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --reuse-existing-audio
```

从中断处续跑——跳过产物已存在且完整的阶段：转写（日语 SRT 存在且非空）、翻译（中文 SRT
条数与源日语 SRT 一致）、音频抽取（WAV 存在且非空）。ASS 始终重新生成（耗时极短，
不占 GPU）；如果加了 `--quality-report`，质量报告也会重新生成。`--resume` 隐含 `--reuse-existing-audio`：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --bilingual --resume
```

### 双语 ASS 与样式

默认输出双语字幕（中文在上，日文在下）。若只想要中文 SRT，用 `--no-bilingual`：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-bilingual
```

默认会生成 `outputs/input.zh.ass` 并拷贝到输入视频同目录。双语模式下，视频同目录只放 ASS、**不放 SRT**；`outputs/` 里 SRT 和 ASS 都保留。SRT 无法可靠地为每一行单独设置样式，所以双语输出用 ASS 格式：中文那行更大、有颜色，日文那行更小、灰白色。默认样式可以用 `--bilingual-font`（默认 `Microsoft YaHei`，在 Windows 上中日文行均有字形；非 Windows 播放器经 fontconfig 回退）、`--bilingual-zh-font-size`、`--bilingual-ja-font-size`、`--bilingual-zh-colour`、`--bilingual-ja-colour`（颜色用 ASS 的 `&HAABBGGRR` 格式）调整。下面那行日文来自参与翻译的日语 SRT（默认 `.ja.srt`，加 `--gap-fill` 时为 `.filled.ja.srt`），因此中日两行逐条对齐。

双语模式下还可**按说话人性别给中文那行上色**（默认关闭，加 `--colour-by-speaker` 开启）：对每条字幕从音频里取对应片段，用 ECAPA-TDNN 声纹性别模型（VoxCeleb 训练，见[下载模型](#下载模型)）判男/女——它在嘈杂/带背景音乐的真实音频上远比纯基频（F0）稳健，不会出现 F0 八度错误导致的男女互判。只有置信度高于 `--gender-confidence`（默认 0.6）的字幕才上色：男声深天蓝、女声粉；不够确定的保持默认黄色，宁可不上色也不上错色。用 `--bilingual-male-colour`、`--bilingual-female-colour` 改配色。未下载该模型时自动跳过上色、输出普通双语 ASS。注意只给中文那行上色，日文那行始终灰白。

调整最终中文字幕和双语 ASS 的显示留白：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

这些参数只影响 `outputs/input.zh.srt` 和生成的 ASS。日语 SRT 仍保持真实
语音时间，所以补漏和质量分析不受影响。单独运行翻译脚本时默认是 `0/0`，
保持向后兼容；一键流程默认是 `0.5/1.5`。

对已经跑完的一批视频，只基于现有产物刷新时间轴和 ASS，不重新识别、不重新翻译：

```bash
python scripts/retime_existing_subtitles.py path/to/videos/ \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

这个脚本读取 `outputs/<名称>.zh.srt` 和匹配的日语 SRT：优先使用
`work/<名称>/<名称>.filled.ja.srt`，没有时回退到 `<名称>.ja.srt`。
它会生成 `outputs/<名称>.retimed.zh.srt`、`outputs/<名称>.retimed.zh.ass`，
并把新的 ASS 复制到视频同目录覆盖 `<名称>.zh.ass`。先用 `--dry-run`
可以只检查匹配关系；加 `--no-copy-to-video-dir` 则只写 `outputs/`，不覆盖视频同目录字幕。

### 翻译和资源调参

如果发现翻译把前文一起输出，可以关闭翻译上下文：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

如果显卡显存不够，降低 ASR 批大小（`--asr qwen` 用 `--qwen-batch-size`，
`--asr whisper` 用 `--main-local-batch-size`）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --qwen-batch-size 8
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr whisper --main-local-batch-size 8
```

## 单步运行

用共用 Qwen/anime 子脚本跑默认 anime 识别：

```bash
python scripts/transcribe_ja_srt_qwen.py work/input/input.wav \
  work/input/input.ja.srt \
  --text-backend anime \
  --text-model models/anime-whisper \
  --timestamp-mode vad_only \
  --vad-backend whisperseg \
  --whisperseg-model models/whisperseg/model.onnx
```

或直接跑 Qwen 对比后端：

```bash
python scripts/transcribe_ja_srt_qwen.py work/input/input.wav \
  work/input/input.ja.srt \
  --text-backend qwen \
  --model models/Qwen3-ASR-1.7B \
  --forced-aligner models/Qwen3-ForcedAligner-0.6B
```

想离线快速调后处理参数，可以先用 `--raw-output work/input/input.raw.json` 把原始
ASR + 对齐器结果导出一次，之后用 `--from-raw work/input/input.raw.json` 跳过模型直接
重建字幕。

或用旧版 Whisper 后端识别：

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output work/input/input.ja.srt \
  --model models/faster-whisper-large-v3 \
  --max-duration 10
```

对已有日语 SRT 做音频补漏（仅 Whisper 后端）：

```bash
python scripts/fill_ja_srt_gaps.py work/input/input.ja.srt \
  --audio work/input/input.wav \
  --output work/input/input.filled.ja.srt \
  --fills-output work/input/input.fills.ja.srt \
  --fills-metadata-output work/input/input.fills.tsv
```

已有日语 SRT，用默认 GalTransl 翻译：

```bash
python scripts/translate_srt_galtransl.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --context-size 6 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

或用 Sakura-14B / HY-MT 翻译（CLI 相同，只换模型）：

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

用对齐的日语和中文 SRT 生成双语 ASS：

```bash
python scripts/make_bilingual_ass.py \
  --zh-srt outputs/input.zh.srt \
  --ja-srt work/input/input.ja.srt \
  --output outputs/input.zh.ass
```

生成质量报告：

```bash
python scripts/quality_report.py \
  --ja-srt work/input/input.ja.srt \
  --zh-srt outputs/input.zh.srt \
  --audio work/input/input.wav \
  --output work/input/input.quality.txt
```

质量报告中的音频覆盖率检查可以使用 `--vad-backend metadata`、`whisperseg`、`silero` 或 `auto`。ASR 元数据里已有 speech regions 时用 `metadata`；要匹配 anime 主线时用 `whisperseg`；要使用旧版 faster-whisper VAD helper 时用 `silero`。

如果已经运行过 `fill_ja_srt_gaps.py`，翻译、ASS 和质量报告都改用
`work/input/input.filled.ja.srt`；质量报告可额外传入
`--fills-metadata work/input/input.fills.tsv`。

只翻译前 N 条，方便调试：

```bash
python scripts/translate_srt_hymt.py work/input/input.ja.srt \
  --output outputs/input.sample.zh.srt \
  --limit 20
```

## CUDA 验证

验证 `llama-cpp-python` 是否启用了 CUDA：

```bash
python - <<'PY'
import llama_cpp
info = llama_cpp.llama_print_system_info()
print(info.decode() if isinstance(info, bytes) else info)
PY
```

如果输出里能看到 `CUDA`、`CUDA0` 或 `offloaded ... layers to GPU`，说明翻译模型可以使用 GPU。

## 测试

纯函数部分（SRT 解析、时间换算、区间计算、噪声/重复判定、翻译清洗）有 `pytest` 单元测试覆盖，不需要模型或 GPU：

```bash
python -m pip install pytest
python -m pytest tests/ -q
```

## 常见问题

### 模型文件缺失

如果报错类似：

```text
Missing Qwen ASR model: .../models/Qwen3-ASR-1.7B
Missing Qwen forced aligner: .../models/Qwen3-ForcedAligner-0.6B
Missing GalTransl model: .../models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf
Missing Whisper model: .../models/faster-whisper-large-v3/model.bin
Missing HY-MT model: .../models/Hy-MT2-7B-GGUF/HY-MT2-7B-Q6_K.gguf
```

按"下载模型"一节重新下载，并确认目录名和文件名没有改动。默认主线需要 anime-whisper、
WhisperSeg 和 GalTransl；Qwen 模型只在 `--asr qwen` 或 anime forced-aligner 诊断模式下需要；
Sakura 模型只在 `--translator sakura` 时需要，Whisper 模型只在 `--asr whisper` 时需要，HY-MT
模型只在 `--translator hymt` 时需要。

### 翻译速度很慢

通常是 `llama-cpp-python` 没有启用 CUDA，或者 GPU 显存不足导致部分层在 CPU 上运行。先按"CUDA 验证"检查。如果无法使用 GPU，可以继续用 CPU 跑，但长视频会很慢。

如果是 ASR 阶段 CUDA 显存不足，降低批大小：`--asr qwen` 用 `--qwen-batch-size`（默认
`24`），`--asr whisper` 用 `--main-local-batch-size`（默认 `24`，偏吞吐量，小显存显卡可能偏高）。

### `ffmpeg` 找不到

安装 FFmpeg，并确认命令在 `PATH` 中：

```bash
sudo apt install -y ffmpeg
ffmpeg -version
```

### 输出字幕串入前文

降低或关闭翻译上下文：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

### 字幕有漏识别

`--asr qwen` 默认由 WhisperSeg 决定哪些语音切片会送入 Qwen。如果整段语音岛被漏掉，先尝试调低
`--qwen-whisperseg-threshold`，或调整 `--qwen-whisperseg-max-group` /
`--qwen-whisperseg-chunk-threshold`。只有要对比旧滑窗 VAD 路径时，才使用
`--asr qwen --qwen-vad-backend current` 以及 `--qwen-vad-threshold`、
`--qwen-vad-max-cluster-gap` 这些参数。作为兜底，`--asr qwen --no-qwen-vad-chunks`
会均匀平铺整条时间轴，不跳过任何区域。

`--asr whisper` 时，主识别已经用滑窗局部 VAD 扫描整段 WAV。想提高召回，可以降低
`--main-local-vad-threshold`（默认 0.6）或提高 `--main-local-vad-max-cluster-gap`
（默认 2.0）；两者都会选中更多音频，也会带来更多需要过滤的幻觉。

Qwen 主线想覆盖更多语音，优先开启空窗补捞，例如 `--qwen-recapture-min-gap 10`。如果使用
`--asr whisper`，再用 `--gap-fill` 开启 Whisper 的二阶段补漏：它会对字幕空窗跑局部 VAD，
只对存在足够语音的空窗重新识别，并复用主识别清洗过滤。但补漏最容易出现在轻声、背景音或近静音处，
所以更慢，也更可能产生听错或幻觉字幕。

### 字幕有重复内容

先查看质量报告里的 `suspicious_adjacent_duplicates`、`japanese_kana_left` 和 `possible_japanese_or_traditional_left`。ASR 阶段会按词级时间戳切分过长内部空隙，并合并很短的相邻片段；翻译阶段把上下文作为对话历史传入（当前轮只放当前句），从源头避免把上一句翻进来。默认的 GalTransl 翻译（以及 Sakura）还会逐句自纠两类失败：译文残留日文假名时最多无历史重试两次（第二次带采样扰动）；译文与上一条相同但原文不同时，带重复惩罚无历史重试一次——如果模型坚持原译则保留重复（不同原文本来就可能共享同一个译法）。`possible_japanese_or_traditional_left` 是针对纯汉字日文残留或非简体字符的保守复查提示，不会自动过滤字幕。

### 补漏字幕置信度偏低或疑似幻觉

补漏字幕是在安静或不确定的音频上补出来的，所以最容易被听错或产生幻觉。流水线会把每条补漏字幕的 Whisper 置信度记录到 `work/<名称>/<名称>.fills.tsv`，质量报告则在 `[Gap Fill Metadata]` 一节汇总，包含 `low_confidence_kept_entries`、`repeated_kept_fill_phrases` 和样例列表。置信度指标含义：

- `avg_logprob`：平均 token 对数概率，**越低越不可信**（低于 `--warn-avg-logprob-below`，默认 `-0.80` 时标记）。
- `no_speech_prob`：该片段不是语音的概率，**越高越可能是在近乎静音处的幻觉**（高于 `--warn-no-speech-prob-above`，默认 `0.50` 时标记）。
- `compression_ratio`：文本重复度，**越高越像重复/乱码**（高于 `--warn-compression-ratio-above`，默认 `2.20` 时标记）。

按样例列表里的时间戳去日语 SRT 里抽查，再按需收紧或放宽阈值。`repeated_kept_fill_phrases` 默认在保留补漏中重复 3 次时只提示复查，不自动删除。极端补漏 `compression_ratio` 会在翻译前由 `--max-fill-compression-ratio` 过滤。注意：它只覆盖二阶段补漏，不含第一阶段主转写。

## Git 提交建议

建议提交：

- `README.md`、`README-CN.md`、`requirements.txt`
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

- Qwen 长上下文工作完成后，回头复盘默认 anime 主线：对比 anime 与当前 Qwen 默认线，核对 WJ anime 参数一致性，在不牺牲时间轴干净度的前提下优化弱语音召回和可读性。
- 继续改进 ASR 后处理，减少孤立符号、无意义短字幕、乱码和片尾噪声词。
