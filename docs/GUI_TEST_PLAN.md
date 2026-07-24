# GUI 测试计划与结果记录模板

状态：执行中
适用范围：源码开发版 GUI，以及后续 Windows CUDA 绿色目录版  
基线提交：`b6cec92 Add source GUI for subtitle pipeline`  
最近自动测试基线：`403 passed`

## 1. 目标

本计划用于验证 GUI 的每一项用户可见功能都能正确驱动现有字幕流水线，并明确区分：

- 不加载模型的自动化测试；
- WSLg 源码版的真实 CUDA 功能测试；
- Windows 绿色目录版完成后的原生环境验收。

测试重点是功能、状态、输出和失败恢复。当前 GUI 不是视频播放器或字幕编辑器，本计划不验证
时间轴手工编辑、视频预览或本地 LLM 审校。

## 2. 通过标准

发布候选版本必须同时满足：

1. 完整自动测试通过，且 `git diff --check` 无错误；
2. 所有 P0、P1 用例通过；
3. 每个用户可见控件至少被一个自动或人工用例覆盖；
4. Anime、Qwen、GalTransl、Sakura、Sugoi 后端都至少完成一次真实加载；
5. 默认 Anime + GalTransl 流程从 GUI 输入一直生成最终双语 ASS；
6. 取消、失败和断点续跑不误报成功、不误删中间产物；
7. Windows 绿色版阶段必须在没有项目开发环境的 Windows 会话中单独通过验收。

允许 P2 外观问题延期，但必须记录；P0/P1 未通过时不能进入下一发布阶段。

## 3. 测试环境

每轮执行前记录：

| 项目 | 记录值 |
|---|---|
| 日期 | |
| Git 提交 | |
| 测试人员 | |
| 环境 | WSLg 源码版 / Windows 绿色版 |
| Windows 版本 | |
| WSL 发行版（如适用） | |
| GPU 与显存 | |
| NVIDIA 驱动 | |
| Python/内置运行时版本 | |
| PyTorch CUDA | |
| ONNX Runtime providers | |
| llama.cpp GPU offload | |
| FFmpeg 版本 | |
| 测试模型 | |

## 4. 测试素材

不要把私人文件名或绝对路径写入仓库。执行记录只使用以下代号：

| 代号 | 要求 | 用途 |
|---|---|---|
| V1 | 8–20 秒、至少两句清晰日语对白 | 快速成功流程、后端加载、清理策略 |
| V2 | 30–90 秒、含停顿和多条对白 | 进度、字幕样式和质量报告 |
| V3 | 2–5 分钟或足以手动取消的片段 | 取消、重新加入、断点续跑 |
| F1 | 含 V1、V2 的目录 | 文件夹队列测试 |
| F2 | V1 位于子目录、根目录另有非视频文件 | 递归扫描与过滤 |
| P1 | 含中文、空格和较长目录名的副本 | Windows/WSL 路径兼容 |

测试副本必须与原始素材分开，避免清理和复制测试影响原文件。

## 5. 结果标记

- `PASS`：实际结果与预期一致；
- `FAIL`：结果错误或缺失；
- `BLOCKED`：环境或前置条件不满足；
- `SKIP`：本轮明确不适用，必须填写原因；
- `NOT RUN`：尚未执行。

每个失败必须记录日志路径、截图或可复现步骤，不能只写“失败”。

## 6. 自动化基线

### AUTO-001 完整测试

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q
git diff --check
```

预期：全部测试通过，差异格式检查无输出。

当前自动测试已覆盖：

- GUI 配置到 CLI 参数的精确映射与参数校验；
- Anime/Qwen 批大小参数选择；
- 文件和文件夹发现、递归扫描、过滤与去重；
- 默认勾选状态和设置迁移；
- 文件选择结果和模拟本地文件拖放事件；
- 设置保存后由新窗口实例恢复；
- 模型文件完整性检查；
- 简体/繁体/实验性英文字幕目标、兼容模型联动、设置持久化和标准输出后缀；
- OpenCC SRT 结构保持、Sugoi 编号批量严格校验/拆分重试/字符残留拒绝；
- 模型缺失时阻止启动并显示缺失路径；
- 下拉菜单和字体菜单选择后销毁；
- 高级设置自动换行开关和取消修改回滚；
- CUDA 刷新按钮的焦点行为；
- 任务状态、失败/取消后的移除和重新加入；
- JSONL 阶段事件、输出和队列进度；
- 取消当前任务后停止队列；
- 清理策略及主流水线事件/取消接口。

自动测试不能替代真实模型加载、桌面拖放、系统目录对话框、播放器渲染或 Windows 绿色版验证。

## 7. GUI 静态与交互用例

### 7.1 启动、布局与设备状态

| ID | 优先级 | 操作 | 预期 | 结果 |
|---|---|---|---|---|
| GUI-001 | P0 | 启动 `python scripts/run_gui.py` | 主窗口正常出现，无终端异常退出 | NOT RUN |
| GUI-002 | P1 | 检查 1280×720 默认窗口 | 主要文字不换行、不遮挡，底部按钮完整可见 | NOT RUN |
| GUI-003 | P1 | 缩小到允许的最小尺寸后恢复 | 控件不重叠；窗口可以恢复 | NOT RUN |
| GUI-004 | P1 | 展开 ASR、翻译、清理下拉菜单并选择 | 选项生效，菜单立即消失 | NOT RUN |
| GUI-005 | P0 | 等待启动设备检测 | 显示 ASR、VAD、翻译的 CUDA/CPU 状态 | NOT RUN |
| GUI-006 | P1 | 点击“刷新” | 显示“检测中…”，完成后恢复；焦点不跳到输出目录 | NOT RUN |
| GUI-007 | P1 | 悬停设备状态 | 能查看组件检测详情 | NOT RUN |
| GUI-008 | P1 | 关闭再启动 GUI | 窗口和已保存设置正常恢复 | NOT RUN |

### 7.2 输入与任务队列

| ID | 优先级 | 操作 | 预期 | 结果 |
|---|---|---|---|---|
| QUEUE-001 | P0 | 将 V1 拖入窗口 | 队列增加一项，路径正确 | NOT RUN |
| QUEUE-002 | P1 | 同时拖入 V1、V2 | 两项均加入，顺序稳定 | NOT RUN |
| QUEUE-003 | P1 | 重复拖入 V1 | 不产生重复任务 | NOT RUN |
| QUEUE-004 | P1 | 点击“添加视频”选择 V1 | 系统文件对话框工作，任务加入 | NOT RUN |
| QUEUE-005 | P1 | 点击“添加文件夹”选择 F1 | 文件夹中的支持视频加入队列 | NOT RUN |
| QUEUE-006 | P1 | 递归关闭时加入 F2 | 不加入子目录内的 V1 | NOT RUN |
| QUEUE-007 | P1 | 递归开启时加入 F2 | 加入子目录内的 V1，忽略非视频文件 | NOT RUN |
| QUEUE-008 | P1 | 选中一项后“移除选中” | 仅移除选中任务 | NOT RUN |
| QUEUE-009 | P1 | 点击“清空” | 队列和总进度恢复初始状态 | NOT RUN |
| QUEUE-010 | P1 | 任务运行时尝试增删队列 | 输入和队列编辑控件被禁用 | NOT RUN |
| QUEUE-011 | P1 | 使用 P1 中文/空格/长路径素材 | 能加入队列，路径显示和处理正常 | NOT RUN |

### 7.3 常用设置

| ID | 优先级 | 操作 | 预期 | 结果 |
|---|---|---|---|---|
| SET-001 | P0 | 清空旧设置后首次启动 | 双语 ASS、复制字幕开启；递归、断点续跑关闭 | NOT RUN |
| SET-002 | P1 | 切换 Anime/Qwen | 模型状态随选择刷新 | NOT RUN |
| SET-003 | P1 | 简体/繁体下切换 GalTransl/Sakura | 模型状态随选择刷新 | NOT RUN |
| SET-004 | P1 | 修改 ASR 批大小 | 值被记忆，并传给所选 ASR 后端 | NOT RUN |
| SET-005 | P1 | 选择输出目录和工作目录 | 输入框更新，悬停可见完整路径 | NOT RUN |
| SET-006 | P1 | 切换三种清理策略 | 当前选项显示正确并被记忆 | NOT RUN |
| SET-007 | P1 | 切换质量报告、复制、说话人着色 | 状态被记忆，模型检查按需更新 | NOT RUN |
| SET-008 | P1 | 模型缺少必需文件时开始 | 启动被阻止并列出缺失文件 | NOT RUN |
| SET-009 | P0 | 字幕语言切到“英文（实验性）” | 翻译模型自动切为 Sugoi 且不可选不兼容模型 | NOT RUN |
| SET-010 | P1 | 从英文切回简体或繁体 | 恢复上次中文翻译模型、批大小和换行值 | NOT RUN |

### 7.4 高级设置

| ID | 优先级 | 操作 | 预期 | 结果 |
|---|---|---|---|---|
| ADV-001 | P1 | 打开高级设置 | 独立窗口完整显示两个标签页 | NOT RUN |
| ADV-002 | P1 | 修改参数后点“取消” | 所有修改回滚 | NOT RUN |
| ADV-003 | P1 | 修改参数后点“确定” | 修改保留并在重启后恢复 | NOT RUN |
| ADV-004 | P1 | 点击“恢复默认值” | 中文恢复上下文 6、批 8、换行 20；英文批量默认 10、换行初始值 60 | NOT RUN |
| ADV-005 | P1 | 展开字体列表并滚动选择 | 有垂直滚动条；选择后菜单关闭 | NOT RUN |
| ADV-006 | P1 | 选择四种字幕颜色 | 调色板可用，按钮色块与所选颜色一致 | NOT RUN |
| ADV-007 | P1 | 关闭长字幕自动换行 | CLI 收到阈值 0，输出不做显示换行 | NOT RUN |
| ADV-008 | P1 | 开启阈值 20 | 超过阈值时仅在合适标点处分行，无标点不硬拆 | NOT RUN |
| ADV-009 | P1 | 修改中日文字号和字体 | 生成 ASS 的样式字段与设置一致 | NOT RUN |
| ADV-010 | P2 | 开启说话人着色并选择男女颜色 | 生成 ASS 使用对应颜色；低置信度仍使用普通中文色 | NOT RUN |

## 8. 真实流水线用例

### 8.1 默认成功流程

| ID | 优先级 | 操作 | 预期 | 结果 |
|---|---|---|---|---|
| RUN-001 | P0 | V1，Anime + GalTransl，默认设置运行 | 任务完成，进度 100%，无错误 | NOT RUN |
| RUN-002 | P0 | 检查阶段状态和日志 | 提取、ASR、翻译、ASS 阶段顺序正确，日志持续刷新 | NOT RUN |
| RUN-003 | P0 | 检查输出目录 | `.zh-s` SRT/ASS 和术语文件存在且非空 | NOT RUN |
| RUN-004 | P0 | 检查视频目录 | 按默认设置只复制最终双语 ASS | NOT RUN |
| RUN-005 | P1 | 用播放器打开 ASS | 中文、日文、换行、颜色和字号正常显示 | NOT RUN |
| RUN-006 | P1 | 点击“打开输出目录” | 系统文件管理器打开当前输出目录 | NOT RUN |

### 8.2 后端覆盖

为避免无意义地跑四种笛卡尔组合，使用两次短流程覆盖全部后端：

| ID | 优先级 | 组合 | 预期 | 结果 |
|---|---|---|---|---|
| BACKEND-001 | P0 | V1：Anime + GalTransl | 两个后端真实加载并完成 | PASS |
| BACKEND-002 | P0 | V1：Qwen + Sakura | 两个后端真实加载并完成 | NOT RUN |
| BACKEND-003 | P0 | V1：Anime + Sugoi，英文目标 | Sugoi CUDA 加载并生成 `.en.srt/.en.ass` | PASS |
| BACKEND-004 | P0 | V1：Anime + GalTransl，繁体目标 | OpenCC `s2t` 后生成 `.zh-t.srt/.ass` | PASS |

两次运行都要从日志确认实际选择的后端，不能只看 GUI 下拉框。

### 8.3 批量和进度

| ID | 优先级 | 操作 | 预期 | 结果 |
|---|---|---|---|---|
| BATCH-001 | P0 | 队列加入 V1、V2 后开始 | 严格逐个处理，不并行加载两套模型 | NOT RUN |
| BATCH-002 | P1 | 观察单任务及总进度 | 阶段完成后进度前进，最终总进度 100% | NOT RUN |
| BATCH-003 | P0 | 观察 Anime 分块识别、对齐和翻译 | 保持单一总体进度条；块/字幕完成时百分比持续前进，状态文字显示当前工作 | PASS |
| BATCH-003 | P1 | 第一项完成后观察第二项 | 自动开始第二项，输出归属正确 | NOT RUN |
| BATCH-004 | P1 | 全部完成后检查按钮 | 开始、取消、打开工作目录和打开输出目录状态正确 | NOT RUN |

### 8.4 取消、失败、重新加入与断点续跑

| ID | 优先级 | 操作 | 预期 | 结果 |
|---|---|---|---|---|
| RECOVER-001 | P0 | V3 运行中点击“取消” | 当前任务变为已取消，后续等待任务不启动 | NOT RUN |
| RECOVER-002 | P0 | 检查取消后的文件 | 已有中间产物保留，不执行成功后清理 | NOT RUN |
| RECOVER-003 | P1 | 失败/取消后移除任务并重新加入 | 任务恢复等待状态且可以再次开始 | NOT RUN |
| RECOVER-004 | P0 | 勾选断点续跑后重新加入 | 完整 WAV/日语 SRT/译文 SRT 且 provenance 相符时安全跳过 | NOT RUN |
| RECOVER-005 | P1 | 取消翻译形成不完整译文 SRT 后重新加入 | 条数不完整时翻译不会被错误跳过 | NOT RUN |
| RECOVER-006 | P1 | 制造可恢复失败，修正条件后重新加入 | 任务先显示失败原因，之后可成功完成 | NOT RUN |
| RECOVER-007 | P1 | 更换 ASR 模型后关闭断点续跑 | ASR 确实重新执行，不复用旧日语 SRT | NOT RUN |
| RECOVER-008 | P1 | 任务运行时关闭窗口并拒绝确认 | 窗口保持打开，任务继续 | NOT RUN |
| RECOVER-009 | P1 | 任务运行时关闭窗口并确认 | 请求取消，完成安全退出，不遗留假运行状态 | NOT RUN |

### 8.5 清理策略

每条用例使用独立测试副本，避免前一轮删除影响后一轮。

| ID | 优先级 | 策略 | 预期 | 结果 |
|---|---|---|---|---|
| CLEAN-001 | P0 | 保留全部中间产物 | WAV、日语 SRT、metadata、日志和最终输出保留 | NOT RUN |
| CLEAN-002 | P0 | 成功后删除 WAV | 仅 WAV 被删除；其他中间和最终输出保留 | NOT RUN |
| CLEAN-003 | P0 | 成功后仅保留最终字幕、质检和日志 | 已知 WAV、日语 SRT、ASR metadata 删除；最终输出和日志保留 | NOT RUN |
| CLEAN-004 | P0 | 开启质量报告并使用 final_only | 质量报告保留 | NOT RUN |
| CLEAN-005 | P0 | 失败或取消时使用任意清理策略 | 不执行成功清理，中间产物保留 | NOT RUN |

## 9. Windows 绿色目录版专项验收

此节在绿色包组装完成后执行，不能用 WSLg 结果代替。

| ID | 优先级 | 操作 | 预期 | 结果 |
|---|---|---|---|---|
| WIN-001 | P0 | 在无项目 Python 环境中解压并启动 | 不安装 Python/pip 也能启动 GUI | PASS |
| WIN-002 | P0 | 断开 WSL 后启动 | 不依赖 WSL 文件或进程 | PASS |
| WIN-003 | P0 | 运行设备检测 | 正确识别 Windows CUDA 三个组件 | PASS |
| WIN-004 | P0 | 用 V1 跑默认流程 | Windows 原生 CUDA 流程完成 | PASS |
| WIN-005 | P0 | 验证内置 FFmpeg | 不依赖系统 PATH 中的 FFmpeg | PASS |
| WIN-006 | P1 | 从中文、空格、长路径运行 | 输入、工作、输出和复制均成功 | PASS |
| WIN-007 | P1 | 移动整个绿色目录后再启动 | 相对路径和模型发现仍正常 | PASS |
| WIN-008 | P1 | 在另一台兼容 NVIDIA 电脑解压测试 | 无开发机残留依赖 | NOT RUN |
| WIN-009 | P1 | 检查压缩包清单和许可证 | 运行时、模型、FFmpeg、许可证和 notices 完整 | PASS |
| WIN-010 | P0 | 双击原生 EXE 并开始处理 | GUI 不依赖 CMD；主流水线及 FFmpeg/模型子进程不弹控制台窗口 | PASS |
| WIN-011 | P1 | 显示/隐藏日志并重启 | 日志区域折叠后任务区扩展；选择被记忆；失败时自动展开 | PASS |

## 10. 推荐执行顺序

1. `AUTO-001`；
2. GUI-001 至 ADV-010，不加载模型完成静态交互验收；
3. RUN-001 至 RUN-006，立即验证默认真实流程；
4. BACKEND-002，覆盖 Qwen 和 Sakura；
5. 批量、取消、断点续跑和三种清理策略；
6. 修复所有 P0/P1 问题并完整回归；
7. Windows 绿色包组装完成后执行 WIN-001 至 WIN-009。

## 11. 单次运行记录模板

复制本节，为每次真实模型运行填写一份记录。

### RUN-YYYYMMDD-NN

| 项目 | 记录值 |
|---|---|
| 日期/时间 | |
| Git 提交 | |
| 环境 | |
| 素材代号 | |
| ASR / 批大小 | |
| 翻译模型 | |
| 输出/工作目录代号 | |
| 双语 ASS | |
| 质量报告 | |
| 断点续跑 | |
| 清理策略 | |
| CUDA 状态 | |
| 开始时间 | |
| 结束时间 | |
| 最终状态 | PASS / FAIL / BLOCKED |

阶段记录：

| 阶段 | 状态 | 耗时 | 设备/关键日志 | 备注 |
|---|---|---:|---|---|
| 音频提取 | | | | |
| 日语 ASR | | | | |
| 中文翻译 | | | | |
| 双语 ASS | | | | |
| 质量报告 | | | | |
| 清理 | | | | |

输出核对：

- [ ] 中文 SRT 存在且非空
- [ ] 双语 ASS 存在且非空
- [ ] 视频目录复制结果正确
- [ ] 日中字幕逐条对应
- [ ] 字体、字号、颜色和自动换行正确
- [ ] 时间轴可正常播放
- [ ] 日志与 GUI 最终状态一致
- [ ] 清理结果符合所选策略

结论与备注：

```text

```

## 12. 缺陷记录模板

### BUG-YYYYMMDD-NN：简短标题

| 项目 | 记录值 |
|---|---|
| 严重级别 | P0 / P1 / P2 |
| Git 提交 | |
| 环境 | |
| 关联用例 | |
| 可重复性 | 每次 / 偶发 / 仅一次 |

复现步骤：

1. 
2. 
3. 

预期结果：

```text

```

实际结果：

```text

```

证据：

- 日志：
- 截图：
- 输出文件：

修复提交与回归结果：

```text

```

## 13. 已执行记录

以下记录使用隔离的临时目录和测试副本；没有修改原始视频、现有 `outputs/` 或现有 `work/`。

### 2026-07-16 自动基线

| 项目 | 结果 |
|---|---|
| 提交 | `b6cec92` |
| 环境 | WSLg 源码版，Qt offscreen 自动测试 |
| AUTO-001 | PASS：`323 passed`，`git diff --check` 通过 |

### RUN-20260716-01：默认真实流程

| 项目 | 记录值 |
|---|---|
| 素材 | V1，30.177 秒日语对白测试副本 |
| ASR / 批大小 | Anime / 24 |
| 翻译 | GalTransl 7B |
| 设置 | 双语 ASS、复制最终字幕、保留全部中间产物 |
| 结果 | PASS：约 15 秒完成，状态 completed，进度 100% |

核对结果：WhisperSeg 日志确认 `CUDAExecutionProvider`；日中 SRT 均为 5 条；中文 SRT、
双语 ASS、术语报告存在且非空；视频旁 ASS 与输出 ASS 的 SHA-256 一致；ASS 中的
`Microsoft YaHei`、36/24 字号和四种样式均正确写入。

### RUN-20260716-02：清理策略

| 策略 | 质量报告 | 结果 |
|---|---|---|
| 成功后删除 WAV | 关闭 | PASS：仅 WAV 删除；日语 SRT、metadata、日志和最终输出保留 |
| 仅保留最终字幕、质检和日志 | 开启 | PASS：WAV、日语 SRT、metadata 删除；质量报告、日志、SRT、ASS、术语报告保留 |

### RUN-20260716-03：取消与断点续跑

| 项目 | 记录值 |
|---|---|
| 素材 | V3，120.133 秒日语对白测试副本；后接 V1 队列任务 |
| 取消时机 | GUI 控制器收到 ASR 阶段事件后请求取消 |
| 清理策略 | final_only |
| 取消结果 | PASS：V3 为 cancelled（17%）；后续 V1 保持 waiting；WAV 和 pipeline.log 保留，未执行成功清理 |
| 续跑结果 | PASS：勾选断点续跑后 V3 完成；日志明确记录 `Reusing existing audio`，说明 WAV 被复用，未完成 ASR/翻译/ASS 重新执行 |

### RUN-20260716-04：后端覆盖

| 项目 | 记录值 |
|---|---|
| 素材 | V1 |
| ASR / 翻译 | Qwen / Sakura 14B |
| 结果 | PASS：约 13 秒完成，状态 completed，进度 100%，生成 SRT 和双语 ASS |

结合 RUN-20260716-01，Anime、Qwen、GalTransl、Sakura 均已完成一次真实模型加载。

### RUN-20260716-05：队列与质量报告

| 项目 | 记录值 |
|---|---|
| 素材 | V1、V2 两条 30 秒测试副本 |
| 设置 | Anime + GalTransl，质量报告开启，复制关闭 |
| 结果 | PASS：日志按 V1 后 V2 顺序启动；两项均 completed 100%；各自 SRT、ASS、质量报告存在；汇总 metrics JSONL 恰有两条记录 |

### RUN-20260716-06：高级字幕样式

| 项目 | 记录值 |
|---|---|
| 素材 | V1 |
| 设置 | 自动换行关闭；中文/日文字号 42/26；修改中文和日文颜色 |
| 结果 | PASS：最终 ASS 的 ZH/JA 样式字段与字号、颜色设置一致；日志没有显示自动换行 |

### RUN-20260716-07：窗口内部布局与设备状态

| 项目 | 记录值 |
|---|---|
| 主窗口 | PASS：直接渲染 1280×720 和最小 1120×680；主要标签不换行，底部四个操作按钮均在窗口范围内 |
| 高级设置 | PASS：560×445 下翻译、字幕样式两个标签页及底部按钮完整显示 |
| 设备检测 | PASS：RTX 5080；PyTorch CUDA、ONNX Runtime CUDA provider、llama.cpp GPU offload 均可用 |
| 环境限制 | WSLg 的 `rdp-*` 屏幕坐标不能可靠映射到 Windows 工作区，顶层窗口默认位置和任务栏避让留到 Windows 原生绿色版验收 |

### RUN-20260716-08：可恢复失败后重试

| 项目 | 记录值 |
|---|---|
| 首次运行 | 损坏的 MP4 在 FFmpeg 提取阶段失败；任务为 failed、进度 0%，未生成最终 ASS |
| 修复与重试 | 用有效 V1 副本替换同一路径文件，执行失败任务重置和重新开始 |
| 结果 | PASS：旧错误被清除，任务从 waiting 完成到 completed 100%，中文 SRT 和双语 ASS 均生成 |

### RUN-20260716-09：标准 ASS 渲染

| 项目 | 记录值 |
|---|---|
| 渲染器 | FFmpeg `ass` 滤镜 / libass |
| 素材 | V1 与默认流程生成的双语 ASS |
| 结果 | PASS：Microsoft YaHei 正常加载；中文黄色 36 号、日文灰色 24 号及黑色描边正确；两行层级和底部边距正常，无重叠或越界 |
| 边界 | 证明 ASS 文件可被标准 libass 正确渲染；Windows 目标播放器仍需原生环境验收 |

### RUN-20260716-10：Windows 原生 CUDA 绿色目录

| 项目 | 记录值 |
|---|---|
| 环境 | Windows x64 原生进程；绿色目录内置 Python 3.12.10 和 FFmpeg 8.1.2 |
| GPU 基线 | RTX 5080；PyTorch 2.11.0+cu128 |
| 设备检测 | PASS：PyTorch CUDA、WhisperSeg ONNX CUDA session、llama.cpp GPU offload 均通过真实负载检查 |
| 素材 | V1，约 23 秒真实日语对白 |
| 设置 | Anime + GalTransl，ASR 批大小 6，翻译批大小 4，双语 ASS 开启，复制关闭 |
| 结果 | PASS：包内 FFmpeg 提取音频；Anime 生成 8 条日语并完成强制对齐；GalTransl 输出 8 条中文；最终 SRT 与双语 ASS 均生成 |
| 时间 | 约 63 秒，包含三个模型阶段的首次加载 |
| 重定位 | PASS：整个绿色目录移动到含中文和空格的新路径后，输出/工作路径随根目录更新，三个 CUDA 组件仍可用 |
| 路径兼容 | PASS：中文、空格和较长名称的输入/输出/工作目录完成全流程，最终 ASS 成功复制到源视频旁边 |
| 边界 | 尚未覆盖断开 WSL 后启动、其它 NVIDIA 电脑和 Qwen/Sakura 可选后端 |

### RUN-20260716-11：Windows 发布候选归档

| 项目 | 记录值 |
|---|---|
| 归档 | 程序包约 3.1 GB；默认模型包约 9.8 GB；分开发布 |
| 完整性 | PASS：两个归档均通过 SHA-256；程序包含逐文件大小/哈希清单，模型包含独立清单 |
| 首次解压缺陷 | 首版排除规则 `models/***` 误匹配 `transformers/models` 等第三方包目录，导致导入失败；改为根锚定 `/models/***` 并加入目录与实际 import 哨兵后修复 |
| 干净启动 | PASS：全新删除目标目录后解压两个归档；不使用项目 Python/pip，内置 Python 启动 GUI 并自动退出 |
| 设备检测 | PASS：RTX 5080 上 PyTorch CUDA、WhisperSeg 的真实 CUDA session、llama.cpp GPU offload 均为 true |
| 默认流程 | PASS：约 23 秒 V1 使用内置 FFmpeg、Anime、forced aligner、GalTransl 生成 8 条日文、中文 SRT 和双语 ASS；约 29 秒完成 |
| 断点续跑 | PASS：复用 WAV、日语 SRT 和中文 SRT，仅重建 ASS，不到 1 秒完成 |
| final_only | PASS：成功后工作目录仅保留 `pipeline.log`，最终 SRT、ASS 和术语表保留 |
| 运行中取消 | PASS：Anime 阶段创建取消文件后以退出码 130 结束；未生成最终字幕，无残留流水线子进程，WAV 和日志保留 |
| 许可证 | PASS：程序包含 Python/Qt-PySide/FFmpeg notices 与许可材料；模型包含四个默认模型的上游 model card、许可文本和状态清单 |
| 分发限制 | GalTransl 上游声明为 CC-BY-NC-SA-4.0 并明确禁止商业使用，因此默认模型包必须与程序包分离并保留非商业提示 |
| 边界 | 测试由 WSL 发起 Windows 原生进程；尚未验证 WSL 完全断开、第二台 NVIDIA 电脑及 Qwen/Sakura 可选模型包 |

### RUN-20260716-12：EXE、无黑框和细化总体进度

| 项目 | 记录值 |
|---|---|
| 启动器 | PASS：44 KB 原生 Windows GUI 子系统 EXE，仅依赖 Windows 系统 DLL；成功启动包内 `pythonw.exe` |
| 无控制台 | PASS：GUI 主流水线使用 `pythonw.exe`；流水线内部 subprocess 使用 `CREATE_NO_WINDOW`；原生完整流程完成 |
| 日志折叠 | PASS：显示/隐藏即时生效并写入 GUI 设置；隐藏后任务区扩展；失败状态自动重新显示日志 |
| 总体进度 | PASS：V1 实测依次显示场景分析、语音片段分析、模型加载、Anime 1/5 至 5/5、强制对齐 5/5、翻译 1/8 至 8/8，百分比从 0 单调增长到 100 |
| 流程结果 | PASS：通过 GUI controller 与 `pythonw.exe` 完成 Anime + GalTransl，生成中文 SRT 和双语 ASS |
| 自动测试 | `330 passed` |
| 制品状态 | 已由后续 RUN-20260716-13 重新生成最终 staging、程序包和四个模型包 |

### RUN-20260716-13：Windows CUDA 测试版候选与模型分包

| 项目 | 记录值 |
|---|---|
| 归档 | 程序 3,282,810,909 B；默认模型 10,422,393,080 B；Qwen ASR 3,471,565,149 B；Sakura 14B 8,050,332,879 B；性别模型 56,684,987 B |
| 分包结构 | PASS：默认包只含 Anime/WhisperSeg/Forced Aligner/GalTransl；三个可选包各自只含 Qwen ASR、Sakura 14B 或性别模型 |
| 许可 | PASS：Qwen ASR 附 Apache-2.0；性别模型附 MIT；默认翻译和 Sakura 14B 附 CC-BY-NC-SA-4.0 与非商业提示；各包保留对应上游模型卡 |
| 文件清单 | PASS：默认 31 项、Qwen 15 项、Sakura 4 项、性别 10 项逐文件 SHA-256 复核通过 |
| 归档完整性 | PASS：五个最终归档均通过总 `SHA256SUMS`；四个模型归档额外通过 `7z t` |
| 全新解压 | PASS：程序与四个模型包从零合并解压；七个模型目录、四份模型清单、空 GUI 配置和空输出/工作目录符合预期；实际 Transformers 导入成功 |
| CUDA 探测 | PASS：解压候选在 RTX 5080 上 PyTorch、WhisperSeg ONNX、llama.cpp 三项 CUDA 均为 true |
| 默认流程 | PASS：解压候选使用 Anime + GalTransl 完成约 23 秒样例，生成 8 条日文、中文 SRT 和双语 ASS，约 30 秒 |
| Qwen 可选包 | PASS：Windows 包内 Qwen ASR 加载两个 shard，WhisperSeg 使用 CUDA，完成 6 条识别；GalTransl 生成最终 ASS，约 20 秒 |
| Sakura 可选包 | PASS：Anime 生成 8 条日文，Sakura 14B GGUF 完成翻译并生成最终 ASS，约 29 秒 |
| 性别可选包 | PASS：包内 ECAPA 模型完成真实推理，8/8 cue 着色，male/female 各 4 条 |
| 原生 EXE | PASS：`jp2zh字幕工具.exe` 返回 0 并启动包内 `pythonw.exe`；GUI 进程有有效窗口句柄且可正常关闭 |
| 当前边界 | 仅 RTX 5080 一台 Windows 电脑；无第二块 NVIDIA 显卡的原生兼容性数据，因此定位为测试版候选 |

上述原生 EXE 文件名是 Beta 2 的历史测试记录。国际化开发版已将后续绿色包入口改为
`jp2zh-subtitle-tool.exe`；发布新测试版时需按新名称重新执行本节验证。

### RUN-20260717-14：Windows CUDA Beta 1 发布

| 项目 | 记录值 |
|---|---|
| Release | `v0.1.0-beta.1` 已作为 GitHub prerelease 发布，tag 指向 `9c2b93a` |
| 分发策略 | 只发程序包，不发第三方模型权重；用户按中英文安装说明使用包内 `hf.exe` 从 Hugging Face 下载 |
| 程序分卷 | `.001` 1,992,294,400 B；`.002` 1,290,993,518 B；重组 SHA-256 为 `6c92ab174627d3504b590789dbb09ea17db0aa5e6567899f2abae58a38830c86` |
| 完整性 | PASS：原始程序归档通过 `7z t`；两个分卷按顺序重组后与原归档 SHA-256 一致 |
| 图标 | PASS：EXE 内置 16–256 px 九档图标；Windows 成功从最终启动器提取 32 px 图标；Qt 窗口图标加载成功 |
| 隐私边界 | PASS：最终归档不包含 `config/gui.ini`、模型权重、示例视频或其他媒体文件 |
| 用户解压启动 | PASS：用户已解压最终程序包并启动 GUI；缺少模型时正确列出 6 个必需文件 |
| 已知提示问题 | 缺少 WhisperSeg ONNX 时设备栏显示“语音切分 CPU”；该问题已由后续 RUN-20260717-15 修复和复测 |

### RUN-20260717-15：GUI 进程与设备状态加固

| 项目 | 记录值 |
|---|---|
| 源码版本 | `6974e93` (`Harden GUI process and device handling`) |
| 自动测试 | PASS：`336 passed`；包括 CrashExit + 退出码 0 仍标记失败、单实例锁、运行时目录清理和 VAD 四态文案 |
| Windows launcher | PASS：MinGW `-Wall -Wextra -Werror` 完整链接成功；`SystemRoot`、环境变量和路径截断均有失败检查 |
| package 刷新 | PASS：仅同步程序脚本并重编译原生 EXE；源码与 package 的 5 个变更脚本 SHA-256 逐一一致 |
| Windows 用户验收 | PASS（人工）：重复启动第二个 GUI 时出现单实例提示；临时移走 models 后显示“语音切分 未检测（缺少模型）” |
| 完整流程 | PASS（人工）：Windows GUI 正常完成一次实际任务；结束后 `work/.gui` 未留下本次 UUID 运行目录 |

### RUN-20260717-16：Windows CUDA Beta 2 发布

| 项目 | 记录值 |
|---|---|
| Release | `v0.1.0-beta.2` 已作为 GitHub prerelease 发布，tag 指向 `b1d4e5f` |
| 程序分卷 | `.001` 1,992,294,400 B；`.002` 1,290,993,726 B；重组 SHA-256 为 `ff8aed50b5310995c3bc30c80c048a1b3da5b1b57371601f1ec510d5cd01f085` |
| 完整性 | PASS：原始程序归档和直接从 `.001` 识别的两分卷均通过 `7z t`；流式重组 SHA-256 与原归档一致 |
| 隐私边界 | PASS：归档不包含模型、`config/gui.ini`、运行锁、work、outputs、用户/示例视频或字幕 |
| 远端资产 | PASS：2 个程序分卷、2 个中英文安装说明和 2 个 SHA-256 文件均为 `uploaded`；release 非 draft 且为 prerelease |

### RUN-20260720-17：三种字幕目标与 Windows CUDA 绿色目录

| 项目 | 记录值 |
|---|---|
| 自动测试 | PASS：`371 passed`；`git diff --check` 和 Windows 打包脚本语法检查通过 |
| Windows 运行时 | PASS：绿色包自带 OpenCC 1.4.1；`s2t` 转换保持 SRT 索引和时间轴 |
| Sugoi 模型 | PASS：源文件与 Windows 包内 Q4 模型 SHA-256 均为 `d34cdc5f1be98091fdef6cedaf0a84978ca17c785a7b99c57ca22e44d4687b77` |
| 运行设备 | PASS：RTX 5080；PyTorch CUDA、WhisperSeg CUDAExecutionProvider、llama.cpp GPU offload 均为可用 |
| 简体流程 | PASS：Windows 原生 Anime + GalTransl 生成 `.zh-s.srt/.zh-s.ass` |
| 繁体流程 | PASS：Windows 原生 Anime + GalTransl + OpenCC `s2t` 生成 `.zh-t.srt/.zh-t.ass` |
| 英文流程 | PASS：Windows 原生 Anime + Sugoi 生成 `.en.srt/.en.ass`；10 条批处理无回退；该次运行当时使用 42 字符按词边界换行，当前默认值已调整为 60 |
| 字体 | PASS：英文目标顶行默认 Arial，日文底行继续使用 Microsoft YaHei |
| 测试素材 | 23 秒非成人日语对话样例；工作和输出均限制在 `E:\\jp2zh-win-portable-lab\\test-data` |
| 当时尚未执行 | 新程序归档、解压复验与新 Beta 发布；归档/解压/发布已由 RUN-20260720-18 完成，完整人工 GUI 三目标切换仍属 Beta 反馈矩阵 |

### RUN-20260720-18：Windows CUDA Beta 3 发布

| 项目 | 记录值 |
|---|---|
| Release | `v0.1.0-beta.3` 已作为 GitHub prerelease 发布，tag 指向 `be0a255` |
| 自动测试 | PASS：`385 passed`；Shell 语法、文档链接和 `git diff --check` 通过 |
| 分发策略 | 只发布程序包；模型权重仍由用户按包内 `INSTALL-CN.txt` / `INSTALL-EN.txt` 从 Hugging Face 下载 |
| 程序分卷 | `.001` 1,992,294,400 B；`.002` 1,291,825,906 B；重组 SHA-256 为 `c7ae7296648c585122c10205af6bfa407452fb09075801a37ae14cfb333b1fc4` |
| 完整性 | PASS：原始 `.7z` 通过 SHA-256；两个分卷各自通过 SHA-256；顺序拼接结果与原始归档哈希一致 |
| 发布边界 | PASS：程序包含 `jp2zh-subtitle-tool.exe` 和两份安装说明，不含模型权重、旧中文 EXE、`config/gui.ini`、运行锁或用户数据 |
| 全新解压 | PASS：28,136 个文件完整解压；包内 Transformers 实际导入成功；空模型目录和空输出/工作目录符合程序-only 发布策略 |
| 原生启动 | PASS：解压目录的 Windows EXE 启动有效 GUI 窗口并正常关闭；单实例锁和 `work/.gui` 临时文件正常清理 |
| 远端资产 | PASS：两个程序分卷、两份安装说明和两份 SHA-256 文件均为 `uploaded`；release 非 draft 且为 prerelease |
| 延续证据 | 简体、繁体和实验性英文的 Windows CUDA 完整流程沿用 RUN-20260720-17 的同代码 package 验证；最终归档后的变更仅为发布文档 |

### RUN-20260724-19：Windows CUDA Beta 4 发布

| 项目 | 记录值 |
|---|---|
| Release | `v0.1.0-beta.4` 已作为 GitHub prerelease 发布，tag 指向 `fbccddc` |
| 源码验证 | PASS：`401 passed`；Ruff、Python 编译、依赖一致性、Shell 语法、Markdown 链接和 `git diff --check` 均通过 |
| 增量 staging | PASS：只同步程序层并输出 `Reusing unchanged staged runtime`；没有重建 runtime 或打包模型 |
| 原始程序归档 | 3,284,128,574 B；SHA-256 为 `0ed529675342f095411f63b7d5fa33b674497012c06357a8e3a951e26ada0f6b` |
| 程序分卷 | `.001` 1,992,294,400 B，SHA-256 `7529e293d0af20fdef2fe8065e96633495b96eac39f840208cc20acc21b5c5d3`；`.002` 1,291,834,174 B，SHA-256 `c07fd7d2719f9f361766e1c71a15f821caf65a6b865fcea39b0f01f09c88e5b0` |
| 完整性 | PASS：原始归档和两个分卷各自通过 SHA-256；流式顺序重组哈希等于原始归档；从 `.001` 识别两卷执行 `7z t` 无错误 |
| 全新解压 | PASS：28,139 个文件、8,202,711,383 B 完整解压；包内 Transformers 实际导入成功 |
| 发布边界 | PASS：包含根目录和 `app` 内的 MIT LICENSE；不含模型权重、`config/gui.ini`、运行锁、媒体、字幕、用户输出或开发机路径 |
| 运行时与 GUI | PASS：解压后的 PyTorch 2.11.0+cu128 识别 RTX 5080 CUDA；CLI 帮助和非法后端组合提前拒绝正常；隔离配置 GUI 显示 2 个 ASR、3 种字幕目标并正常退出 |
| 远端资产 | PASS：两个程序分卷、两份安装说明和两份 SHA-256 文件均为 `uploaded`，名称和字节数与本地一致；四个小型资产重新下载后逐字节匹配 |

### RUN-20260724-20：Windows CUDA Beta 5 下载器热修复发布

| 项目 | 记录值 |
|---|---|
| Release | `v0.1.0-beta.5` 已作为 GitHub prerelease 发布，tag 指向 `934ed5f`；Beta 4 已标记为 superseded |
| 修复原因 | Beta 4 安装说明调用 pip 生成的 `runtime\Scripts\hf.exe`，其中嵌入打包机 Python 绝对路径，绿色目录移动后无法启动 |
| 修复内容 | 根目录新增可迁移 `hf.cmd`，通过相对路径调用随包 Python，并在模型下载期间清除推理专用 offline 环境变量；中英文安装命令全部改用该入口 |
| 源码验证 | PASS：`403 passed`；Ruff、Shell 语法和 `git diff --check` 通过 |
| 增量 staging | PASS：只同步程序层并输出 `Reusing unchanged staged runtime`；不重建 runtime、不复制或归档模型 |
| 原始程序归档 | 3,284,128,470 B；SHA-256 为 `79c7b4ff2af8d91f5002aff910fdad2907a0987f220b46ea082a4d90b5710648` |
| 程序分卷 | `.001` 1,992,294,400 B，SHA-256 `454b50d6282b5c229821be425c200d1389efe5c3683de69cf5ef9bd0993063d3`；`.002` 1,291,834,070 B，SHA-256 `f07e9070b7905bd1d34bb267ff8467b0e32f532871430d13e77be536631e75b5` |
| 完整性 | PASS：原始归档和两个分卷各自通过 SHA-256；顺序拼接结果与原始归档哈希一致；原始归档 `7z t` 无错误 |
| 全新解压 | PASS：28,140 个文件、8,202,711,989 B 完整解压；Transformers 实际导入成功；`hf.cmd version` 返回 huggingface_hub 0.36.2 |
| 联网安装 | PASS：从全新解压目录通过 Windows 本机 HTTP 代理调用 `hf.cmd`，实际下载 `litagin/anime-whisper` 的 1,268 B `config.json` |
| 远端资产 | PASS：两个程序分卷、两份安装说明和两份 SHA-256 文件均为 `uploaded`；GitHub 返回的大小和 SHA-256 digest 与本地一致 |

## 14. 当前剩余人工验收

以下项目尚未用真实桌面手工操作逐项勾选，保留 `NOT RUN`：系统文件对话框、真实桌面
拖放、窗口缩放、设置持久化、字幕播放器渲染、所有高级对话框按钮，以及
Windows 绿色目录版的 WIN-008。它们不应因上述自动或程序化 GUI 调用而标记为已通过。
