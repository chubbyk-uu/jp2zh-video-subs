# 本地视频字幕生成流水线

[English](README.md) | 中文说明

这个项目用于从本地视频生成简体中文字幕 SRT。当前默认流程面向日语语音，下载好模型后，推理过程全部在本地完成。

## 项目功能

一键流程会执行以下步骤：

1. 用 `ffmpeg` 从视频抽取 16 kHz 单声道 WAV 音频。
2. 用本地 `faster-whisper-large-v3` 识别日语并生成日语 SRT。
3. 可选运行二阶段补漏（`--gap-fill`），结合 WAV 音频和已有日语字幕补识别字幕空窗里的有效语音。
4. 用本地 `HY-MT1.5-7B-GGUF` 把日语 SRT 翻译成简体中文字幕 SRT。
5. 输出质量报告，用于检查覆盖率、可能漏识别的语音、疑似重复字幕，以及中文字幕里的日文或非简体残留。

默认只跑主识别，很多视频已经能得到覆盖率不错的字幕。需要覆盖更多轻声或漏识别语音时，可以加 `--gap-fill` 跑二阶段补漏；代价是处理更慢，也更可能引入幻觉或听错的字幕，重要输出建议复查质量报告和补漏元数据。开启二阶段补漏时，第 2、3 步会在同一个进程里完成，Whisper 模型只加载一次，而不是加载两次。翻译阶段仍是独立进程，这样 Whisper 和翻译模型不会同时占用显存。所有生成的 SRT 都会排序并消除时间重叠，字幕不会互相重叠或乱序。

批量处理时，视频按文件大小从小到大处理，并且每个视频的音频（第 1 步）会由后台线程提前一个抽取。抽音频是 CPU/IO 密集、识别和翻译是 GPU 密集，所以"当前视频在 GPU 上跑的同时，提前抽下一个视频的音频"能把提取藏进 GPU 时间里，而不是卡在它前面。提取始终保持单路串行读取，以降低机械盘随机 IO 压力；同一块机械盘上不建议同时跑多个流水线。

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
│   ├── retime_existing_subtitles.py # 基于已有产物批量重定时并刷新 ASS
│   ├── make_bilingual_ass.py        # 双语 ASS（中文在上，日文在下）
│   └── srt_utils.py                 # 共享的 SRT 解析、时间和区间工具
├── tests/                           # 纯函数与批处理流水线的 pytest 单元测试
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

批量处理时，视频按文件大小升序处理，最小的最先就绪、GPU 更早开工；同时下一个视频的音频会在后台提取，与当前视频的识别和翻译重叠。无需额外参数，GPU 上也不会并行跑任务。

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
- 翻译上下文：默认带前 1 轮对话历史（上一句原文/译文作为对话上文，当前轮只翻当前句）；设为 0 则逐句独立翻译
- 中文字幕显示时间：默认尾延 0.5 秒，并保证最短显示 1.5 秒
- VAD：整片批处理滑窗局部 VAD（唯一的主识别）
- 二阶段补漏：默认关闭（用 `--gap-fill` 开启）
- 质量报告：默认开启
- 抽取音频：默认保留 WAV，方便复查和调参

没有流程预设了，唯一的批处理滑窗主识别就是默认。用 `--main-local-vad-threshold`
（默认 0.6，调低能捞回更多轻声但幻觉变多）和 `--main-local-vad-max-cluster-gap`
（默认 2.0）在召回和干净度之间权衡。

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
- `work/input/input.quality.txt`：质量报告。
- `outputs/input.zh.srt`：最终中文字幕。
- `path/to/input.zh.srt`：自动拷贝到输入视频同目录的中文字幕。加 `--bilingual` 时，放到视频同目录的是双语 `input.zh.ass`，而**不是** SRT（SRT 仍保留在 `outputs/`）。

加 `--gap-fill` 时，还会额外输出：

- `work/input/input.filled.ja.srt`：补漏后的日语字幕，也是补漏模式下的翻译输入。
- `work/input/input.fills.ja.srt`：二阶段新增的日语字幕片段。
- `work/input/input.fills.tsv`：补漏置信度元数据和过滤原因。

日语 SRT 保持识别到的真实语音时间，用于补漏、VAD 覆盖率和质量报告。
中文字幕 SRT 是最终显示字幕：一键流程会轻微延长每条字幕的结束时间，
避免短句在语音结束瞬间立刻消失。双语 ASS 的时间轴来自中文字幕 SRT；
ASS 里的日文只按字幕序号对齐贡献文本。

## 常用参数

指定单个视频的输出路径：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --output outputs/input.zh.srt
```

批量处理时指定输出目录：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --output-dir outputs
```

默认流程是批处理滑窗主识别、不补漏。若要额外跑二阶段补漏提升召回：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --gap-fill
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

会生成 `outputs/input.zh.ass` 并拷贝到输入视频同目录。双语模式下，视频同目录只放 ASS、**不放 SRT**；`outputs/` 里 SRT 和 ASS 都保留。SRT 无法可靠地为每一行单独设置样式，所以双语输出用 ASS 格式：中文那行更大、有颜色，日文那行更小、灰白色。默认样式可以用 `--bilingual-zh-font-size`、`--bilingual-ja-font-size`、`--bilingual-zh-colour`、`--bilingual-ja-colour` 调整（颜色用 ASS 的 `&HAABBGGRR` 格式）。下面那行日文来自参与翻译的日语 SRT（默认 `.ja.srt`，加 `--gap-fill` 时为 `.filled.ja.srt`），因此中日两行逐条对齐。

调整最终中文字幕和双语 ASS 的显示留白：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

这些参数只影响 `outputs/input.zh.srt` 和生成的 ASS。日语 SRT 仍保持真实
语音时间，所以补漏和质量分析不受影响。单独运行 `translate_srt_hymt.py`
时默认是 `0/0`，保持向后兼容；一键流程默认是 `0.5/1.5`。

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

如果发现翻译把前文一起输出，可以关闭翻译上下文：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

如果显卡显存不够，降低 ASR 批大小：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --main-local-batch-size 8
```

批量处理时，如果某个视频失败后继续处理后面的视频：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ --continue-on-error
```

## 单步运行

只做语音识别：

```bash
python scripts/transcribe_ja_srt.py work/input/input.wav \
  --output work/input/input.ja.srt \
  --model models/faster-whisper-large-v3 \
  --max-duration 10
```

对已有日语 SRT 做音频补漏：

```bash
python scripts/fill_ja_srt_gaps.py work/input/input.ja.srt \
  --audio work/input/input.wav \
  --output work/input/input.filled.ja.srt \
  --fills-output work/input/input.fills.ja.srt \
  --fills-metadata-output work/input/input.fills.tsv
```

已有日语 SRT，只做翻译：

```bash
python scripts/translate_srt_hymt.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --model-path models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf \
  --context-size 1 \
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
Missing Whisper model: .../models/faster-whisper-large-v3/model.bin
Missing HY-MT model: .../models/HY-MT1.5-7B-GGUF/HY-MT1.5-7B-Q4_K_M.gguf
```

按“下载模型”一节重新下载，并确认目录名和文件名没有改动。

### 翻译速度很慢

通常是 `llama-cpp-python` 没有启用 CUDA，或者 GPU 显存不足导致部分层在 CPU 上运行。先按“CUDA 验证”检查。如果无法使用 GPU，可以继续用 CPU 跑，但长视频会很慢。

如果是 ASR 阶段 CUDA 显存不足，优先降低 `--main-local-batch-size`；默认值
`24` 偏向吞吐量，小显存显卡可能需要改成 `12`、`8` 或 `4`。

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

默认主识别已经用滑窗局部 VAD 扫描整段 WAV。想提高召回，可以降低
`--main-local-vad-threshold`（默认 0.6）或提高 `--main-local-vad-max-cluster-gap`
（默认 2.0）；两者都会选中更多音频，也会带来更多需要过滤的幻觉。

如果还想覆盖更多语音，加 `--gap-fill`。它会对字幕空窗跑局部 VAD，只对存在足够语音的
空窗重新识别，并复用主识别清洗过滤。但补漏最容易出现在轻声、背景音或近静音处，
所以更慢，也更可能产生听错或幻觉字幕。

### 字幕有重复内容

先查看质量报告里的 `suspicious_adjacent_duplicates`、`japanese_kana_left` 和 `possible_japanese_or_traditional_left`。ASR 阶段会按词级时间戳切分过长内部空隙，并合并很短的相邻片段；翻译阶段把上下文作为对话历史传入（当前轮只放当前句），从源头避免把上一句翻进来，并在译文残留日文假名时无历史重试一次。`possible_japanese_or_traditional_left` 是针对纯汉字日文残留或非简体字符的保守复查提示，不会自动过滤字幕。

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

- 给 Whisper 增加可配置 `initial_prompt`，用于人名、术语、作品名和场景词。
- 继续改进 ASR 后处理，减少孤立符号、无意义短字幕、乱码和片尾噪声词。
