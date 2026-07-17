# 使用详解：配置、默认行为、常用参数、单步运行与排障

> 详细文档，仅提供中文。项目总览与上手见 [README-CN.md](../README-CN.md)（中文）/ [README.md](../README.md)（English）。后端逐项对比见 [BACKENDS.md](BACKENDS.md)。

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

TOML 必须是扁平结构；`[asr]`、`[translation]` 这类 section 会被拒绝。`input`/`output` 属于每次运行的 IO 参数，不会出现在 `--print-config` 的输出里，输入路径始终在命令行传入。命令行传入的普通取值参数会覆盖 TOML。`quality_report = true`、`resume = true` 这类单向开关一旦在 TOML 里设为 `true`，同一条命令无法用 `--no-*` 关掉；需要修改 TOML，或为不同模式准备不同配置文件。

## 默认行为

一键流程默认使用：

- 识别后端：`anime`（`models/anime-whisper` + `models/whisperseg/model.onnx` + `models/Qwen3-ForcedAligner-0.6B`）
- Anime semantic scene 预切分：开启（`--anime-scene-backend semantic`；用 `--anime-scene-backend none` 关闭）
- Anime 定时模式：`aligner_fallback`。forced aligner 正常时使用逐字时间；整段或局部 source unit 对齐坍缩时自动回退 VAD。`--anime-timestamp-mode vad_only` 保留用于 A/B，`aligner_only` 仅用于诊断。
- Anime WhisperSeg frame 默认值：`max_group=5.0`、`chunk_threshold=0.5`、`max_speech=5.0`、`min_frame=0.1`、`threshold=0.35`
- Anime semantic scene ASR pad：`--anime-scene-asr-pad-seconds 0.35`，匹配 WhisperJAV 的 padded `asr_processing` scene window；相邻场景的 WhisperSeg 结果会先归并为 canonical frame，避免重叠区重复识别。
- Anime 不使用 Qwen 的 WhisperSeg context `merge` 路径；该参数组只属于 Qwen。
- Anime cleaner：开启，清理省略号-only 片段、句首软省略号和短重复伪迹。forced-align 输出以 anime 原始文本单元为权威，不用纯时间间隙随意切句，再由共享最终清理删除重叠和闪字幕。
- Qwen 对比线：用 `--asr qwen` 开启。默认使用 WhisperSeg frame（`--qwen-vad-backend whisperseg`），Qwen 参数为 `max_group=6.0`、`chunk_threshold=1.0`、`max_speech=5.0`、`min_frame=0.1`、`threshold=0.35`；用 `--asr qwen --no-qwen-vad-chunks` 做固定 30 秒平铺。
- Qwen context 模式：默认 `--qwen-whisperseg-context-mode none`；`merge` 仍可实验，但当前测试里更长的 merge 窗口会增加幻觉，不作为默认。`pad` 模式已移除，因为它是额外 per-frame context expansion，实测容易污染识别。`--qwen-scene-asr-pad-seconds 0.35` 只控制 semantic scene 的 WhisperSeg processing window；无论 `none` 还是 `merge`，最终 Qwen job 都按 owned WhisperSeg frame 的精确首尾切音频。
- Qwen 定时、分句与生成：默认 `--qwen-timestamp-mode aligner_fallback`、`--qwen-scene-backend semantic`、`--qwen-scene-asr-pad-seconds 0.35`、`--qwen-phrase-max-chars 80`、`--qwen-phrase-max-internal-gap 1.5`、`--qwen-max-new-tokens 4096`、`--qwen-repetition-penalty 1.1`、`--qwen-max-tokens-per-second 20.0`。step-down retry 已在共享子脚本实现，但不是顶层默认路径。
- Qwen `vad_only` 定时只作为诊断模式使用。显式设置 `--qwen-timestamp-mode vad_only` 时，必须同时设置 `--qwen-whisperseg-context-mode none`；纯 VAD 定时无法过滤从 merge 上下文里听到的邻近文本，所以管线会拒绝这种组合。
- 对 Qwen 输出的 Whisper 式幻觉过滤：关闭（用 `--asr qwen --qwen-filter-hallucinations` 开启）
- 纯语气词过滤：共享 qwen/anime 子脚本默认开启。整条归一化后只剩一个单语气词（うん/ん/ねえ/あ 等）、不含台词的 cue 会被丢弃——默认 anime 线是两侧各有 `--anime-isolated-interjection-silence 3.0` 秒静默的孤立单条，或连续 3 条及以上的语气词链。只有**整条等于单语气词**的 cue 才会被删，所以任何含实词的台词都会保留。anime 用 `--anime-isolated-interjection-silence 0` 关闭，qwen 用 `--qwen-isolated-interjection-silence 0` 关闭（同时关掉成链规则）。
- 语气词重复拼接折叠：共享 qwen/anime 子脚本默认开启，但只折叠至少 3 次、且每次都由明确标点分隔的失控 filler loop。无标点重复和正常双重复（如「ふふっ」「ねえねえ」「あ、ああ」）保留。anime 可用 `--no-anime-collapse-filler-repetition` 做 A/B，qwen 用 `--no-qwen-collapse-filler-repetition`。
- 通用失控重复折叠：共享 qwen/anime 子脚本默认开启。类似「行く」连续重复很多次的短语 flood 会在最终字幕前折成两个，普通 2-3 次强调会保留。
- 翻译后端：`galtransl`（`models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf`）；用 `--translator sakura` 切 Sakura-14B
- 识别语言：日语 `ja`
- 翻译上下文：GalTransl/Sakura 默认前 6 轮；设为 0 则逐句独立翻译
- 批量翻译（仅 GalTransl，`--translate-batch-size`，默认 8）：把至多 N 条连续字幕（不跨越 >10 秒间隔）作为一轮一起翻译，让被切成多条 cue 的整句能被完整看到，从而纠正省略主语/人称错误——例如跨多条 cue 的第三人称旁白此前会被误译成第一人称。它依赖 GalTransl「不要擅自增减换行」的契约保证输出与输入逐行 1:1；行数不匹配会先拆成更小的严格批量重试，仍不可靠的输出槽位才逐条回退，不会丢掉同块里已经可靠的译文。设为 `0` 或 `1` 关闭批量。
- 中文字幕显示时间：默认尾延 0.5 秒，并保证最短显示 1.5 秒
- 质量报告：生产字幕默认关闭；调参/测试时用 `--quality-report` 开启
- 抽取音频：默认保留 WAV，方便复查和调参

使用 `--asr qwen` 时，Qwen 跑 WhisperSeg-framed 主识别。用
`--qwen-whisperseg-threshold`、`--qwen-whisperseg-max-group`、`--qwen-whisperseg-chunk-threshold`
在召回和切片数之间权衡。需要不依赖语音簇的兜底对比时，用 `--asr qwen --no-qwen-vad-chunks`。

Qwen context `merge` 模式可以让 Qwen 听到多个相邻 WhisperSeg frame，同时保留当前时间轴保护；但当前默认是
`--qwen-whisperseg-context-mode none`。需要调相邻 frame 合并时，用
`--qwen-whisperseg-context-mode merge` 配合
`--qwen-whisperseg-context-target-seconds` / `--qwen-whisperseg-context-merge-gap`。
`target-seconds` 是软目标：未达目标时按 `merge-gap` 桥接间隔，一旦合并窗口超过软目标，容忍度收紧到 `--qwen-whisperseg-context-after-target-gap`（0.2 秒），从而在下一个真实停顿处收尾，而不是等撞到硬上限时被句中硬切；真正的安全上限由
`--qwen-whisperseg-context-hard-max-seconds`（15 秒）控制，只约束真正无停顿的连续语音。`merge`
只把多个相邻 WhisperSeg frame 合并为一个识别窗口；不会向该窗口两端额外加 `--qwen-scene-asr-pad-seconds`。该参数仅用于 WhisperSeg 的 scene processing window。
旧的 `--qwen-whisperseg-context-pre/post-seconds` 和 pad ratio 参数已经从 CLI 删除；旧命令或 TOML 配置需要移除这些参数。

不要把 Qwen `vad_only` 定时和 `merge` 上下文一起开。这个诊断模式没有
aligner ownership filter，Qwen 从邻近上下文里听到的文本可能再次落到当前 VAD
区域里，形成整句重复。只在需要隔离“文本识别质量”和“forced aligner 行为”时使用
`--asr qwen --qwen-timestamp-mode vad_only --qwen-whisperseg-context-mode none`；正式跑
Qwen 字幕时保持默认的 `aligner_fallback + context none` 路径，除非正在显式测试
`merge`。

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

选择识别后端（默认 `anime`），改用 Qwen：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen
```

选择翻译后端（默认 `galtransl`），改用 Sakura-14B：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura
```

### 召回与对比

Qwen 后端用固定均匀平铺代替 WhisperSeg/VAD 切片（适合作为 framing 兜底对比，通常漂移更大）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen --no-qwen-vad-chunks
```

需要调召回时，优先调 WhisperSeg frame 参数，或用 `--asr qwen --no-qwen-vad-chunks`
做固定平铺对比。

### 质量报告、音频和续跑

为调参/测试生成质量报告：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --quality-report
```

质量报告的音频覆盖率检查可以使用 ASR metadata 或 WhisperSeg。一键 anime 路径默认让质量报告使用 WhisperSeg，以匹配 anime 的切分方式；其他路径使用 `auto`。可以用 `--quality-vad-backend metadata`、`whisperseg` 或 `auto` 显式指定。生产字幕通常不需要质量报告。`--skip-quality-report` 仅保留兼容性，因为未指定 `--quality-report` 时本来就不会生成报告。

处理完成后删除抽取出来的 WAV：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --delete-audio
```

也可以使用 GUI 共用的显式清理策略。清理只在任务成功后执行；失败或取消时保留全部可续跑
产物。`final_only` 只删除已知的 WAV、日语 SRT 和对应 ASR metadata，不会直接删除工作目录，
质量报告和 `pipeline.log` 会保留：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --cleanup-policy keep_all
python scripts/video_to_zh_srt.py path/to/input.mp4 --cleanup-policy delete_audio
python scripts/video_to_zh_srt.py path/to/input.mp4 --cleanup-policy final_only
```

旧的 `--delete-audio` 等价于 `--cleanup-policy delete_audio`；不要同时传入冲突策略。

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

### GUI 集成事件与取消

主流水线可以额外写出逐行刷新、UTF-8 编码的 JSONL 事件，供桌面 GUI 实时读取。该功能
不改变默认终端输出；`--event-log` 和 `--cancel-file` 是单次运行控制参数，也不会出现在
`--print-config` 生成的可复用配置中：

```bash
python scripts/video_to_zh_srt.py path/to/videos/ \
  --event-log work/gui-events.jsonl \
  --cancel-file work/gui-cancel.requested
```

事件覆盖批任务、单视频以及 `extract`、`asr`、`translate`、`ass`、`quality`、`cleanup`
阶段的开始、完成、跳过、失败和取消状态，并带任务/阶段序号。模型内部没有可靠百分比时，
事件不会伪造百分比。

调用方创建 `--cancel-file` 指定的文件即可请求取消。流水线会终止当前 FFmpeg、ASR 或翻译
子进程，停止后续阶段和任务，以退出码 130 结束，并保留日志和可用于续跑的中间产物；取消
音频抽取时产生的不完整 `.part` 文件会删除。调用方应为每次运行使用新的取消文件路径，且
在启动前保证该路径不存在。

### 桌面 GUI

Windows 用户可从
[`v0.1.0 Beta 1`](https://github.com/chubbyk-uu/jp2zh-video-subs/releases/tag/v0.1.0-beta.1)
下载绿色版。下载全部 `jp2zh-video-subs-windows-x64-cuda-program.7z.*`
分卷，放在同一目录并从 `.7z.001` 解压，然后按 Release 内的
`INSTALL-CN.txt` 使用包内 `runtime\Scripts\hf.exe` 下载模型。双击
`jp2zh字幕工具.exe` 即可启动；系统无需另装 Python、FFmpeg 或 CUDA Toolkit，
但仍需可用的 NVIDIA 驱动。发布包只包含程序，不包含模型权重或示例视频。

从源码运行 GUI 时，图形依赖独立于基础命令行环境：

```bash
python -m pip install -r requirements-gui.txt
python scripts/run_gui.py
```

主窗口支持：

- 拖入一个或多个视频、拖入文件夹并可选递归扫描；
- 任务去重、移除、清空，以及失败/取消任务重试；
- Anime/Qwen ASR 和 GalTransl/Sakura 翻译模型选择及本地文件完整性提示；
- 输出/工作目录、双语 ASS、质量报告、断点续跑、字幕复制，以及直接影响 ASR 显存与速度的
  批大小策略（性能优先 24、均衡 16、低显存 8、稳定优先 4；默认 24，建议 14 GB 以上
  显存使用，显存不足时逐档降低）；
- 后台检测并显示 PyTorch ASR、ONNX Runtime 语音切分和 llama.cpp 翻译的 CUDA 支持状态；
- 翻译上下文/批大小、自动换行、系统字体下拉框、中文/日文字号和调色板颜色集中在独立的
  双标签高级设置窗口；
- 三档成功后清理策略、实时阶段进度、完整日志和取消；
- 自动记忆窗口、模型和常用参数设置。

文件夹会先展开成 GUI 队列，当前版本固定逐个视频启动现有 CLI，避免并行模型实例叠加显存。
阶段百分比来自版本化 JSONL
事件；后端没有可靠内部百分比时只显示已完成阶段，不推测模型内部进度。Windows x64 CUDA
绿色版已完成程序分卷、全新解压和 RTX 5080 原生验证；其它
NVIDIA 显卡仍缺少实机兼容性证据。缺少 `models\whisperseg\model.onnx`
时，设备栏显示“语音切分 未检测（缺少模型）”；模型存在时才创建真实 ONNX Runtime
会话并区分 CUDA、CPU 和检测失败。更改模型文件后点击“刷新”重新检测。

“复用已完成阶段（断点续跑）”会跳过完整存在的 WAV、日语 SRT 和条数匹配的中文字幕。
更换模型或识别参数后应关闭它，以免继续复用旧的识别结果。长字幕自动换行的默认阈值 20
表示超过 20 个可见字符时尝试在靠近中间的句末标点处分成两行；没有合适标点时不会硬拆，
关闭该开关等价于 `--display-wrap-max-chars 0`。

### 双语 ASS 与样式

默认输出双语字幕（中文在上，日文在下）。若只想要中文 SRT，用 `--no-bilingual`：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --no-bilingual
```

默认会生成 `outputs/input.zh.ass` 并拷贝到输入视频同目录。双语模式下，视频同目录只放 ASS、**不放 SRT**；`outputs/` 里 SRT 和 ASS 都保留。SRT 无法可靠地为每一行单独设置样式，所以双语输出用 ASS 格式：中文那行更大、有颜色，日文那行更小、灰白色。默认样式可以用 `--bilingual-font`（默认 `Microsoft YaHei`，在 Windows 上中日文行均有字形；非 Windows 播放器经 fontconfig 回退）、`--bilingual-zh-font-size`、`--bilingual-ja-font-size`、`--bilingual-zh-colour`、`--bilingual-ja-colour`（颜色用 ASS 的 `&HAABBGGRR` 格式）调整。下面那行日文来自参与翻译的日语 SRT（`.ja.srt`），因此中日两行逐条对齐。

双语模式下还可**按说话人性别给中文那行上色**（默认关闭，加 `--colour-by-speaker` 开启）：对每条字幕从音频里取对应片段，用 ECAPA-TDNN 声纹性别模型（VoxCeleb 训练，见 [README-CN.md 的下载模型](../README-CN.md#下载模型)）判男/女——它在嘈杂/带背景音乐的真实音频上远比纯基频（F0）稳健，不会出现 F0 八度错误导致的男女互判。只有置信度高于 `--gender-confidence`（默认 0.6）的字幕才上色：男声深天蓝、女声粉；不够确定的保持默认黄色，宁可不上色也不上错色。用 `--bilingual-male-colour`、`--bilingual-female-colour` 改配色。未下载该模型时自动跳过上色、输出普通双语 ASS。注意只给中文那行上色，日文那行始终灰白。

调整最终中文字幕和双语 ASS 的显示留白：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

这些参数只影响 `outputs/input.zh.srt` 和生成的 ASS。日语 SRT 仍保持真实
语音时间，所以质量分析不受影响。单独运行翻译脚本时默认是 `0/0`，
保持向后兼容；一键流程默认是 `0.5/1.5`。

对已经跑完的一批视频，只基于现有产物刷新时间轴和 ASS，不重新识别、不重新翻译：

```bash
python scripts/retime_existing_subtitles.py path/to/videos/ \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

这个脚本读取 `outputs/<名称>.zh.srt` 和匹配的日语 SRT：
`work/<名称>/<名称>.ja.srt`。
它会生成 `outputs/<名称>.retimed.zh.srt`、`outputs/<名称>.retimed.zh.ass`，
并把新的 ASS 复制到视频同目录覆盖 `<名称>.zh.ass`。先用 `--dry-run`
可以只检查匹配关系；加 `--no-copy-to-video-dir` 则只写 `outputs/`，不覆盖视频同目录字幕。

### 翻译和资源调参

如果发现翻译把前文一起输出，可以关闭翻译上下文：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --context-size 0
```

如果 Qwen 显卡显存不够，降低 ASR 批大小：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4 --qwen-batch-size 8
```

## 单步运行

用共用 Qwen/anime 子脚本跑默认 anime 识别：

```bash
python scripts/transcribe_ja_srt_qwen.py work/input/input.wav \
  work/input/input.ja.srt \
  --text-backend anime \
  --text-model models/anime-whisper \
  --timestamp-mode aligner_fallback \
  --forced-aligner models/Qwen3-ForcedAligner-0.6B \
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

已有日语 SRT，用默认 GalTransl 翻译：

```bash
python scripts/translate_srt_galtransl.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --context-size 6 \
  --lead-out-seconds 0.5 \
  --min-display-seconds 1.5
```

或用 Sakura-14B 翻译：

```bash
python scripts/translate_srt_sakura.py work/input/input.ja.srt \
  --output outputs/input.zh.srt \
  --context-size 6 \
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

质量报告中的音频覆盖率检查可以使用 `--vad-backend metadata`、`whisperseg` 或 `auto`。ASR 元数据里已有 speech regions 时用 `metadata`；要匹配 anime 主线时用 `whisperseg`。

只翻译前 N 条，方便调试：

```bash
python scripts/translate_srt_galtransl.py work/input/input.ja.srt \
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

## 常见问题

### 模型文件缺失

如果报错类似：

```text
Missing Qwen ASR model: .../models/Qwen3-ASR-1.7B
Missing Qwen forced aligner: .../models/Qwen3-ForcedAligner-0.6B
Missing GalTransl model: .../models/Sakura-GalTransl-7B-v3.7-GGUF/Sakura-Galtransl-7B-v3.7.gguf
```

按 [README-CN.md 的下载模型](../README-CN.md#下载模型) 一节重新下载，并确认目录名和文件名没有改动。默认主线需要 anime-whisper、
WhisperSeg、Qwen forced aligner 和 GalTransl；Qwen ASR 模型只在 `--asr qwen` 时需要；
Sakura 模型只在 `--translator sakura` 时需要。

### 翻译速度很慢

通常是 `llama-cpp-python` 没有启用 CUDA，或者 GPU 显存不足导致部分层在 CPU 上运行。先按“CUDA 验证”检查。如果无法使用 GPU，可以继续用 CPU 跑，但长视频会很慢。

如果是 Qwen ASR 阶段 CUDA 显存不足，降低 `--qwen-batch-size`（默认 `24`）。

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
`--qwen-whisperseg-chunk-threshold`。作为兜底，`--asr qwen --no-qwen-vad-chunks`
会均匀平铺整条时间轴，不跳过任何区域。

### 字幕有重复内容

先查看质量报告里的 `suspicious_adjacent_duplicates`、`japanese_kana_left` 和 `possible_japanese_or_traditional_left`。ASR 阶段会按词级时间戳切分过长内部空隙，并合并很短的相邻片段；翻译阶段把上下文作为对话历史传入（当前轮只放当前句），从源头避免把上一句翻进来。默认的 GalTransl 翻译（以及 Sakura）还会逐句自纠两类失败：译文残留日文假名时最多无历史重试两次（第二次带采样扰动）；译文与上一条相同但原文不同时，带重复惩罚无历史重试一次——如果模型坚持原译则保留重复（不同原文本来就可能共享同一个译法）。`possible_japanese_or_traditional_left` 是针对纯汉字日文残留或非简体字符的保守复查提示，不会自动过滤字幕。
