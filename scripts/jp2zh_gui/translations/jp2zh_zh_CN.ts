<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="zh_CN">
<context>
    <name>AdvancedSettingsDialog</name>
    <message>
        <location filename="../window.py" line="257"/>
        <source>Advanced subtitle and translation settings</source>
        <translation>高级字幕与翻译设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="258"/>
        <source>Number of preceding lines supplied to the translation model; 0 translates each line independently.</source>
        <translation>提供给翻译模型的前文轮数；0 表示逐句独立翻译。</translation>
    </message>
    <message>
        <location filename="../window.py" line="260"/>
        <source>Translation context</source>
        <translation>翻译上下文</translation>
    </message>
    <message>
        <location filename="../window.py" line="262"/>
        <source>These settings affect translation context and grouping, not GPU parallelism.</source>
        <translation>这些参数影响翻译语境和分组，不是显存并行参数。</translation>
    </message>
    <message>
        <location filename="../window.py" line="263"/>
        <source>Translation</source>
        <translation>翻译设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="266"/>
        <source> chars</source>
        <translation> 字</translation>
    </message>
    <message>
        <location filename="../window.py" line="264"/>
        <source>Wrap long subtitles</source>
        <translation>长字幕自动换行</translation>
    </message>
    <message>
        <location filename="../window.py" line="268"/>
        <source>Preferred line length</source>
        <translation>建议每行字符数</translation>
    </message>
    <message>
        <location filename="../window.py" line="272"/>
        <source>Japanese font size</source>
        <translation>日文字号</translation>
    </message>
    <message>
        <location filename="../window.py" line="259"/>
        <source>Maximum number of consecutive subtitles translated together; this is not GPU parallelism.</source>
        <translation>连续成组翻译的最大字幕条数；不是 GPU 并行数。</translation>
    </message>
    <message>
        <location filename="../window.py" line="261"/>
        <source>Translation batch size</source>
        <translation>翻译批大小</translation>
    </message>
    <message>
        <location filename="../window.py" line="265"/>
        <source>Wrap long Chinese text near punctuation and English text at a word boundary</source>
        <translation>中文长句按附近标点换行，英文长句在单词边界换行</translation>
    </message>
    <message>
        <location filename="../window.py" line="267"/>
        <source>Cue count and timing stay unchanged; English uses a separately evaluated default.</source>
        <translation>字幕条数和时间轴保持不变；英文默认值需单独评估。</translation>
    </message>
    <message>
        <location filename="../window.py" line="269"/>
        <source>Target subtitle font</source>
        <translation>译文字幕字体</translation>
    </message>
    <message>
        <location filename="../window.py" line="270"/>
        <source>Japanese subtitle font</source>
        <translation>日文字幕字体</translation>
    </message>
    <message>
        <location filename="../window.py" line="271"/>
        <source>Target font size</source>
        <translation>译文字幕字号</translation>
    </message>
    <message>
        <location filename="../window.py" line="274"/>
        <source>Target colour</source>
        <translation>译文字幕颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="275"/>
        <source>Japanese colour</source>
        <translation>日文颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="276"/>
        <source>Male speaker colour</source>
        <translation>男性颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="277"/>
        <source>Female speaker colour</source>
        <translation>女性颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="283"/>
        <source>Subtitle style</source>
        <translation>字幕样式</translation>
    </message>
    <message>
        <location filename="../window.py" line="284"/>
        <source>Restore defaults</source>
        <translation>恢复默认值</translation>
    </message>
    <message>
        <location filename="../window.py" line="285"/>
        <source>OK</source>
        <translation>确定</translation>
    </message>
    <message>
        <location filename="../window.py" line="286"/>
        <source>Cancel</source>
        <translation>取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="312"/>
        <source>{value} (click to choose a colour)</source>
        <translation>{value}（点击选择颜色）</translation>
    </message>
    <message>
        <location filename="../window.py" line="316"/>
        <source>Choose subtitle colour</source>
        <translation>选择字幕颜色</translation>
    </message>
</context>
<context>
    <name>Application</name>
    <message>
        <location filename="../app.py" line="40"/>
        <source>Application already running</source>
        <translation>程序已在运行</translation>
    </message>
    <message>
        <location filename="../app.py" line="41"/>
        <source>jp2zh Subtitle Tool is already running.</source>
        <translation>jp2zh 字幕工具已经在运行。</translation>
    </message>
</context>
<context>
    <name>DeviceStatus</name>
    <message>
        <location filename="../window.py" line="76"/>
        <source>Not detected (model missing)</source>
        <translation>未检测（缺少模型）</translation>
    </message>
    <message>
        <location filename="../window.py" line="77"/>
        <source>Probe failed</source>
        <translation>检测失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="78"/>
        <source>Unknown</source>
        <translation>未知</translation>
    </message>
    <message>
        <location filename="../window.py" line="81"/>
        <source>VAD {state}</source>
        <translation>语音切分 {state}</translation>
    </message>
    <message>
        <location filename="../window.py" line="82"/>
        <source>Translation {state}</source>
        <translation>翻译 {state}</translation>
    </message>
    <message>
        <location filename="../window.py" line="87"/>
        <source>Device: CUDA · {gpu} (ASR ✓ / VAD ✓ / Translation ✓)</source>
        <translation>运行设备：CUDA · {gpu}（ASR ✓ / VAD ✓ / 翻译 ✓）</translation>
    </message>
    <message>
        <location filename="../window.py" line="89"/>
        <source>Device: partial CUDA · {gpu} ({parts})</source>
        <translation>运行设备：部分 CUDA · {gpu}（{parts}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="90"/>
        <source>Device: CUDA unavailable; ASR cannot start ({parts})</source>
        <translation>运行设备：CUDA 不可用，ASR 无法启动（{parts}）</translation>
    </message>
</context>
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../window.py" line="730"/>
        <source>Japanese Video Subtitle Tool</source>
        <translation>日语视频中文字幕工具</translation>
    </message>
    <message>
        <location filename="../window.py" line="731"/>
        <source>Input tasks (drop videos or folders here)</source>
        <translation>输入任务（可直接拖入视频或文件夹）</translation>
    </message>
    <message>
        <location filename="../window.py" line="733"/>
        <source>Video</source>
        <translation>视频</translation>
    </message>
    <message>
        <location filename="../window.py" line="733"/>
        <source>Status</source>
        <translation>状态</translation>
    </message>
    <message>
        <location filename="../window.py" line="733"/>
        <source>Progress</source>
        <translation>进度</translation>
    </message>
    <message>
        <location filename="../window.py" line="733"/>
        <source>Output</source>
        <translation>输出</translation>
    </message>
    <message>
        <location filename="../window.py" line="735"/>
        <source>Add videos</source>
        <translation>添加视频</translation>
    </message>
    <message>
        <location filename="../window.py" line="736"/>
        <source>Add folder</source>
        <translation>添加文件夹</translation>
    </message>
    <message>
        <location filename="../window.py" line="737"/>
        <source>Remove selected</source>
        <translation>移除选中</translation>
    </message>
    <message>
        <location filename="../window.py" line="738"/>
        <source>Clear</source>
        <translation>清空</translation>
    </message>
    <message>
        <location filename="../window.py" line="739"/>
        <source>Models and common settings</source>
        <translation>模型与常用设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="740"/>
        <source>ASR model</source>
        <translation>ASR 模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="741"/>
        <source>Translation model</source>
        <translation>翻译模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="744"/>
        <source>Anime (recommended)</source>
        <translation>Anime（推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="748"/>
        <location filename="../window.py" line="885"/>
        <source>GalTransl 7B (recommended)</source>
        <translation>GalTransl 7B（推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="755"/>
        <source>English (Experimental)</source>
        <translation>英文（实验性）</translation>
    </message>
    <message>
        <location filename="../window.py" line="757"/>
        <location filename="../window.py" line="1102"/>
        <source>Probing…</source>
        <translation>检测中…</translation>
    </message>
    <message>
        <location filename="../window.py" line="757"/>
        <location filename="../window.py" line="1107"/>
        <source>Refresh</source>
        <translation>刷新</translation>
    </message>
    <message>
        <location filename="../window.py" line="759"/>
        <source>Output folder</source>
        <translation>输出目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="760"/>
        <source>Work folder</source>
        <translation>工作目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="761"/>
        <source>After success</source>
        <translation>成功后清理</translation>
    </message>
    <message>
        <location filename="../window.py" line="762"/>
        <location filename="../window.py" line="763"/>
        <source>Browse…</source>
        <translation>浏览…</translation>
    </message>
    <message>
        <location filename="../window.py" line="765"/>
        <source>Keep all intermediate files</source>
        <translation>保留全部中间产物</translation>
    </message>
    <message>
        <location filename="../window.py" line="766"/>
        <source>Delete WAV after success</source>
        <translation>成功后删除 WAV</translation>
    </message>
    <message>
        <location filename="../window.py" line="767"/>
        <source>Keep only final subtitles, QC report, and logs</source>
        <translation>成功后仅保留最终字幕、质检和日志</translation>
    </message>
    <message>
        <location filename="../window.py" line="769"/>
        <source>Output and performance</source>
        <translation>输出与性能</translation>
    </message>
    <message>
        <location filename="../window.py" line="771"/>
        <source>Generate bilingual ASS</source>
        <translation>生成双语 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="772"/>
        <source>Generate quality report</source>
        <translation>生成质量报告</translation>
    </message>
    <message>
        <location filename="../window.py" line="777"/>
        <source>ASR batch size</source>
        <translation>ASR 批大小</translation>
    </message>
    <message>
        <location filename="../window.py" line="779"/>
        <source>Performance (24; 14 GB+ VRAM)</source>
        <translation>性能优先（24，14GB以上显存推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="780"/>
        <source>Balanced (16)</source>
        <translation>均衡（16）</translation>
    </message>
    <message>
        <location filename="../window.py" line="781"/>
        <source>Low VRAM (8)</source>
        <translation>低显存（8）</translation>
    </message>
    <message>
        <location filename="../window.py" line="782"/>
        <source>Stability (4)</source>
        <translation>稳定优先（4）</translation>
    </message>
    <message>
        <location filename="../window.py" line="784"/>
        <source>Affects ASR speed and VRAM usage; actual usage varies by model and GPU.</source>
        <translation>影响 ASR 速度和显存占用；不同模型和显卡的实际占用不同。</translation>
    </message>
    <message>
        <location filename="../window.py" line="770"/>
        <source>Scan subfolders</source>
        <translation>扫描子目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="742"/>
        <source>Subtitle language</source>
        <translation>字幕语言</translation>
    </message>
    <message>
        <location filename="../window.py" line="753"/>
        <source>Simplified Chinese</source>
        <translation>简体中文</translation>
    </message>
    <message>
        <location filename="../window.py" line="754"/>
        <source>Traditional Chinese</source>
        <translation>繁体中文</translation>
    </message>
    <message>
        <location filename="../window.py" line="758"/>
        <source>Manage models…</source>
        <translation>管理模型…</translation>
    </message>
    <message>
        <location filename="../window.py" line="773"/>
        <source>Resume completed stages</source>
        <translation>复用已完成阶段</translation>
    </message>
    <message>
        <location filename="../window.py" line="774"/>
        <source>Reuse complete WAV, Japanese SRT, and translated subtitle files; disable this after changing models or key settings.</source>
        <translation>复用完整的 WAV、日文 SRT 和译文字幕；更改模型或关键设置后请关闭此项。</translation>
    </message>
    <message>
        <location filename="../window.py" line="775"/>
        <source>Copy subtitles beside video</source>
        <translation>复制字幕到视频目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="776"/>
        <source>Colour by speaker gender</source>
        <translation>按说话人性别着色</translation>
    </message>
    <message>
        <location filename="../window.py" line="785"/>
        <source>Lower if VRAM is insufficient.</source>
        <translation>显存不足时逐档降低；不同模型和显卡的实际占用不同。</translation>
    </message>
    <message>
        <location filename="../window.py" line="786"/>
        <source>Advanced settings…</source>
        <translation>高级字幕与翻译设置…</translation>
    </message>
    <message>
        <location filename="../window.py" line="787"/>
        <source>Advanced subtitle and translation settings…</source>
        <translation>高级字幕与翻译设置…</translation>
    </message>
    <message>
        <location filename="../window.py" line="788"/>
        <source>Tips</source>
        <translation>使用提示</translation>
    </message>
    <message>
        <location filename="../window.py" line="790"/>
        <source>Drop videos or folders into the left panel
The work folder stores intermediate files; the output folder stores final subtitles
Do not reuse completed stages after changing models or key settings</source>
        <translation>可将视频或文件夹直接拖入左侧
工作目录保存中间产物，输出目录保存最终字幕
更换模型或关键参数后，请勿复用已完成阶段</translation>
    </message>
    <message>
        <location filename="../window.py" line="794"/>
        <source>Show logs</source>
        <translation>显示日志</translation>
    </message>
    <message>
        <location filename="../window.py" line="795"/>
        <source>Drag to resize the log panel</source>
        <translation>拖动调整日志高度</translation>
    </message>
    <message>
        <location filename="../window.py" line="798"/>
        <source>Start</source>
        <translation>开始处理</translation>
    </message>
    <message>
        <location filename="../window.py" line="799"/>
        <source>Cancel</source>
        <translation>取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="800"/>
        <source>Open work folder</source>
        <translation>打开工作目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="801"/>
        <source>Open output folder</source>
        <translation>打开输出目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="802"/>
        <source>Settings</source>
        <translation>设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="803"/>
        <source>Language</source>
        <translation>语言</translation>
    </message>
    <message>
        <location filename="../window.py" line="804"/>
        <source>System language</source>
        <translation>跟随系统语言</translation>
    </message>
    <message>
        <location filename="../window.py" line="808"/>
        <source>Startup and behaviour</source>
        <translation>启动与行为</translation>
    </message>
    <message>
        <location filename="../window.py" line="809"/>
        <source>Probe device at startup</source>
        <translation>启动时检测运行设备</translation>
    </message>
    <message>
        <location filename="../window.py" line="810"/>
        <source>Open output folder when queue finishes</source>
        <translation>队列完成后打开输出目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="811"/>
        <source>Open configuration folder</source>
        <translation>打开配置文件夹</translation>
    </message>
    <message>
        <location filename="../window.py" line="812"/>
        <source>Restore all defaults…</source>
        <translation>恢复全部默认设置…</translation>
    </message>
    <message>
        <location filename="../window.py" line="813"/>
        <source>Help</source>
        <translation>帮助</translation>
    </message>
    <message>
        <location filename="../window.py" line="814"/>
        <source>User guide</source>
        <translation>使用说明</translation>
    </message>
    <message>
        <location filename="../window.py" line="815"/>
        <source>About</source>
        <translation>关于</translation>
    </message>
    <message>
        <location filename="../window.py" line="823"/>
        <source>Waiting for tasks</source>
        <translation>等待任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="988"/>
        <source>Preparing Japanese ASR</source>
        <translation>正在准备日语识别</translation>
    </message>
    <message>
        <location filename="../window.py" line="989"/>
        <source>Loading translation model</source>
        <translation>正在加载翻译模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="990"/>
        <source>Generating bilingual ASS</source>
        <translation>正在生成双语 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="991"/>
        <source>Generating quality report</source>
        <translation>正在生成质量报告</translation>
    </message>
    <message>
        <location filename="../window.py" line="992"/>
        <source>Loading Anime model</source>
        <translation>正在加载 Anime 模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="993"/>
        <source>Running Anime recognition ({current}/{total})</source>
        <translation>正在进行 Anime 识别（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="994"/>
        <source>Running forced alignment ({current}/{total})</source>
        <translation>正在进行强制对齐（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="995"/>
        <source>Running Qwen recognition ({current}/{total})</source>
        <translation>正在进行 Qwen 识别（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="996"/>
        <source>Analysing semantic scenes</source>
        <translation>正在分析语义场景</translation>
    </message>
    <message>
        <location filename="../window.py" line="997"/>
        <source>Analysing speech segments</source>
        <translation>正在分析语音片段</translation>
    </message>
    <message>
        <location filename="../window.py" line="998"/>
        <source>Running Qwen Japanese ASR</source>
        <translation>正在运行 Qwen 日语识别</translation>
    </message>
    <message>
        <location filename="../window.py" line="999"/>
        <source>Finalising Japanese subtitles</source>
        <translation>正在整理日语字幕</translation>
    </message>
    <message>
        <location filename="../window.py" line="1000"/>
        <source>Translating subtitles ({current}/{total})</source>
        <translation>正在翻译字幕（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="1007"/>
        <source>Extracting audio</source>
        <translation>提取音频</translation>
    </message>
    <message>
        <location filename="../window.py" line="1008"/>
        <source>Japanese ASR</source>
        <translation>日语识别</translation>
    </message>
    <message>
        <location filename="../window.py" line="1009"/>
        <source>Chinese translation</source>
        <translation>中文翻译</translation>
    </message>
    <message>
        <location filename="../window.py" line="1010"/>
        <source>Generating ASS</source>
        <translation>生成 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="1011"/>
        <source>Quality check</source>
        <translation>质量检查</translation>
    </message>
    <message>
        <location filename="../window.py" line="1012"/>
        <source>Cleaning intermediate files</source>
        <translation>清理中间产物</translation>
    </message>
    <message>
        <location filename="../window.py" line="1016"/>
        <source>Waiting</source>
        <translation>等待中</translation>
    </message>
    <message>
        <location filename="../window.py" line="1017"/>
        <source>Processing</source>
        <translation>处理中</translation>
    </message>
    <message>
        <location filename="../window.py" line="1018"/>
        <source>Completed</source>
        <translation>已完成</translation>
    </message>
    <message>
        <location filename="../window.py" line="1019"/>
        <source>Failed</source>
        <translation>失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="1020"/>
        <source>Cancelled</source>
        <translation>已取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="1028"/>
        <source>Pipeline stage failed</source>
        <translation>流水线阶段失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="1029"/>
        <source>Task failed</source>
        <translation>任务失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="1030"/>
        <source>Pipeline process crashed</source>
        <translation>流水线进程异常崩溃</translation>
    </message>
    <message>
        <location filename="../window.py" line="1031"/>
        <source>Pipeline exit code: {code}</source>
        <translation>流水线退出码：{code}</translation>
    </message>
    <message>
        <location filename="../window.py" line="1032"/>
        <source>Could not start the pipeline process</source>
        <translation>无法启动流水线进程</translation>
    </message>
    <message>
        <location filename="../window.py" line="1062"/>
        <source>{status}: {error}</source>
        <translation>{status}：{error}</translation>
    </message>
    <message>
        <location filename="../window.py" line="1071"/>
        <source>{video} — {status}</source>
        <translation>{video} — {status}</translation>
    </message>
    <message>
        <location filename="../window.py" line="1076"/>
        <source>Select videos</source>
        <translation>选择视频</translation>
    </message>
    <message>
        <location filename="../window.py" line="1076"/>
        <source>Video files (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)</source>
        <translation>视频文件 (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)</translation>
    </message>
    <message>
        <location filename="../window.py" line="1080"/>
        <source>Select video folder</source>
        <translation>选择视频文件夹</translation>
    </message>
    <message>
        <location filename="../window.py" line="1085"/>
        <source>Select folder</source>
        <translation>选择目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="1100"/>
        <location filename="../window.py" line="1131"/>
        <source>Device: probing CUDA…</source>
        <translation>运行设备：正在检测 CUDA…</translation>
    </message>
    <message>
        <location filename="../window.py" line="1111"/>
        <location filename="../window.py" line="1136"/>
        <source>Device: probe failed</source>
        <translation>运行设备：检测失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="1119"/>
        <location filename="../window.py" line="1138"/>
        <source>Device: could not parse probe result</source>
        <translation>运行设备：检测结果无法解析</translation>
    </message>
    <message>
        <location filename="../window.py" line="1133"/>
        <source>Device: automatic startup probe disabled</source>
        <translation>运行设备：已关闭启动时自动检测</translation>
    </message>
    <message>
        <location filename="../window.py" line="1195"/>
        <source>No tasks</source>
        <translation>没有任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="1195"/>
        <source>Add a video task first.</source>
        <translation>请先添加视频任务。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1201"/>
        <source>ASR batch size must be greater than 0.</source>
        <translation>ASR 批大小必须大于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1202"/>
        <source>Translation context cannot be negative.</source>
        <translation>翻译上下文不能小于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1203"/>
        <source>Translation batch size cannot be negative.</source>
        <translation>翻译批大小不能小于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1204"/>
        <source>Maximum characters per line cannot be negative.</source>
        <translation>每行最大字符数不能小于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1205"/>
        <source>Subtitle font sizes must be greater than 0.</source>
        <translation>字幕字号必须大于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1206"/>
        <source>Subtitle font cannot be empty.</source>
        <translation>字幕字体不能为空。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1207"/>
        <source>The selected translation model does not support this subtitle language.</source>
        <translation>所选翻译模型不支持当前字幕语言。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1210"/>
        <source>Chinese colour</source>
        <translation>中文颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="1210"/>
        <source>Japanese colour</source>
        <translation>日文颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="1211"/>
        <source>Male speaker colour</source>
        <translation>男性颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="1211"/>
        <source>Female speaker colour</source>
        <translation>女性颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="1216"/>
        <source>{field} must use ASS &amp;HAABBGGRR format.</source>
        <translation>{field}必须使用 ASS &amp;HAABBGGRR 格式。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1219"/>
        <source>Invalid settings</source>
        <translation>参数错误</translation>
    </message>
    <message>
        <location filename="../window.py" line="1224"/>
        <source>Models incomplete</source>
        <translation>模型不完整</translation>
    </message>
    <message>
        <location filename="../window.py" line="1224"/>
        <source>The selected models are missing files:
{files}</source>
        <translation>所选模型缺少文件：
{files}</translation>
    </message>
    <message>
        <location filename="../window.py" line="1263"/>
        <source>User guide unavailable</source>
        <translation>无法打开使用说明</translation>
    </message>
    <message>
        <location filename="../window.py" line="1264"/>
        <source>The local user guide could not be found.</source>
        <translation>找不到本地使用说明。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1272"/>
        <source>About jp2zh Subtitle Tool</source>
        <translation>关于 jp2zh 字幕工具</translation>
    </message>
    <message>
        <location filename="../window.py" line="1274"/>
        <source>&lt;b&gt;jp2zh Subtitle Tool&lt;/b&gt;&lt;br&gt;&lt;br&gt;Generate Chinese or experimental English subtitles from Japanese videos with local models.&lt;br&gt;&lt;br&gt;&lt;a href=&quot;https://github.com/chubbyk-uu/jp2zh-video-subs&quot;&gt;Project on GitHub&lt;/a&gt;</source>
        <translation>&lt;b&gt;jp2zh 字幕工具&lt;/b&gt;&lt;br&gt;&lt;br&gt;使用本地模型为日语视频生成中文字幕或实验性英文字幕。&lt;br&gt;&lt;br&gt;&lt;a href=&quot;https://github.com/chubbyk-uu/jp2zh-video-subs&quot;&gt;GitHub 项目主页&lt;/a&gt;</translation>
    </message>
    <message>
        <location filename="../window.py" line="1283"/>
        <source>Restore all defaults</source>
        <translation>恢复全部默认设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="1284"/>
        <source>Reset all GUI settings, including window layout, paths, models, appearance, and language?</source>
        <translation>重置全部 GUI 设置，包括窗口布局、路径、模型、外观和语言吗？</translation>
    </message>
    <message>
        <location filename="../window.py" line="1310"/>
        <source>{count} models missing or incomplete</source>
        <translation>缺少或不完整的模型：{count} 个</translation>
    </message>
    <message>
        <location filename="../window.py" line="1312"/>
        <source>{count} models missing</source>
        <translation>缺少 {count} 个模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="1322"/>
        <source>Selected model files are complete</source>
        <translation>所选模型文件完整</translation>
    </message>
    <message>
        <location filename="../window.py" line="1514"/>
        <source>Custom (batch size {value})</source>
        <translation>自定义（批大小 {value}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="1520"/>
        <source>Task still running</source>
        <translation>任务仍在运行</translation>
    </message>
    <message>
        <location filename="../window.py" line="1520"/>
        <source>Cancel the current task and exit?</source>
        <translation>取消当前任务并退出吗？</translation>
    </message>
    <message>
        <location filename="../window.py" line="1535"/>
        <source>Queue finished</source>
        <translation>队列处理结束</translation>
    </message>
</context>
<context>
    <name>ModelDownloadController</name>
    <message>
        <location filename="../model_download.py" line="212"/>
        <source>Could not start the model downloader.</source>
        <translation>无法启动模型下载程序。</translation>
    </message>
</context>
<context>
    <name>ModelDownloadDialog</name>
    <message>
        <location filename="../model_download.py" line="497"/>
        <source>No models selected</source>
        <translation>未选择模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="498"/>
        <source>Select at least one missing or partial model first.</source>
        <translation>请先选择至少一个缺失或未完整下载的模型。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="514"/>
        <source>Models already installed</source>
        <translation>模型已安装</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="516"/>
        <source>The selected models are already installed. Use Re-download selected to replace them.</source>
        <translation>所选模型均已安装。如需覆盖，请使用“重新下载所选”。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="555"/>
        <source>Download mode: prefer Hugging Face/Xet with compatibility fallback</source>
        <translation>下载模式：优先使用 Hugging Face/Xet，失败时切换兼容方式</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="558"/>
        <source>Download mode: compatibility HTTP only</source>
        <translation>下载模式：仅使用兼容 HTTP</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="590"/>
        <source>Nothing to delete</source>
        <translation>没有可删除的内容</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="591"/>
        <source>None of the selected models has local files.</source>
        <translation>所选模型均没有本地文件。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="597"/>
        <source>Delete selected models</source>
        <translation>删除所选模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="599"/>
        <source>Permanently delete these models, including cached and partial files?

{models}</source>
        <translation>确定永久删除以下模型，包括缓存和未完整文件吗？

{models}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="614"/>
        <source>Model path is not a normal directory</source>
        <translation>模型路径不是普通目录</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="626"/>
        <source>Could not delete some models</source>
        <translation>部分模型无法删除</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="631"/>
        <source>{count} models deleted</source>
        <translation>已删除 {count} 个模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="640"/>
        <source>Refusing to delete a path outside the models folder</source>
        <translation>拒绝删除模型目录之外的路径</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="646"/>
        <source>Cancelling; partial files will be kept…</source>
        <translation>正在取消；将保留未完整下载的文件…</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="676"/>
        <source>{count} models queued</source>
        <translation>已将 {count} 个模型加入队列</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="684"/>
        <source>Downloading {model} ({current}/{total})</source>
        <translation>正在下载 {model}（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="701"/>
        <source>Unknown download error</source>
        <translation>未知下载错误</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="702"/>
        <source>Download failed: {error}</source>
        <translation>下载失败：{error}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="708"/>
        <source>{count} models downloaded successfully</source>
        <translation>已成功下载 {count} 个模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="728"/>
        <location filename="../model_download.py" line="765"/>
        <source>unknown</source>
        <translation>未知</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="476"/>
        <source>The proxy port is invalid.</source>
        <translation>代理端口无效。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="486"/>
        <source>Enter an HTTP proxy such as http://127.0.0.1:7890 without a username or password.</source>
        <translation>请输入不含用户名和密码的 HTTP 代理，例如 http://127.0.0.1:7890。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="526"/>
        <source>Invalid proxy</source>
        <translation>代理无效</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="534"/>
        <source>Source: {source}</source>
        <translation>下载源：{source}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="539"/>
        <source>Proxy: {proxy}</source>
        <translation>代理：{proxy}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="541"/>
        <source>Proxy: disabled</source>
        <translation>代理：未启用</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="544"/>
        <source>Mode: re-download and replace</source>
        <translation>模式：重新下载并替换</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="546"/>
        <source>Mode: download missing or partial models</source>
        <translation>模式：下载缺失或不完整的模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="549"/>
        <source>Selected models: {models}</source>
        <translation>已选模型：{models}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="718"/>
        <source>Download helper started.</source>
        <translation>下载辅助进程已启动。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="721"/>
        <source>Querying metadata: {model}</source>
        <translation>正在查询元数据：{model}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="731"/>
        <source>Queued: {model} ({size})</source>
        <translation>已加入队列：{model}（{size}）</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="738"/>
        <source>Skipped installed model: {model}</source>
        <translation>已跳过安装完成的模型：{model}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="742"/>
        <source>Downloading: {model}</source>
        <translation>正在下载：{model}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="746"/>
        <source>Completed: {model}</source>
        <translation>下载完成：{model}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="750"/>
        <source>Error: {error}</source>
        <translation>错误：{error}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="755"/>
        <source>Download queue completed.</source>
        <translation>下载队列已完成。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="767"/>
        <source>{downloaded} / {total} · average {speed}/s</source>
        <translation>{downloaded} / {total} · 平均 {speed}/秒</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="779"/>
        <source>Download cancelled; partial files were kept.</source>
        <translation>下载已取消；已保留未完整下载的文件。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="782"/>
        <source>Model download failed.</source>
        <translation>模型下载失败。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="803"/>
        <source>Anime speech recognition</source>
        <translation>Anime 日语识别</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="804"/>
        <source>Speech segmentation</source>
        <translation>语音切分</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="805"/>
        <source>Subtitle timestamp alignment</source>
        <translation>字幕时间轴对齐</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="806"/>
        <source>Recommended Chinese translation</source>
        <translation>推荐的中文翻译</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="807"/>
        <source>Optional Qwen speech recognition</source>
        <translation>可选的 Qwen 日语识别</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="808"/>
        <source>Optional Chinese translation</source>
        <translation>可选的中文翻译</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="809"/>
        <source>Experimental English translation</source>
        <translation>实验性英文翻译</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="810"/>
        <source>Optional speaker colouring</source>
        <translation>可选的说话人配色</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="812"/>
        <source>Model download</source>
        <translation>模型下载</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="841"/>
        <source>Installed</source>
        <translation>已安装</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="842"/>
        <source>Partial; resumable</source>
        <translation>未完整；可续传</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="843"/>
        <source>Missing</source>
        <translation>缺失</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="844"/>
        <source>Querying…</source>
        <translation>正在查询…</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="845"/>
        <source>Downloading…</source>
        <translation>正在下载…</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="846"/>
        <source>Failed</source>
        <translation>失败</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="854"/>
        <source>Third-party mirror; do not use a private access token.</source>
        <translation>第三方镜像；请勿使用私有访问令牌。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="860"/>
        <source>Model manager</source>
        <translation>模型管理</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="861"/>
        <source>Download source</source>
        <translation>下载来源</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="864"/>
        <source>Hugging Face official</source>
        <translation>Hugging Face 官方站</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="868"/>
        <source>HF-Mirror (third-party)</source>
        <translation>HF-Mirror（第三方）</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="870"/>
        <source>Use proxy</source>
        <translation>使用代理</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="874"/>
        <source>Optional HTTP proxy used only by model downloads, for example http://127.0.0.1:7890.</source>
        <translation>仅模型下载使用的可选 HTTP 代理，例如 http://127.0.0.1:7890。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="879"/>
        <source>Prefer Hugging Face/Xet (recommended)</source>
        <translation>优先使用 Hugging Face/Xet（推荐）</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="883"/>
        <source>Turn this off to use resumable compatibility HTTP directly.</source>
        <translation>取消勾选后直接使用支持断点续传的兼容 HTTP。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="888"/>
        <source>Download</source>
        <translation>下载</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="889"/>
        <source>Model</source>
        <translation>模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="890"/>
        <source>Purpose</source>
        <translation>用途</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="891"/>
        <source>Status</source>
        <translation>状态</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="892"/>
        <source>Size</source>
        <translation>大小</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="898"/>
        <source>Select current configuration</source>
        <translation>选择当前配置所需模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="899"/>
        <source>Select all missing</source>
        <translation>选择全部缺失模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="900"/>
        <source>Delete selected…</source>
        <translation>删除所选…</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="901"/>
        <source>Ready</source>
        <translation>就绪</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="902"/>
        <source>Current model</source>
        <translation>当前模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="903"/>
        <source>Show download details</source>
        <translation>显示下载详情</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="906"/>
        <source>Download details will appear after a task starts.</source>
        <translation>任务开始后将在此显示下载详情。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="908"/>
        <source>Download selected</source>
        <translation>下载所选</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="909"/>
        <source>Re-download selected</source>
        <translation>重新下载所选</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="910"/>
        <source>Cancel download</source>
        <translation>取消下载</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="911"/>
        <source>Close</source>
        <translation>关闭</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="921"/>
        <source>Cancel model download</source>
        <translation>取消模型下载</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="922"/>
        <source>Cancel the current download, keep partial files, and close this window?</source>
        <translation>取消当前下载、保留未完整文件并关闭此窗口吗？</translation>
    </message>
</context>
<context>
    <name>PipelineController</name>
    <message>
        <location filename="../controller.py" line="71"/>
        <source>Could not write cancellation file: {error}</source>
        <translation>无法写入取消文件：{error}</translation>
    </message>
    <message>
        <location filename="../controller.py" line="73"/>
        <source>Cancellation requested; waiting for the current stage to exit safely…</source>
        <translation>已请求取消，正在等待当前阶段安全退出……</translation>
    </message>
    <message>
        <location filename="../controller.py" line="120"/>
        <source>▶ Starting: {video}</source>
        <translation>▶ 开始处理：{video}</translation>
    </message>
    <message>
        <location filename="../controller.py" line="150"/>
        <source>Could not parse pipeline event: {error}</source>
        <translation>事件解析失败：{error}</translation>
    </message>
    <message>
        <location filename="../controller.py" line="273"/>
        <source>Could not clean GUI runtime files: {error}</source>
        <translation>无法清理 GUI 运行时文件：{error}</translation>
    </message>
</context>
</TS>
