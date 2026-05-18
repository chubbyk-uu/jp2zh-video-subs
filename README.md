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
python -m pip install -r requirements.txt
```

> ⚠️ **注意**：`requirements.txt` 里的 `llama-cpp-python` 默认从 PyPI 拉到的是 **CPU 预编译版**，翻译阶段不会用到 GPU。
> 如果有 NVIDIA GPU，建议在上面一步之后再用源码编译方式覆盖安装 CUDA 版（需要本机已装 CUDA Toolkit + 编译工具链）：
>
> ```bash
> CMAKE_ARGS='-DGGML_CUDA=on' FORCE_CMAKE=1 \
>   python -m pip install --force-reinstall --no-cache-dir llama-cpp-python==0.3.23
> ```
>
> 装完后按下文“CUDA 验证”一节确认输出里能看到 `CUDA` / `offloaded ... layers to GPU`。

安装 FFmpeg：

```bash
sudo apt update
sudo apt install -y ffmpeg
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
python scripts/video_to_zh_srt.py videos/input.mp4
```

默认使用：

- 识别模型：`models/faster-whisper-large-v3`
- 翻译模型：`models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf`
- 识别语言：日语 `ja`
- Whisper 前文串联：默认关闭，减少长视频串文和幻觉
- 单条字幕最大显示时长：默认 10 秒，避免静音段字幕挂太久
- 翻译上下文：默认前 2 条原文字幕；短句、省略号和疑似串文会自动无上下文重翻
- VAD：默认使用较敏感配置，尽量减少低声对白漏检
- 中间文件目录：`work/<视频文件名>/`

运行完成后会生成：

- `work/input/input.ja.srt`：中间日语字幕
- `outputs/input.zh.srt`：最终中文字幕
- `videos/input.zh.srt`：自动拷贝到输入视频同目录的中文字幕

## 常用参数

指定输出路径：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --output outputs/input.zh.srt
```

默认基线已经按 `stable` 配置设置。如果想调整翻译上下文条数：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --context-size 3
```

如果发现翻译把前文一起输出，建议降低上下文：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --context-size 1
```

调整字幕最大显示时长：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --max-duration 8
```

如果想恢复 Whisper 的前文串联行为：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --condition-on-previous-text
```

对长视频和低声对白较多的视频，默认不建议开启该参数。实测它可能补出更多语气词，但也更容易带来重复、串文和碎片化字幕。

保留抽取出来的 WAV 音频，方便调试：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --keep-audio
```

如果不想把最终字幕拷贝到输入视频同目录：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --no-copy-to-video-dir
```

指定临时工作目录：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --work-dir work
```

## 单步运行

只做语音识别：

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output subtitles/ja/input.ja.srt \
  --model models/faster-whisper-large-v3 \
  --max-duration 10
```

已有原文 SRT，只做翻译：

```bash
python scripts/translate_srt_hymt.py subtitles/ja/input.ja.srt \
  --output subtitles/zh/input.zh.srt \
  --model-path models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf \
  --context-size 2
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
python scripts/video_to_zh_srt.py videos/input.mp4
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

翻译脚本默认把前 2 条字幕作为上下文。如果出现译文过长或串入前文，可以降低上下文条数：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --context-size 1
```

脚本也会对短句、省略号、语气词自动禁用上下文，并在译文明显过长时无上下文重翻。

### 字幕时间轴过长

当前 ASR 脚本会启用词级时间戳，并把异常长的字幕控制到 `--max-duration` 以内。默认最大 10 秒，这是目前的 `stable` 基线。如果仍然觉得字幕挂屏太久，可以调到 8 秒：

```bash
python scripts/video_to_zh_srt.py videos/input.mp4 --max-duration 8
```

### 处理非日语视频

当前默认使用 `language="ja"`，因此默认适合日语视频。处理英语、中文或其他语言时，可以传入 `--language`，并相应调整翻译提示词。

## GitHub 提交建议

仓库中已提交：

- `README.md`、`requirements.txt`
- `scripts/`
- `.gitignore` 与各目录的 `.gitkeep` 占位

未提交（已通过 `.gitignore` 排除）：

- `models/`：本地模型，按上文从 Hugging Face 下载
- `videos/`：输入视频
- `work/`：中间文件
- `outputs/`、`subtitles/`：生成结果
- `__pycache__/` 及虚拟环境目录

## 后续改进

- 合并过碎字幕。当前 stable 基线信息量较完整，但低声、喘息和长静音附近可能出现一字或两字字幕，需要把相邻短碎片自动合并。
- 给 Whisper 增加 `initial_prompt` 术语表，提升专有名词、人名、产品词和场景词识别质量。
- 增加术语替换表，用于修正常见识别错误。
- 增加 ASR 后处理，过滤孤立符号、无意义短字幕、英文乱码和片尾噪声词。
- 增加质量报告，列出疑似异常字幕，包括超短碎片、重复短句、时间轴重叠、空白、乱码、日文残留、译文过长等。
- 支持批量处理目录下的多个视频。
- 支持输出原文 SRT、中文字幕 SRT、双语 SRT 等多种格式。
