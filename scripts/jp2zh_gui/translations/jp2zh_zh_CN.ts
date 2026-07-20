<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="zh_CN">
<context>
    <name>AdvancedSettingsDialog</name>
    <message>
        <location filename="../window.py" line="251"/>
        <source>Advanced subtitle and translation settings</source>
        <translation>高级字幕与翻译设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="252"/>
        <source>Number of preceding lines supplied to the translation model; 0 translates each line independently.</source>
        <translation>提供给翻译模型的前文轮数；0 表示逐句独立翻译。</translation>
    </message>
    <message>
        <location filename="../window.py" line="253"/>
        <source>Maximum number of consecutive subtitles translated together by GalTransl; this is not GPU parallelism.</source>
        <translation>GalTransl 连续字幕成组翻译的最大条数；不是 GPU 并行数。</translation>
    </message>
    <message>
        <location filename="../window.py" line="254"/>
        <source>Translation context</source>
        <translation>翻译上下文</translation>
    </message>
    <message>
        <location filename="../window.py" line="255"/>
        <source>Translation batch size</source>
        <translation>翻译批大小</translation>
    </message>
    <message>
        <location filename="../window.py" line="256"/>
        <source>These settings affect translation context and grouping, not GPU parallelism.</source>
        <translation>这些参数影响翻译语境和分组，不是显存并行参数。</translation>
    </message>
    <message>
        <location filename="../window.py" line="257"/>
        <source>Translation</source>
        <translation>翻译设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="259"/>
        <source>Split at the punctuation nearest the middle when the character limit is exceeded</source>
        <translation>超过指定字数时，按最接近中间的标点分成两行</translation>
    </message>
    <message>
        <location filename="../window.py" line="260"/>
        <source> chars</source>
        <translation> 字</translation>
    </message>
    <message>
        <location filename="../window.py" line="261"/>
        <source>Text is not forcibly wrapped when no suitable punctuation exists; cue count and timing stay unchanged.</source>
        <translation>没有合适标点时不会强行断行；字幕条数和时间轴不变。</translation>
    </message>
    <message>
        <location filename="../window.py" line="258"/>
        <source>Wrap long subtitles</source>
        <translation>长字幕自动换行</translation>
    </message>
    <message>
        <location filename="../window.py" line="262"/>
        <source>Character limit</source>
        <translation>字符上限</translation>
    </message>
    <message>
        <location filename="../window.py" line="263"/>
        <source>Subtitle font</source>
        <translation>字幕字体</translation>
    </message>
    <message>
        <location filename="../window.py" line="264"/>
        <source>Chinese font size</source>
        <translation>中文字号</translation>
    </message>
    <message>
        <location filename="../window.py" line="265"/>
        <source>Japanese font size</source>
        <translation>日文字号</translation>
    </message>
    <message>
        <location filename="../window.py" line="267"/>
        <source>Chinese colour</source>
        <translation>中文颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="268"/>
        <source>Japanese colour</source>
        <translation>日文颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="269"/>
        <source>Male speaker colour</source>
        <translation>男性颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="270"/>
        <source>Female speaker colour</source>
        <translation>女性颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="276"/>
        <source>Subtitle style</source>
        <translation>字幕样式</translation>
    </message>
    <message>
        <location filename="../window.py" line="277"/>
        <source>Restore defaults</source>
        <translation>恢复默认值</translation>
    </message>
    <message>
        <location filename="../window.py" line="278"/>
        <source>OK</source>
        <translation>确定</translation>
    </message>
    <message>
        <location filename="../window.py" line="279"/>
        <source>Cancel</source>
        <translation>取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="293"/>
        <source>{value} (click to choose a colour)</source>
        <translation>{value}（点击选择颜色）</translation>
    </message>
    <message>
        <location filename="../window.py" line="297"/>
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
        <location filename="../window.py" line="69"/>
        <source>Not detected (model missing)</source>
        <translation>未检测（缺少模型）</translation>
    </message>
    <message>
        <location filename="../window.py" line="70"/>
        <source>Probe failed</source>
        <translation>检测失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="71"/>
        <source>Unknown</source>
        <translation>未知</translation>
    </message>
    <message>
        <location filename="../window.py" line="74"/>
        <source>VAD {state}</source>
        <translation>语音切分 {state}</translation>
    </message>
    <message>
        <location filename="../window.py" line="75"/>
        <source>Translation {state}</source>
        <translation>翻译 {state}</translation>
    </message>
    <message>
        <location filename="../window.py" line="80"/>
        <source>Device: CUDA · {gpu} (ASR ✓ / VAD ✓ / Translation ✓)</source>
        <translation>运行设备：CUDA · {gpu}（ASR ✓ / VAD ✓ / 翻译 ✓）</translation>
    </message>
    <message>
        <location filename="../window.py" line="82"/>
        <source>Device: partial CUDA · {gpu} ({parts})</source>
        <translation>运行设备：部分 CUDA · {gpu}（{parts}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="83"/>
        <source>Device: CUDA unavailable; ASR cannot start ({parts})</source>
        <translation>运行设备：CUDA 不可用，ASR 无法启动（{parts}）</translation>
    </message>
</context>
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../window.py" line="655"/>
        <source>Japanese Video Subtitle Tool</source>
        <translation>日语视频中文字幕工具</translation>
    </message>
    <message>
        <location filename="../window.py" line="656"/>
        <source>Input tasks (drop videos or folders here)</source>
        <translation>输入任务（可直接拖入视频或文件夹）</translation>
    </message>
    <message>
        <location filename="../window.py" line="658"/>
        <source>Video</source>
        <translation>视频</translation>
    </message>
    <message>
        <location filename="../window.py" line="658"/>
        <source>Status</source>
        <translation>状态</translation>
    </message>
    <message>
        <location filename="../window.py" line="658"/>
        <source>Progress</source>
        <translation>进度</translation>
    </message>
    <message>
        <location filename="../window.py" line="658"/>
        <source>Output</source>
        <translation>输出</translation>
    </message>
    <message>
        <location filename="../window.py" line="660"/>
        <source>Add videos</source>
        <translation>添加视频</translation>
    </message>
    <message>
        <location filename="../window.py" line="661"/>
        <source>Add folder</source>
        <translation>添加文件夹</translation>
    </message>
    <message>
        <location filename="../window.py" line="662"/>
        <source>Remove selected</source>
        <translation>移除选中</translation>
    </message>
    <message>
        <location filename="../window.py" line="663"/>
        <source>Clear</source>
        <translation>清空</translation>
    </message>
    <message>
        <location filename="../window.py" line="664"/>
        <source>Models and common settings</source>
        <translation>模型与常用设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="665"/>
        <source>ASR model</source>
        <translation>ASR 模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="666"/>
        <source>Translation model</source>
        <translation>翻译模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="668"/>
        <source>Anime (recommended)</source>
        <translation>Anime（推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="672"/>
        <source>GalTransl 7B (recommended)</source>
        <translation>GalTransl 7B（推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="675"/>
        <location filename="../window.py" line="936"/>
        <source>Probing…</source>
        <translation>检测中…</translation>
    </message>
    <message>
        <location filename="../window.py" line="675"/>
        <location filename="../window.py" line="941"/>
        <source>Refresh</source>
        <translation>刷新</translation>
    </message>
    <message>
        <location filename="../window.py" line="676"/>
        <source>Output folder</source>
        <translation>输出目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="677"/>
        <source>Work folder</source>
        <translation>工作目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="678"/>
        <source>After success</source>
        <translation>成功后清理</translation>
    </message>
    <message>
        <location filename="../window.py" line="679"/>
        <location filename="../window.py" line="680"/>
        <source>Browse…</source>
        <translation>浏览…</translation>
    </message>
    <message>
        <location filename="../window.py" line="682"/>
        <source>Keep all intermediate files</source>
        <translation>保留全部中间产物</translation>
    </message>
    <message>
        <location filename="../window.py" line="683"/>
        <source>Delete WAV after success</source>
        <translation>成功后删除 WAV</translation>
    </message>
    <message>
        <location filename="../window.py" line="684"/>
        <source>Keep only final subtitles, QC report, and logs</source>
        <translation>成功后仅保留最终字幕、质检和日志</translation>
    </message>
    <message>
        <location filename="../window.py" line="686"/>
        <source>Output and performance</source>
        <translation>输出与性能</translation>
    </message>
    <message>
        <location filename="../window.py" line="688"/>
        <source>Generate bilingual ASS</source>
        <translation>生成双语 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="689"/>
        <source>Generate quality report</source>
        <translation>生成质量报告</translation>
    </message>
    <message>
        <location filename="../window.py" line="691"/>
        <source>Reuse complete WAV, Japanese SRT, and Chinese translation files; disable this after changing models or key settings.</source>
        <translation>复用已存在的完整 WAV、日语 SRT 和中文翻译；更换模型或参数后应关闭。</translation>
    </message>
    <message>
        <location filename="../window.py" line="694"/>
        <source>ASR batch size</source>
        <translation>ASR 批大小</translation>
    </message>
    <message>
        <location filename="../window.py" line="696"/>
        <source>Performance (24; 14 GB+ VRAM)</source>
        <translation>性能优先（24，14GB以上显存推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="697"/>
        <source>Balanced (16)</source>
        <translation>均衡（16）</translation>
    </message>
    <message>
        <location filename="../window.py" line="698"/>
        <source>Low VRAM (8)</source>
        <translation>低显存（8）</translation>
    </message>
    <message>
        <location filename="../window.py" line="699"/>
        <source>Stability (4)</source>
        <translation>稳定优先（4）</translation>
    </message>
    <message>
        <location filename="../window.py" line="701"/>
        <source>Affects ASR speed and VRAM usage; actual usage varies by model and GPU.</source>
        <translation>影响 ASR 速度和显存占用；不同模型和显卡的实际占用不同。</translation>
    </message>
    <message>
        <location filename="../window.py" line="687"/>
        <source>Scan subfolders</source>
        <translation>扫描子目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="690"/>
        <source>Resume completed stages</source>
        <translation>复用已完成阶段</translation>
    </message>
    <message>
        <location filename="../window.py" line="692"/>
        <source>Copy subtitles beside video</source>
        <translation>复制字幕到视频目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="693"/>
        <source>Colour by speaker gender</source>
        <translation>按说话人性别着色</translation>
    </message>
    <message>
        <location filename="../window.py" line="702"/>
        <source>Lower if VRAM is insufficient; usage varies by model and GPU.</source>
        <translation>显存不足时降低；实际占用因模型和显卡而异。</translation>
    </message>
    <message>
        <location filename="../window.py" line="703"/>
        <source>Advanced subtitle and translation settings…</source>
        <translation>高级字幕与翻译设置…</translation>
    </message>
    <message>
        <location filename="../window.py" line="704"/>
        <source>Tips</source>
        <translation>使用提示</translation>
    </message>
    <message>
        <location filename="../window.py" line="706"/>
        <source>Drop videos or folders into the left panel
The work folder stores intermediate files; the output folder stores final subtitles
Do not reuse completed stages after changing models or key settings</source>
        <translation>可将视频或文件夹直接拖入左侧
工作目录保存中间产物，输出目录保存最终字幕
更换模型或关键参数后，请勿复用已完成阶段</translation>
    </message>
    <message>
        <location filename="../window.py" line="710"/>
        <source>Show logs</source>
        <translation>显示日志</translation>
    </message>
    <message>
        <location filename="../window.py" line="711"/>
        <source>Start</source>
        <translation>开始处理</translation>
    </message>
    <message>
        <location filename="../window.py" line="712"/>
        <source>Cancel</source>
        <translation>取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="713"/>
        <source>Retry failed tasks</source>
        <translation>重试失败任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="714"/>
        <source>Open output folder</source>
        <translation>打开输出目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="715"/>
        <source>Settings</source>
        <translation>设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="716"/>
        <source>Language</source>
        <translation>语言</translation>
    </message>
    <message>
        <location filename="../window.py" line="717"/>
        <source>System language</source>
        <translation>跟随系统语言</translation>
    </message>
    <message>
        <location filename="../window.py" line="721"/>
        <source>Startup and behaviour</source>
        <translation>启动与行为</translation>
    </message>
    <message>
        <location filename="../window.py" line="722"/>
        <source>Probe device at startup</source>
        <translation>启动时检测运行设备</translation>
    </message>
    <message>
        <location filename="../window.py" line="723"/>
        <source>Open output folder when queue finishes</source>
        <translation>队列完成后打开输出目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="724"/>
        <source>Open configuration folder</source>
        <translation>打开配置文件夹</translation>
    </message>
    <message>
        <location filename="../window.py" line="725"/>
        <source>Restore all defaults…</source>
        <translation>恢复全部默认设置…</translation>
    </message>
    <message>
        <location filename="../window.py" line="726"/>
        <source>Help</source>
        <translation>帮助</translation>
    </message>
    <message>
        <location filename="../window.py" line="727"/>
        <source>User guide</source>
        <translation>使用说明</translation>
    </message>
    <message>
        <location filename="../window.py" line="728"/>
        <source>About</source>
        <translation>关于</translation>
    </message>
    <message>
        <location filename="../window.py" line="734"/>
        <source>Waiting for tasks</source>
        <translation>等待任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="822"/>
        <source>Preparing Japanese ASR</source>
        <translation>正在准备日语识别</translation>
    </message>
    <message>
        <location filename="../window.py" line="823"/>
        <source>Loading translation model</source>
        <translation>正在加载翻译模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="824"/>
        <source>Generating bilingual ASS</source>
        <translation>正在生成双语 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="825"/>
        <source>Generating quality report</source>
        <translation>正在生成质量报告</translation>
    </message>
    <message>
        <location filename="../window.py" line="826"/>
        <source>Loading Anime model</source>
        <translation>正在加载 Anime 模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="827"/>
        <source>Running Anime recognition ({current}/{total})</source>
        <translation>正在进行 Anime 识别（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="828"/>
        <source>Running forced alignment ({current}/{total})</source>
        <translation>正在进行强制对齐（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="829"/>
        <source>Running Qwen recognition ({current}/{total})</source>
        <translation>正在进行 Qwen 识别（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="830"/>
        <source>Analysing semantic scenes</source>
        <translation>正在分析语义场景</translation>
    </message>
    <message>
        <location filename="../window.py" line="831"/>
        <source>Analysing speech segments</source>
        <translation>正在分析语音片段</translation>
    </message>
    <message>
        <location filename="../window.py" line="832"/>
        <source>Running Qwen Japanese ASR</source>
        <translation>正在运行 Qwen 日语识别</translation>
    </message>
    <message>
        <location filename="../window.py" line="833"/>
        <source>Finalising Japanese subtitles</source>
        <translation>正在整理日语字幕</translation>
    </message>
    <message>
        <location filename="../window.py" line="834"/>
        <source>Translating subtitles ({current}/{total})</source>
        <translation>正在翻译字幕（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="841"/>
        <source>Extracting audio</source>
        <translation>提取音频</translation>
    </message>
    <message>
        <location filename="../window.py" line="842"/>
        <source>Japanese ASR</source>
        <translation>日语识别</translation>
    </message>
    <message>
        <location filename="../window.py" line="843"/>
        <source>Chinese translation</source>
        <translation>中文翻译</translation>
    </message>
    <message>
        <location filename="../window.py" line="844"/>
        <source>Generating ASS</source>
        <translation>生成 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="845"/>
        <source>Quality check</source>
        <translation>质量检查</translation>
    </message>
    <message>
        <location filename="../window.py" line="846"/>
        <source>Cleaning intermediate files</source>
        <translation>清理中间产物</translation>
    </message>
    <message>
        <location filename="../window.py" line="850"/>
        <source>Waiting</source>
        <translation>等待中</translation>
    </message>
    <message>
        <location filename="../window.py" line="851"/>
        <source>Processing</source>
        <translation>处理中</translation>
    </message>
    <message>
        <location filename="../window.py" line="852"/>
        <source>Completed</source>
        <translation>已完成</translation>
    </message>
    <message>
        <location filename="../window.py" line="853"/>
        <source>Failed</source>
        <translation>失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="854"/>
        <source>Cancelled</source>
        <translation>已取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="862"/>
        <source>Pipeline stage failed</source>
        <translation>流水线阶段失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="863"/>
        <source>Task failed</source>
        <translation>任务失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="864"/>
        <source>Pipeline process crashed</source>
        <translation>流水线进程异常崩溃</translation>
    </message>
    <message>
        <location filename="../window.py" line="865"/>
        <source>Pipeline exit code: {code}</source>
        <translation>流水线退出码：{code}</translation>
    </message>
    <message>
        <location filename="../window.py" line="866"/>
        <source>Could not start the pipeline process</source>
        <translation>无法启动流水线进程</translation>
    </message>
    <message>
        <location filename="../window.py" line="896"/>
        <source>{status}: {error}</source>
        <translation>{status}：{error}</translation>
    </message>
    <message>
        <location filename="../window.py" line="905"/>
        <source>{video} — {status}</source>
        <translation>{video} — {status}</translation>
    </message>
    <message>
        <location filename="../window.py" line="910"/>
        <source>Select videos</source>
        <translation>选择视频</translation>
    </message>
    <message>
        <location filename="../window.py" line="910"/>
        <source>Video files (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)</source>
        <translation>视频文件 (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)</translation>
    </message>
    <message>
        <location filename="../window.py" line="914"/>
        <source>Select video folder</source>
        <translation>选择视频文件夹</translation>
    </message>
    <message>
        <location filename="../window.py" line="919"/>
        <source>Select folder</source>
        <translation>选择目录</translation>
    </message>
    <message>
        <location filename="../window.py" line="934"/>
        <location filename="../window.py" line="965"/>
        <source>Device: probing CUDA…</source>
        <translation>运行设备：正在检测 CUDA…</translation>
    </message>
    <message>
        <location filename="../window.py" line="945"/>
        <location filename="../window.py" line="970"/>
        <source>Device: probe failed</source>
        <translation>运行设备：检测失败</translation>
    </message>
    <message>
        <location filename="../window.py" line="953"/>
        <location filename="../window.py" line="972"/>
        <source>Device: could not parse probe result</source>
        <translation>运行设备：检测结果无法解析</translation>
    </message>
    <message>
        <location filename="../window.py" line="967"/>
        <source>Device: automatic startup probe disabled</source>
        <translation>运行设备：已关闭启动时自动检测</translation>
    </message>
    <message>
        <location filename="../window.py" line="1027"/>
        <source>No tasks</source>
        <translation>没有任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="1027"/>
        <source>Add a video first, or retry failed tasks.</source>
        <translation>请先添加视频，或重试失败任务。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1033"/>
        <source>ASR batch size must be greater than 0.</source>
        <translation>ASR 批大小必须大于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1034"/>
        <source>Translation context cannot be negative.</source>
        <translation>翻译上下文不能小于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1035"/>
        <source>Translation batch size cannot be negative.</source>
        <translation>翻译批大小不能小于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1036"/>
        <source>Maximum characters per line cannot be negative.</source>
        <translation>每行最大字符数不能小于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1037"/>
        <source>Subtitle font sizes must be greater than 0.</source>
        <translation>字幕字号必须大于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1038"/>
        <source>Subtitle font cannot be empty.</source>
        <translation>字幕字体不能为空。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1041"/>
        <source>Chinese colour</source>
        <translation>中文颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="1041"/>
        <source>Japanese colour</source>
        <translation>日文颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="1042"/>
        <source>Male speaker colour</source>
        <translation>男性颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="1042"/>
        <source>Female speaker colour</source>
        <translation>女性颜色</translation>
    </message>
    <message>
        <location filename="../window.py" line="1047"/>
        <source>{field} must use ASS &amp;HAABBGGRR format.</source>
        <translation>{field}必须使用 ASS &amp;HAABBGGRR 格式。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1050"/>
        <source>Invalid settings</source>
        <translation>参数错误</translation>
    </message>
    <message>
        <location filename="../window.py" line="1055"/>
        <source>Models incomplete</source>
        <translation>模型不完整</translation>
    </message>
    <message>
        <location filename="../window.py" line="1055"/>
        <source>The selected models are missing files:
{files}</source>
        <translation>所选模型缺少文件：
{files}</translation>
    </message>
    <message>
        <location filename="../window.py" line="1083"/>
        <source>User guide unavailable</source>
        <translation>无法打开使用说明</translation>
    </message>
    <message>
        <location filename="../window.py" line="1084"/>
        <source>The local user guide could not be found.</source>
        <translation>找不到本地使用说明。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1092"/>
        <source>About jp2zh Subtitle Tool</source>
        <translation>关于 jp2zh 字幕工具</translation>
    </message>
    <message>
        <location filename="../window.py" line="1094"/>
        <source>&lt;b&gt;jp2zh Subtitle Tool&lt;/b&gt;&lt;br&gt;&lt;br&gt;Generate Simplified-Chinese subtitles from Japanese videos with local models.&lt;br&gt;&lt;br&gt;&lt;a href=&quot;https://github.com/chubbyk-uu/jp2zh-video-subs&quot;&gt;Project on GitHub&lt;/a&gt;</source>
        <translation>&lt;b&gt;jp2zh 字幕工具&lt;/b&gt;&lt;br&gt;&lt;br&gt;使用本地模型为日语视频生成简体中文字幕。&lt;br&gt;&lt;br&gt;&lt;a href=&quot;https://github.com/chubbyk-uu/jp2zh-video-subs&quot;&gt;GitHub 项目主页&lt;/a&gt;</translation>
    </message>
    <message>
        <location filename="../window.py" line="1103"/>
        <source>Restore all defaults</source>
        <translation>恢复全部默认设置</translation>
    </message>
    <message>
        <location filename="../window.py" line="1104"/>
        <source>Reset all GUI settings, including paths, models, appearance, and language?</source>
        <translation>重置全部 GUI 设置，包括路径、模型、外观和语言吗？</translation>
    </message>
    <message>
        <location filename="../window.py" line="1118"/>
        <source>{count} model files missing</source>
        <translation>缺少 {count} 个模型文件</translation>
    </message>
    <message>
        <location filename="../window.py" line="1122"/>
        <source>Selected model files are complete</source>
        <translation>所选模型文件完整</translation>
    </message>
    <message>
        <location filename="../window.py" line="1256"/>
        <source>Custom (batch size {value})</source>
        <translation>自定义（批大小 {value}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="1262"/>
        <source>Task still running</source>
        <translation>任务仍在运行</translation>
    </message>
    <message>
        <location filename="../window.py" line="1262"/>
        <source>Cancel the current task and exit?</source>
        <translation>取消当前任务并退出吗？</translation>
    </message>
    <message>
        <location filename="../window.py" line="1277"/>
        <source>Queue finished</source>
        <translation>队列处理结束</translation>
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
