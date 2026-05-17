# 本地视频字幕生成流水线

这个项目用于把视频自动生成中文字幕 SRT。当前默认流程面向日语语音：

1. 用 `ffmpeg` 从视频抽取 16 kHz 单声道 WAV 音频。
2. 用本地 `faster-whisper-large-v3` 识别日语并生成原文 SRT。
3. 用本地 `HY-MT1.5-7B-GGUF` 把原文 SRT 翻译成简体中文字幕 SRT。

所有推理都在本地运行，不依赖在线 API。首次复现需要先下载模型文件，模型不建议直接提交到 GitHub。

## 目录结构

```text
.
├── models/                         # 本地模型目录，不建议提交到 GitHub
│   ├── faster-whisper-large-v3/     # CTranslate2 格式 Whisper ASR 模型
│   └── HY-MT1.5-7B-GGUF/            # GGUF 翻译模型
├── outputs/                         # 最终中文字幕输出
├── scripts/
│   ├── video_to_zh_srt.py           # 一键视频到中文字幕
│   ├── transcribe_ja_srt.py         # 音频到日语 SRT
│   └── translate_srt_hymt.py        # 原文 SRT 到中文字幕 SRT
├── subtitles/
│   ├── ja/                          # 可选：保存日语 SRT
│   └── zh/                          # 可选：保存中文字幕 SRT
├── videos/                          # 输入视频
└── work/                            # 中间文件
```

## 软硬件环境

已验证环境：

- OS：Ubuntu 24.04 / Linux x86_64
- Python：3.11
- FFmpeg：6.1.1
- `faster-whisper`：1.2.1
- `llama-cpp-python`：0.3.23
- `huggingface-hub`：1.15.0

推荐硬件：

- GPU：建议 NVIDIA GPU，显存 12 GB 或以上更稳。显存不足时可降低并发、改用 CPU，或者换更小的 ASR/翻译模型。
- CPU：建议 8 核以上。
- 内存：建议 16 GB 以上，32 GB 更稳。
- 磁盘：至少预留 10 GB。当前两个默认模型大约占用：
  - `faster-whisper-large-v3`：约 2.9 GB
  - `HY-MT1.5-7B-Q4_K_M.gguf`：约 4.4 GB

CPU 也可以运行，但速度会明显慢。脚本会优先尝试 CUDA；ASR 阶段 CUDA 不可用时会自动回退到 CPU int8。

## 安装依赖

建议使用 Python 3.11 虚拟环境：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
```

安装 Python 依赖：

```bash
python -m pip install faster-whisper==1.2.1 huggingface-hub==1.15.0
python -m pip install llama-cpp-python==0.3.23
```

安装 FFmpeg：

```bash
sudo apt update
sudo apt install -y ffmpeg
```

如果要让 HY-MT 翻译模型使用 NVIDIA GPU，需要安装 CUDA 版 `llama-cpp-python`：

```bash
CMAKE_ARGS='-DGGML_CUDA=on' FORCE_CMAKE=1 \
  python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.23
```

## 下载模型

模型下载自 Hugging Face：

- ASR 模型：[`Systran/faster-whisper-large-v3`](https://huggingface.co/Systran/faster-whisper-large-v3)
- 翻译模型：[`tencent/HY-MT1.5-7B-GGUF`](https://huggingface.co/tencent/HY-MT1.5-7B-GGUF)

使用 `huggingface-hub` 下载到脚本默认目录：

```bash
mkdir -p models

hf download Systran/faster-whisper-large-v3 \
  --local-dir models/faster-whisper-large-v3

hf download tencent/HY-MT1.5-7B-GGUF HY-MT1.5-7B-Q4_K_M.gguf \
  --local-dir models/HY-MT1.5-7B-GGUF
```

下载完成后，目录里至少应包含这些文件：

```text
models/faster-whisper-large-v3/model.bin
models/faster-whisper-large-v3/config.json
models/faster-whisper-large-v3/tokenizer.json
models/faster-whisper-large-v3/vocabulary.json
models/faster-whisper-large-v3/preprocessor_config.json
models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

如果本地 `hf` 命令不可用，先确认虚拟环境已激活，并安装：

```bash
python -m pip install -U huggingface-hub
```

也可以用 Git LFS 下载：

```bash
git lfs install
git clone https://huggingface.co/Systran/faster-whisper-large-v3 models/faster-whisper-large-v3
git clone https://huggingface.co/tencent/HY-MT1.5-7B-GGUF models/HY-MT1.5-7B-GGUF
```

## 一条命令生成中文字幕

把视频放到 `videos/`，然后运行：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt
```

默认使用：

- 识别模型：`models/faster-whisper-large-v3`
- 翻译模型：`models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf`
- 识别语言：日语 `ja`
- 翻译上下文：前 5 条原文字幕
- 中间文件目录：`work/<视频文件名>/`

运行完成后会生成：

- `work/input/input.ja.srt`：中间日语字幕
- `outputs/input.zh.srt`：最终中文字幕

## 常用参数

指定输出路径：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt
```

调整翻译上下文条数：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt --context-size 3
```

保留抽取出来的 WAV 音频，方便调试：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt --keep-audio
```

指定临时工作目录：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt --work-dir work
```

## 单步运行

只做语音识别：

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output subtitles/ja/input.ja.srt \
  --model models/faster-whisper-large-v3
```

已有原文 SRT，只做翻译：

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.ja.srt \
  --output subtitles/zh/input.zh.srt \
  --model-path models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf \
  --context-size 5
```

限制只翻译前 N 条，方便调试：

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

如果输出里能看到 `CUDA`、`CUDA0`、`offloaded ... layers to GPU`，说明翻译模型正在使用 GPU。

如果只看到 CPU 指令集，需要重新安装 CUDA 版：

```bash
CMAKE_ARGS='-DGGML_CUDA=on' FORCE_CMAKE=1 \
  python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.23
```

ASR 阶段由 `faster-whisper` 使用 CUDA。脚本里默认尝试：

```python
WhisperModel(model_name_or_path, device="cuda", compute_type="float16")
```

如果 CUDA 初始化失败，会回退到：

```python
WhisperModel(model_name_or_path, device="cpu", compute_type="int8")
```

## 复现检查清单

运行前确认：

- `ffmpeg -version` 可以正常输出版本。
- `python --version` 是 3.11 或兼容版本。
- `models/faster-whisper-large-v3/model.bin` 存在。
- `models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf` 存在。
- 输入视频路径存在，例如 `videos/input.mp4`。
- `outputs/` 和 `work/` 有写入权限。

最小验证命令：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt
```

如果只想快速确认翻译链路，可以先准备一个很短的 SRT，再用 `--limit` 测试：

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.ja.srt \
  --output outputs/input.sample.zh.srt \
  --limit 5
```

## 常见问题

### 模型文件缺失

报错类似：

```text
Missing Whisper model: .../models/faster-whisper-large-v3/model.bin
Missing HY-MT model: .../models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

按“下载模型”一节重新下载，并确认目录名和文件名没有改动。

### 翻译速度很慢

通常是 `llama-cpp-python` 没有启用 CUDA，或者 GPU 显存不足导致部分层在 CPU 上运行。先按“CUDA 验证”检查。如果无法使用 GPU，可以继续用 CPU 跑，但长视频会很慢。

### `ffmpeg` 找不到

安装 FFmpeg，并确认命令在 PATH 中：

```bash
sudo apt install -y ffmpeg
ffmpeg -version
```

### 输出字幕串入前文

翻译脚本默认把前 5 条字幕作为上下文。如果出现译文过长或串入前文，可以降低上下文条数：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt --context-size 2
```

### 处理非日语视频

当前 `scripts/transcribe_ja_srt.py` 固定使用 `language="ja"`，因此默认适合日语视频。处理英语、中文或其他语言时，需要修改脚本中的 `language` 参数，并相应调整翻译提示词。

## GitHub 提交建议

建议提交：

- `README.md`
- `scripts/`
- 少量示例字幕或短样例

不建议提交：

- `models/`
- `videos/`
- `work/`
- 大体积 `outputs/`
- `__pycache__/`

可以添加 `.gitignore`：

```gitignore
models/
videos/
work/
outputs/
__pycache__/
*.pyc
*.wav
*.mp4
```

## 后续改进

- 支持通过参数指定识别语言，例如 `ja`、`en`、`zh`。
- 给 Whisper 增加 `initial_prompt` 术语表，提升专有名词、人名、产品词和场景词识别质量。
- 把 `condition_on_previous_text` 做成参数，并测试长视频下开启或关闭对幻觉和串文的影响。
- 增加 ASR 后处理，过滤孤立符号、无意义短字幕和片尾噪声词。
- 增加术语替换表，用于修正常见识别错误。
- 翻译阶段检测异常长译文，并自动降低上下文条数重翻。
- 增加质量报告，列出疑似异常字幕，例如超长译文、重复短句、空白或乱码。
- 支持批量处理目录下的多个视频。
- 支持输出原文 SRT、中文字幕 SRT、双语 SRT 等多种格式。
