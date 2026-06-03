# 本地视频字幕生成流水线

[English](README.md) | 中文说明

这个项目用于从本地视频生成简体中文字幕 SRT。当前默认流程面向日语语音，下载好模型后，推理过程全部在本地完成。

## 项目功能

一键流程会执行以下步骤：

1. 用 `ffmpeg` 从视频抽取 16 kHz 单声道 WAV 音频。
2. 用本地 `faster-whisper-large-v3` 识别日语并生成日语 SRT。
3. 结合 WAV 音频和已有日语字幕，自动补识别字幕空窗里的有效语音。
4. 用本地 `HY-MT1.5-7B-GGUF` 把补漏后的日语 SRT 翻译成简体中文字幕 SRT。
5. 输出质量报告，用于检查覆盖率、可能漏识别的语音、疑似重复字幕和中文字幕里的日文残留。

开启二阶段补漏时（默认开启），第 2、3 步会在同一个进程里完成，Whisper 模型只加载一次，而不是加载两次。翻译阶段仍是独立进程，这样 Whisper 和翻译模型不会同时占用显存。所有生成的 SRT 都会排序并消除时间重叠，字幕不会互相重叠或乱序。

项目不依赖在线 API。模型文件不包含在仓库里，也不建议提交到 Git。

## 目录结构

```text
.
├── models/                         # 本地模型目录，不提交
│   ├── faster-whisper-large-v3/     # CTranslate2 格式 Whisper ASR 模型
│   └── HY-MT1.5-7B-GGUF/            # GGUF 翻译模型
├── outputs/                         # 最终中文字幕输出
├── scripts/
│   ├── video_to_zh_srt.py           # 一键视频到中文字幕
│   ├── transcribe_ja_srt.py         # 音频到日语 SRT
│   ├── fill_ja_srt_gaps.py          # 基于 WAV 的日语字幕二阶段补漏
│   ├── quality_report.py            # 字幕质量报告
│   ├── translate_srt_hymt.py        # 日语 SRT 到中文字幕 SRT
│   ├── make_bilingual_ass.py        # 双语 ASS（中文在上，日文在下）
│   └── srt_utils.py                 # 共享的 SRT 解析、时间和区间工具
├── subtitles/
│   ├── ja/                          # 可选：保存日语 SRT
│   └── zh/                          # 可选：保存中文字幕 SRT
├── tests/                           # 纯函数的 pytest 单元测试
└── work/                            # 中间文件（音频、各阶段 SRT）
```

## 运行环境

已验证环境：

- OS：Ubuntu 24.04 / Linux x86_64
- Python：3.11
- FFmpeg：6.1.1
- `faster-whisper`：1.2.1
- `llama-cpp-python`：0.3.23
- `huggingface-hub`：1.15.0

推荐硬件：

- GPU：建议 NVIDIA GPU，显存 12 GB 或以上。
- CPU：建议 8 核以上。
- 内存：建议 16 GB 以上，32 GB 更稳。
- 磁盘：至少预留 10 GB，用于模型和生成文件。

CPU 也可以运行，但长视频会明显更慢。ASR 脚本会优先尝试 CUDA，CUDA 不可用时自动回退到 CPU int8。

## 安装依赖

创建并激活 Python 3.11 虚拟环境：

```bash
python3.11 -m venv .venv
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

默认模型：

- ASR 模型：[`Systran/faster-whisper-large-v3`](https://huggingface.co/Systran/faster-whisper-large-v3)
- 翻译模型：[`tencent/HY-MT1.5-7B-GGUF`](https://huggingface.co/tencent/HY-MT1.5-7B-GGUF)

下载到脚本默认目录：

```bash
mkdir -p models

hf download Systran/faster-whisper-large-v3 \
  --local-dir models/faster-whisper-large-v3

hf download tencent/HY-MT1.5-7B-GGUF HY-MT1.5-7B-Q4_K_M.gguf \
  --local-dir models/HY-MT1.5-7B-GGUF
```

下载完成后，至少应包含：

```text
models/faster-whisper-large-v3/model.bin
models/faster-whisper-large-v3/config.json
models/faster-whisper-large-v3/tokenizer.json
models/faster-whisper-large-v3/vocabulary.json
models/faster-whisper-large-v3/preprocessor_config.json
models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

## 一条命令生成中文字幕

处理单个视频：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4
```

批量处理目录下的常见视频文件：

```bash
python scripts/video_to_zh_srt.py path/to/videos/
```

递归处理子目录：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --recursive
```

如果在 WSL 里处理 Windows 盘里的视频，请使用泛化后的 Linux 挂载路径：

```bash
python scripts/video_to_zh_srt.py "/mnt/<drive>/<path-to-videos>"
```

公开文档、Issue 或日志里不要写入真实本机路径。

## 默认行为

一键流程默认使用：

- 识别模型：`models/faster-whisper-large-v3`
- 翻译模型：`models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf`
- 识别语言：日语 `ja`
- Whisper 前文串联：默认关闭，减少长视频串文和幻觉
- 单条字幕最大显示时长：默认 10 秒
- 翻译上下文：一键流程默认前 1 条原文字幕
- VAD：默认开启，并使用较敏感配置
- 二阶段补漏：默认开启
- 质量报告：默认开启
- 抽取音频：默认保留 WAV，方便复查和调参

当前二阶段补漏默认参数：

- `--fill-min-gap-seconds 10`：只检查 10 秒以上字幕空窗。
- `--fill-min-speech-seconds 4`：空窗内至少有 4 秒 VAD 语音才补识别。
- `--fill-max-clip-seconds 45`：单个补识别音频片段最长 45 秒。
- `--fill-min-chars 3`：过短补漏结果不写入。

## 输出文件

以 `path/to/input.mp4` 为例，默认输出：

- `work/input/input.wav`：抽取出来的 16 kHz 单声道音频。
- `work/input/input.ja.srt`：第一阶段日语字幕。
- `work/input/input.filled.ja.srt`：补漏后的日语字幕，也是默认翻译输入。
- `work/input/input.fills.ja.srt`：二阶段新增的日语字幕片段。
- `work/input/input.quality.txt`：质量报告。
- `outputs/input.zh.srt`：最终中文字幕。
- `path/to/input.zh.srt`：自动拷贝到输入视频同目录的中文字幕。

## 常用参数

指定单个视频的输出路径：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --output outputs/input.zh.srt
```

批量处理时指定输出目录：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --output-dir outputs
```

关闭二阶段补漏：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --skip-gap-fill
```

不生成质量报告：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --skip-quality-report
```

处理完成后删除抽取出来的 WAV：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --delete-audio
```

不把最终字幕拷贝到输入视频同目录：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-copy-to-video-dir
```

同时输出双语字幕（中文在上，日文在下）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --bilingual
```

会在中文 SRT 旁边生成 `outputs/input.zh.ass`，并拷贝到输入视频同目录。SRT 无法可靠地为每一行单独设置样式，所以双语输出用 ASS 格式：中文那行更大、有颜色，日文那行更小、灰白色。默认样式可以用 `--bilingual-zh-font-size`、`--bilingual-ja-font-size`、`--bilingual-zh-colour`、`--bilingual-ja-colour` 调整（颜色用 ASS 的 `&HAABBGGRR` 格式）。下面那行日文用的是参与翻译的补漏后 SRT，因此中日两行逐条对齐。

如果发现翻译把前文一起输出，可以关闭翻译上下文：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

更激进地补漏：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 \
  --fill-min-gap-seconds 6 \
  --fill-min-speech-seconds 2
```

这样可能补出更多低声对白，也可能引入更多不稳定短句。

批量处理时，如果某个视频失败后继续处理后面的视频：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --continue-on-error
```

## 单步运行

只做语音识别：

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output subtitles/ja/input.ja.srt \
  --model models/faster-whisper-large-v3 \
  --max-duration 10
```

对已有日语 SRT 做音频补漏：

```bash
python scripts/fill_ja_srt_gaps.py subtitles/ja/input.ja.srt \
  --audio work/input/input.wav \
  --output subtitles/ja/input.filled.ja.srt \
  --fills-output subtitles/ja/input.fills.ja.srt
```

已有日语 SRT，只做翻译：

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.filled.ja.srt \
  --output subtitles/zh/input.zh.srt \
  --model-path models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf \
  --context-size 1
```

用对齐的日语和中文 SRT 生成双语 ASS：

```bash
python scripts/make_bilingual_ass.py \
  --zh-srt subtitles/zh/input.zh.srt \
  --ja-srt subtitles/ja/input.filled.ja.srt \
  --output subtitles/zh/input.bilingual.ass
```

生成质量报告：

```bash
python scripts/quality_report.py \
  --ja-srt subtitles/ja/input.filled.ja.srt \
  --zh-srt subtitles/zh/input.zh.srt \
  --audio work/input/input.wav \
  --output work/input/input.quality.txt
```

只翻译前 N 条，方便调试：

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.ja.srt \
  --output subtitles/zh/input.sample.zh.srt \
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
Missing Whisper model: .../models/faster-whisper-large-v3/model.bin
Missing HY-MT model: .../models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

按“下载模型”一节重新下载，并确认目录名和文件名没有改动。

### 翻译速度很慢

通常是 `llama-cpp-python` 没有启用 CUDA，或者 GPU 显存不足导致部分层在 CPU 上运行。先按“CUDA 验证”检查。如果无法使用 GPU，可以继续用 CPU 跑，但长视频会很慢。

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

一键流程默认会跑二阶段补漏。它不是只按空窗长度判断，而是先用 VAD 分析 WAV 音频，只对空窗内存在足够语音的片段重新识别。想更激进时，可以降低空窗阈值或语音时长阈值。

### 字幕有重复内容

先查看质量报告里的 `Suspicious adjacent duplicate zh entries`。ASR 阶段会按词级时间戳切分过长内部空隙，并合并很短的相邻片段；翻译阶段也会对相邻重复译文做一次无上下文重试。

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
- 生成的 `outputs/` 和 `subtitles/`
- 虚拟环境和 `__pycache__/`

## 后续改进

- 给 Whisper 增加可配置 `initial_prompt`，用于人名、术语、作品名和场景词。
- 增加可配置术语表，用于修正常见人名、地名、作品名和专有词。
- 继续改进 ASR 后处理，减少孤立符号、无意义短字幕、乱码和片尾噪声词。
