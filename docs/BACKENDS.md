# 识别与翻译后端对比

> 详细文档，仅提供中文。项目总览与上手见 [README-CN.md](../README-CN.md)（中文）/ [README.md](../README.md)（English）。

用 `--asr` 选识别后端（默认 `anime`）、用 `--translator` 选翻译后端（默认 `galtransl`）。本文逐项对比两条识别线和两个翻译后端，以及各自适用场景。

## 识别后端：Anime vs Qwen

用 `--asr` 选择后端（默认 `anime`）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4                 # Anime（默认）
python scripts/video_to_zh_srt.py path/to/input.mp4 --asr qwen      # Qwen 对比线
```

### 默认 Anime 主线的工作方式

1. semantic scene 先把整段音频切成 12-48 秒的声学场景。
2. WhisperSeg 在每个场景内检测并组合短语音 frame，anime 默认与 WJ 对齐：`max_group=5.0`、`chunk_threshold=0.5`、`max_speech=5.0`、`min_frame=0.1`。
3. `litagin/anime-whisper` 逐 frame 识别文本，anime cleaner 清理省略号-only 和短重复伪迹。
4. 默认 `vad_only` 保持 frame 时间轴、整帧不拆，只做基于长度的可读性切分：超过 50 个内容字符的长段可在逗号处切，逗号-less 长段最多 80 个内容字符硬切；句末标点和 `…` 都不切（anime-whisper 在每个软停顿都撒句末标点，按它切会碎成一闪而过的短字幕）。这样避免 anime 文本走 Qwen forced aligner 时的坍缩/碎片化，同时保证字幕停留时间够长、能读完。

需要对比时可以用 `--asr qwen`；也可用 `--anime-scene-backend none` 关闭 semantic scene 做 A/B。

### Qwen 主线的工作方式

1. Qwen 默认用 WhisperSeg 做 frame（`--qwen-vad-backend whisperseg`），使用 WJ qwen 风格参数：`max_group=6.0`、`chunk_threshold=1.0`、`max_speech=5.0`、`min_frame=0.1`、`threshold=0.35`。
2. Qwen 默认直接使用短 WhisperSeg frame（`--qwen-whisperseg-context-mode none`）。`merge` 仍可用于实验，但当前测试里更长的 merge 窗口会增加 Qwen 幻觉和尾部漂移，所以不是默认。`pad` 模式及其 pre/post/ratio 参数已从 CLI 删除；它曾是额外 per-frame context expansion，和 semantic scene processing window 不是一回事。无论 `none` 还是 `merge`，Qwen 都只听 owned WhisperSeg frame 的精确首尾；`--qwen-scene-asr-pad-seconds 0.35` 只扩展 WhisperSeg 的 scene 输入窗口，不会扩展最终 Qwen job。
3. 切片分批送入 `Qwen3-ASR-1.7B`；生成参数默认也是 WJ 风格：`max_new_tokens=4096`、`repetition_penalty=1.1`、动态预算 `20` tokens/音频秒。
4. 模型带标点的 `result.text` 作为权威文本内容；单独的 `Qwen3-ForcedAligner-0.6B` 给出逐字时间。句子按标点和较大的内部时间间隙切分，再由对齐器定时。同一 clip 内相邻 cue 只有在间隔小于 1.5 秒且合并后不超过 80 个内容字符 / 8 秒时才会合并。
5. Qwen 默认开启 semantic scene，让 WhisperSeg frame 不跨声学场景边界。如果 forced aligner 把一个切片的词压到异常时间段里，Qwen 线会先用 VAD-guided fallback recovery 修复，再进入字幕塑形。step-down retry 已实现但默认关闭。

Qwen A/B 对比时，如果想关掉 VAD 切片、回退到固定 30 秒均匀平铺，用
`--asr qwen --no-qwen-vad-chunks`。

### 怎么选

| | **Anime（默认）** | **Qwen（`--asr qwen`）** |
|---|---|---|
| 文本质量 | 当前 WJ 对比里弱语音召回最好；局部短句仍可能误听 | 正常语音有时更干净；喘息/轻声弱一些 |
| 时间漂移 | VAD-only 避免 anime forced-aligner 坍缩 | WhisperSeg frame + aligner fallback recovery 明显减少旧 Qwen 的漂移/坍缩问题 |
| 速度 | Whisper-large 风格逐 frame 生成，慢于批量 Qwen | 批量主识别快 |
| 轻声召回 | 当前默认最强；重点复查误听短句 | WhisperSeg 后已有改善，但喘息/轻声仍弱于 anime |
| 专有名词/人名 | 可能听错人名和生僻词 | 同样可能听错 |
| 后处理 | anime cleaner + 共享的重叠/闪字幕清理 | 共享清理 + Qwen 失控重复折叠；想要额外幻觉过滤用 `--qwen-filter-hallucinations` |
| 显存 | anime-whisper + WhisperSeg；只有非 `vad_only` 诊断模式才加载 aligner | 1.7B + 0.6B，默认 `--qwen-batch-size 24` 约 11.5 GB |

**推荐：** 当前 JAV/anime 风格素材默认使用 Anime 主线。局部误听明显时，用 `--asr qwen` 做对比。

## 翻译后端：GalTransl vs Sakura

用 `--translator` 选择翻译后端（默认 `galtransl`）：

```bash
python scripts/video_to_zh_srt.py path/to/input.mp4                       # GalTransl（默认）
python scripts/video_to_zh_srt.py path/to/input.mp4 --translator sakura   # Sakura-14B
```

两者都是 GGUF 模型，通过 `llama-cpp-python` 在和 ASR 独立的进程里运行，共用同一套 SRT 解析、上下文处理、术语表和显示时序逻辑——只有模型和 prompt 模板不同。GalTransl 和 Sakura 还共用翻译缓存与假名/空译文/相邻重复三类重试；GalTransl 用 `历史翻译` 块承载上文译文（它原生的 v3 格式），Sakura 用 source/译文 对话配对。

| | **GalTransl（默认）** | **Sakura（`--translator sakura`）** |
|---|---|---|
| 模型 | `Sakura-GalTransl-7B-v3.7`（视觉小说日译中，GRPO 强化） | `Sakura-14B-Qwen2.5-v1.0`（轻小说/galgame 日译中） |
| 风格 | 最自然、口语化的台词 | 自然，略偏书面 |
| 术语表 | 原生 `src->dst #备注` 格式，按句注入 | 原生 GPT 字典格式，按句注入 |
| 体量 | 7B（约 6.25 GB Q6） | 14B（约 8-9 GB iq4xs） |

GalTransl 是默认翻译后端，主要原因是模型更小、推理更轻，当前项目样例里台词风格也更贴近日常口语。Sakura-14B 更重，适合作为长难句或可疑译文的第二意见。实际速度和显存取决于 GGUF 量化、上下文长度、批大小、`llama-cpp-python` 是否启用 GPU，以及具体显卡。

两者都修不了 ASR 阶段听错的专名（识别错了翻译救不回来），都依赖识别出的日文本身正确。

**推荐：** 这类视觉小说/台词内容保持默认 GalTransl。长难句想要第二意见时试 `--translator sakura`。
