# 本地视频字幕生成流水线

[English](README.md) | 中文说明

这个项目用于从本地日语视频生成简体中文、繁体中文或实验性英文 SRT，并默认生成“译文在上、日文在下”的双语 ASS。下载好模型后，推理过程全部在本地完成。

Windows 用户建议直接使用
[`v0.1.0 Beta 5` 绿色版](https://github.com/chubbyk-uu/jp2zh-video-subs/releases/tag/v0.1.0-beta.5)。
它已内置程序运行时和 FFmpeg，但不附带第三方模型权重；按 Release 里的
`INSTALL-CN.txt` 使用程序根目录下可迁移的 `hf.cmd` 下载模型即可。CLI 仍是完整支持的
源码安装与高级用法入口。

项目提供两套识别后端，用 `--asr` 选择：

- **`anime`（默认）**——用 `litagin/anime-whisper` 出文本，WhisperSeg 做弱语音切分，semantic scene 做场景边界，默认使用 Qwen forced aligner 定时，并在整段或局部对齐坍缩时自动回退 VAD 时间。它是当前 JAV/anime 风格素材的推荐主线。
- **`qwen`**——用 `Qwen3-ASR-1.7B` 出文本内容，配 `Qwen3-ForcedAligner-0.6B` 出时间轴，默认在 WhisperSeg 语音 frame 上识别，并带 aligner fallback recovery。适合作为更干净的文本/时间轴对比线。

以及三套翻译后端，由 `--target-language` 和 `--translator` 兼容选择：

- **`galtransl`（默认）**——`Sakura-GalTransl-7B-v3.7`，针对视觉小说台词做了 GRPO 强化训练的日译中模型。比 Sakura-14B 更小更快、译文更口语，原生支持 `src->dst #备注` 格式的术语表。
- **`sakura`**——`Sakura-14B-Qwen2.5-v1.0`，更大的轻小说/galgame 模型，更重，但在长难句上可作第二意见。
- **`sugoi`（实验性）**——`Sugoi-14B-Ultra`，日译英后端。默认按带编号的 10 条批量翻译，严格校验编号，并带拆分重试和逐条兜底。英文输出仍需人工复核，尤其是人名、说话方向和 ASR 已经听错的台词。

`galtransl`/`sakura` 先生成简体中文；繁体中文随后使用包内 OpenCC 的通用 `s2t`
转换。实验性英文只使用 `sugoi`。GUI 会自动限制为兼容组合。

逐项对比与选型建议见 [docs/BACKENDS.md](docs/BACKENDS.md)。

配置文件、默认行为、常用参数、后端对比、单步运行、排障等进阶内容都在 [docs/](docs/) 下（见文末[文档 / 延伸阅读](#文档--延伸阅读)）。

## 项目功能

一键流程会执行以下步骤：

1. 用 `ffmpeg` 从视频抽取 16 kHz 单声道 WAV 音频。
2. 用所选识别后端（默认 `anime`）识别日语并生成日语 SRT。
3. 翻译为所选目标语言（默认 `zh-Hans`）；`zh-Hant` 会追加 OpenCC `s2t` 转换。
4. 默认生成双语 ASS（译文在上、日文在下），并复制到输入视频同目录。
5. 调参/测试时可加 `--quality-report` 输出按目标语言检查的质量报告。

默认的 anime 后端采用 WJ-style 识别框架（semantic scene + WhisperSeg 短语音 frame + `litagin/anime-whisper` 文本 + forced alignment，并在局部/整段坍缩时回退 VAD）；`--asr qwen` 是更干净的文本/时间轴对比线。两条线各自怎么工作、字幕怎么切分详见 [docs/BACKENDS.md](docs/BACKENDS.md)。翻译阶段是独立进程，识别模型和翻译模型不会同时占用显存。所有生成的 SRT 都会排序并消除时间重叠，字幕不会互相重叠或乱序。

批量处理时，视频按文件大小从小到大处理，并且每个视频的音频（第 1 步）会由后台线程提前一个抽取。抽音频是 CPU/IO 密集、识别和翻译是 GPU 密集，所以“当前视频在 GPU 上跑的同时，提前抽下一个视频的音频”能把提取藏进 GPU 时间里，而不是卡在它前面。提取始终保持单路串行读取，以降低机械盘随机 IO 压力；同一块机械盘上不建议同时跑多个流水线。

项目不依赖在线 API。模型文件不包含在仓库里，也不建议提交到 Git。

## 目录结构

```text
.
├── models/                         # 本地模型目录，不提交
│   ├── anime-whisper/               # 默认 anime ASR 文本模型
│   ├── whisperseg/model.onnx        # 默认 anime 弱语音 VAD 模型
│   ├── Qwen3-ASR-1.7B/              # 可选 Qwen ASR 模型（文本内容）
│   ├── Qwen3-ForcedAligner-0.6B/    # 默认 Anime/Qwen 定时模型
│   ├── Sakura-GalTransl-7B-v3.7-GGUF/ # 默认翻译模型
│   ├── Sakura-14B-Qwen2.5-v1.0-GGUF/ # 备选（更大）翻译模型
│   ├── Sugoi-14B-Ultra-GGUF/           # 可选日译英模型
│   └── voice-gender-classifier/     # 可选 ECAPA 性别模型（双语上色用）
├── outputs/                         # 最终译文字幕输出
├── scripts/
│   ├── video_to_zh_srt.py           # 一键视频到中文字幕
│   ├── transcribe_ja_srt_qwen.py    # 音频到日语 SRT（Qwen/anime 共用后端）
│   ├── quality_report.py            # 字幕质量报告
│   ├── translate_srt_galtransl.py   # 日语 SRT 到中文字幕（默认 Sakura-GalTransl）
│   ├── translate_srt_sakura.py      # 日语 SRT 到中文字幕（Sakura-14B）
│   ├── translate_srt_sugoi.py       # 日语 SRT 到英文字幕（Sugoi）
│   ├── convert_srt_opencc.py        # 简体到繁体 SRT 转换
│   ├── download_models.py            # GUI/CLI 模型下载队列
│   ├── model_catalog.py              # 统一的模型路径与文件要求
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
- `qwen-asr`：0.0.6（Qwen 识别与 forced-aligner 运行时；会带入 `torch`、`transformers`、`librosa`、`soundfile`）
- `onnxruntime-gpu`：1.27.0（默认 anime 后端的 WhisperSeg VAD；由脚本直接导入，不随 `qwen-asr` 带入——CPU-only 主机改装 `onnxruntime`）
- `torch`：2.12，已在 RTX 50 系（Blackwell）显卡上验证
- `llama-cpp-python`：0.3.33（翻译使用 GPU 时需安装 CUDA 构建）
- `numpy`：2.4.6（semantic scene 所用的 `numba` 要求 `<2.5`）
- `huggingface-hub`：0.36.2
- `opencc`：1.4.1（Windows 绿色包运行时内置）

推荐硬件：

- GPU：建议 NVIDIA GPU，显存 12 GB 左右即可。默认 anime 后端依次加载 anime-whisper 和 forced aligner，并使用 WhisperSeg；Qwen 对比线（1.7B 识别 + 0.6B 对齐）在默认 `--qwen-batch-size 24` 下峰值约 11.5 GB，遇到显存不足把它降到 `16`。翻译是独立进程，不会叠加在识别之上。
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
  python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.33
```

## 下载模型

当前开发版 GUI 在模型状态旁新增了“管理模型…”窗口。它可以勾选当前 ASR/翻译配置所需
模型或全部缺失模型，并按界面顺序逐个从 Hugging Face 官方站或第三方 HF-Mirror 下载；
下载优先使用 Hugging Face/Xet 客户端，取消时保留未完整文件供下次续传；窗口内可选填
HTTP 代理，也可以取消“优先使用 Hugging Face/Xet”而直接使用支持断点续传的兼容 HTTP。
HF-Mirror 只用于公开模型，下载器不会把本机缓存的 Hugging Face 私有令牌转发给第三方
镜像。已安装模型可以重新下载，也可以经二次确认后删除。
下载后端选项属于 GUI 和本项目的 `scripts/download_models.py` 辅助程序，不是根目录
Hugging Face `hf.cmd` 支持的参数；项目下载 CLI 示例见
[docs/USAGE.md](https://github.com/chubbyk-uu/jp2zh-video-subs/blob/main/docs/USAGE.md)。

已发布的 Beta 5 早于这个功能，仍需使用程序根目录的 `hf.cmd`。源码安装也可以继续使用
下面的命令。

一键默认流程需要的模型：

- Anime ASR 文本：[`litagin/anime-whisper`](https://huggingface.co/litagin/anime-whisper)
- Anime 弱语音 VAD：[`TransWithAI/Whisper-Vad-EncDec-ASMR-onnx`](https://huggingface.co/TransWithAI/Whisper-Vad-EncDec-ASMR-onnx)
- Anime/Qwen 定时：[`Qwen/Qwen3-ForcedAligner-0.6B`](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)
- 翻译模型：[`SakuraLLM/Sakura-GalTransl-7B-v3.7`](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)

可选对比模型：

- Qwen 对比线：[`Qwen/Qwen3-ASR-1.7B`](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- 实验性英文翻译：[`sugoitoolkit/Sugoi-14B-Ultra-GGUF`](https://huggingface.co/sugoitoolkit/Sugoi-14B-Ultra-GGUF)

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

# 默认 Anime 定时与 Qwen 定时
hf download Qwen/Qwen3-ForcedAligner-0.6B \
  --local-dir models/Qwen3-ForcedAligner-0.6B

# 可选 Qwen 识别对比线
hf download Qwen/Qwen3-ASR-1.7B \
  --local-dir models/Qwen3-ASR-1.7B

# 默认翻译模型（Sakura-GalTransl-7B-v3.7，约 6.25GB 高质量量化档）
hf download SakuraLLM/Sakura-GalTransl-7B-v3.7 \
  Sakura-Galtransl-7B-v3.7.gguf \
  --local-dir models/Sakura-GalTransl-7B-v3.7-GGUF
```

默认流程至少应包含：

```text
models/anime-whisper/config.json
models/anime-whisper/model.safetensors
models/anime-whisper/preprocessor_config.json
models/anime-whisper/tokenizer_config.json
models/whisperseg/model.onnx
models/Qwen3-ForcedAligner-0.6B/config.json
models/Qwen3-ForcedAligner-0.6B/model.safetensors
models/Qwen3-ForcedAligner-0.6B/preprocessor_config.json
models/Qwen3-ForcedAligner-0.6B/tokenizer_config.json
models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf
```

Qwen 对比线还需要：

```text
models/Qwen3-ASR-1.7B/config.json
models/Qwen3-ASR-1.7B/model-00001-of-00002.safetensors
models/Qwen3-ASR-1.7B/model-00002-of-00002.safetensors
```

更大的 `sakura` 翻译（`--translator sakura`）改用
[`SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF`](https://huggingface.co/SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF)：

```bash
hf download SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF \
  sakura-14b-qwen2.5-v1.0-iq4xs.gguf \
  --local-dir models/Sakura-14B-Qwen2.5-v1.0-GGUF
```

实验性英文输出（`--target-language en`）需要 Sugoi 14B Ultra：

```bash
hf download sugoitoolkit/Sugoi-14B-Ultra-GGUF \
  Sugoi-14B-Ultra-Q4_K_M.gguf \
  --local-dir models/Sugoi-14B-Ultra-GGUF
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
forced alignment + VAD fallback 定时）、`galtransl` 翻译、生成中文 SRT 和双语 ASS。调参/测试时加
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

# 繁体中文（中文模型输出后使用通用 OpenCC s2t）
python scripts/video_to_zh_srt.py path/to/input.mp4 --target-language zh-Hant

# 实验性英文（兼容后端为 Sugoi，建议人工复核）
python scripts/video_to_zh_srt.py path/to/input.mp4 --target-language en --translator sugoi
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

## 桌面 GUI

### Windows 绿色测试版

Windows 上最直接的入口是
[`v0.1.0 Beta 5` 绿色版](https://github.com/chubbyk-uu/jp2zh-video-subs/releases/tag/v0.1.0-beta.5)：

1. 下载全部 `jp2zh-video-subs-windows-x64-cuda-program.7z.*` 分卷。
2. 把所有分卷放在同一目录，用 7-Zip 或 NanaZip 从 `.7z.001` 开始解压。
3. 在解压后的 `jp2zh-video-subs` 目录打开命令提示符，按 Release 中的
   `INSTALL-CN.txt` 使用程序根目录下可迁移的 `hf.cmd` 下载必需模型。
4. 双击 `jp2zh-subtitle-tool.exe`。

不需要安装系统 Python、FFmpeg 或 CUDA Toolkit，但必须有正常的 NVIDIA 显卡驱动。
Release 不包含模型权重、用户或示例视频、字幕等内容。第一次启动时，模型完整性提示会列出尚未下载的文件。
`models\whisperseg\model.onnx` 缺失时，设备栏会显示“语音切分 未检测（缺少模型）”，不再猜测为
CPU。模型存在时才通过真实 ONNX Runtime 会话显示 CUDA、CPU 或检测失败；更改模型文件后点击“刷新”重新检测。

GUI 支持拖入视频或文件夹、可见任务队列、Anime/Qwen 识别、独立的简体中文/繁体中文/实验性英文字幕目标、兼容的 GalTransl/Sakura/Sugoi 模型选择、
常用字幕参数、总体进度与详细阶段状态、可折叠日志、取消、设置记忆、模型文件检查，
以及成功后的中间产物清理。文件夹会展开为视频列表并逐个处理，避免多个模型实例叠加显存。

上文[下载模型](#下载模型)介绍的“管理模型…”功能计划随下一版绿色测试包发布；
已发布的 Beta 5 仍使用 `hf.cmd`。

Windows 包内置 Python 3.12、FFmpeg、PyTorch CUDA、ONNX Runtime CUDA 和启用 CUDA 的
llama.cpp。已通过含中文/空格路径重定位、不依赖 WSL 的原生 EXE 启动、安装模型后的三项 CUDA 探测，
以及 Anime + GalTransl 完整流程。发布前还验证了 Qwen + GalTransl、Anime + Sakura 14B 和说话人性别着色。
目前原生 CUDA 证据仅来自一台 RTX 5080，其他 NVIDIA 显卡/驱动组合仍属于 Beta 反馈范围，
不作广泛兼容性保证。

### 从源码启动 GUI

同一套 PySide6 GUI 也可以从源码运行：

```bash
python -m pip install -r requirements-gui.txt
python scripts/run_gui.py
```

GUI 复用现有 CLI 流水线，不维护另一套推理逻辑。`packaging/windows/` 保留了固定版本的运行时输入和可复现的 Windows 组装脚本。

## 输出文件

以 `path/to/input.mp4` 为例，默认输出：

- `work/input/input.wav`：抽取出来的 16 kHz 单声道音频。
- `work/input/input.ja.srt`：主识别日语字幕，默认也是翻译输入。
- `work/input/pipeline.log`：完整流水线日志，记录每个子进程的时间戳、stdout 和 stderr。追加模式，终端断连或系统重启也不会丢。
- `work/input/input.quality.txt`：质量报告，仅在加 `--quality-report` 时生成。
- `work/metrics.jsonl`：仅在加 `--quality-report` 时，每处理一个视频追加一行 JSON 关键质量指标（条数、VAD 覆盖率、假名残留、相邻重复）。跨视频跨运行共用一个文件，方便对比调参前后的变化。
- `outputs/input.zh-s.srt`：最终简体中文字幕；繁体和英文分别使用 `.zh-t.srt`、`.en.srt`。
- `path/to/input.zh-s.ass`：拷贝到输入视频同目录的双语 ASS；另外两种目标使用对应的 `.zh-t.ass`、`.en.ass`。双语输出默认开启，所以放到视频同目录的是 ASS 而**不是** SRT。加 `--no-bilingual` 时改为复制译文 SRT。

日语 SRT 保持识别到的真实语音时间，用于 VAD 覆盖率和质量报告。
译文 SRT 是最终显示字幕：一键流程会轻微延长每条字幕的结束时间，
避免短句在语音结束瞬间立刻消失。双语 ASS 的时间轴来自译文 SRT；
ASS 里的日文只按字幕序号对齐贡献文本。
默认当一条中文字幕超过 20 个可见字符（标点也计数）时，会在最接近中点的
`。？！.!?` 后分为两行显示，但仍是一条 SRT/ASS cue、时间轴不变；没有可用标点时不硬拆。
用 `--display-wrap-max-chars 0` 可关闭，或传入其他阈值调整。
英文默认以 60 个字符作为单行换行触发值，只在单词边界换行，并保持最多两行。此前基于两份、
合计 200 条英文评测字幕，较保守的 42 档已确认处于 1280×720 ASS 安全宽度内；60 的新默认值
用于减少过早换行，仍需在正式发布前完成播放器渲染验收。

## 文档 / 延伸阅读

- [docs/BACKENDS.md](docs/BACKENDS.md) — 识别后端及中英翻译后端逐项对比、工作方式、选型建议。
- [docs/USAGE.md](docs/USAGE.md) — 配置文件、完整默认行为、所有常用参数、单步运行、CUDA 验证、常见问题排障。
- [docs/GUI_TEST_PLAN.md](docs/GUI_TEST_PLAN.md) — GUI 可执行测试矩阵、Windows 绿色版验收用例，以及运行/缺陷记录模板。

## 测试

纯函数部分（SRT 解析、时间换算、区间计算、噪声/重复判定、翻译清洗）有 `pytest` 单元测试覆盖，不需要模型或 GPU：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -q
ruff check scripts tests
```

pytest 与 Ruff 的公共配置位于 `pyproject.toml`，`.editorconfig` 统一 UTF-8、LF
行尾、缩进和文件末尾换行。开始测试前先安装 `requirements.txt`；修改桌面 GUI
时改为安装 `requirements-gui.txt`。CI 目前按决定暂缓，CUDA 推理和 Windows
绿色包验收仍在发布前由本机执行。

## Git 提交建议

建议提交：

- `README.md`、`README-CN.md`、`LICENSE`、`docs/` 下已跟踪的公开文档，以及依赖和开发配置文件
- `scripts/`
- `tests/`
- `.gitignore` 与目录占位文件

不要提交：

- `models/`
- 私有输入视频
- `work/`
- 生成的 `outputs/`
- 本地项目计划 `docs/PLAN.md`
- 虚拟环境和 `__pycache__/`

## 许可证

本仓库原创代码采用 [MIT License](LICENSE)。第三方代码、依赖库、FFmpeg
构建和模型权重继续适用各自的许可证，详见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。其中，MIT 许可证不会覆盖或
取消 GalTransl、Sakura 翻译模型的非商业使用限制。

## 后续改进

- 继续对比默认 anime 主线和当前 Qwen 对比线，重点看弱语音召回、局部误听和可读性切分。
- 继续优化 Qwen 文本准确率；除非人工复核证明幻觉和尾部漂移不会回退，否则不把长 merge 上下文重新设为默认。
- Qwen 空窗补捞 / recapture 已移除；后续继续通过 WhisperSeg/scene framing 和文本识别质量来提升 Qwen 召回，而不是再跑二次 ASR。
- HY-MT 翻译后端和旧版 Whisper ASR 后端已移除；现在流水线提供两套 ASR 后端（`anime`/`qwen`）和三套翻译后端（`galtransl`/`sakura`/`sugoi`），并校验目标语言兼容性。
- 继续改进 ASR 后处理，减少孤立符号、无意义短字幕、乱码和片尾噪声词。
