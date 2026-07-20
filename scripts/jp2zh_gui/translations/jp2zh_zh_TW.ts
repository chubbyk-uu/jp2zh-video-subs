<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="zh_TW">
<context>
    <name>AdvancedSettingsDialog</name>
    <message>
        <location filename="../window.py" line="249"/>
        <source>Advanced subtitle and translation settings</source>
        <translation>高級字幕與翻譯設定</translation>
    </message>
    <message>
        <location filename="../window.py" line="250"/>
        <source>Number of preceding lines supplied to the translation model; 0 translates each line independently.</source>
        <translation>提供给翻譯模型的前文轮數；0 表示逐句独立翻譯。</translation>
    </message>
    <message>
        <location filename="../window.py" line="251"/>
        <source>Maximum number of consecutive subtitles translated together by GalTransl; this is not GPU parallelism.</source>
        <translation>GalTransl 连续字幕成組翻譯的最大條數；不是 GPU 并行數。</translation>
    </message>
    <message>
        <location filename="../window.py" line="252"/>
        <source>Translation context</source>
        <translation>翻譯上下文</translation>
    </message>
    <message>
        <location filename="../window.py" line="253"/>
        <source>Translation batch size</source>
        <translation>翻譯批大小</translation>
    </message>
    <message>
        <location filename="../window.py" line="254"/>
        <source>These settings affect translation context and grouping, not GPU parallelism.</source>
        <translation>这些參數影响翻譯語境和分組，不是顯存并行參數。</translation>
    </message>
    <message>
        <location filename="../window.py" line="255"/>
        <source>Translation</source>
        <translation>翻譯設定</translation>
    </message>
    <message>
        <location filename="../window.py" line="256"/>
        <source>Split at the punctuation nearest the middle when the character limit is exceeded</source>
        <translation>超過指定字數時，按最接近中间的標點分成兩行</translation>
    </message>
    <message>
        <location filename="../window.py" line="257"/>
        <source> chars</source>
        <translation> 字</translation>
    </message>
    <message>
        <location filename="../window.py" line="258"/>
        <source>Text is not forcibly wrapped when no suitable punctuation exists; cue count and timing stay unchanged.</source>
        <translation>没有合适標點時不会強行断行；字幕條數和時间軸不變。</translation>
    </message>
    <message>
        <location filename="../window.py" line="259"/>
        <source>Wrap long subtitles</source>
        <translation>长字幕自动換行</translation>
    </message>
    <message>
        <location filename="../window.py" line="260"/>
        <source>Subtitle font</source>
        <translation>字幕字體</translation>
    </message>
    <message>
        <location filename="../window.py" line="261"/>
        <source>Chinese font size</source>
        <translation>中文字号</translation>
    </message>
    <message>
        <location filename="../window.py" line="262"/>
        <source>Japanese font size</source>
        <translation>日文字号</translation>
    </message>
    <message>
        <location filename="../window.py" line="264"/>
        <source>Chinese colour</source>
        <translation>中文色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="265"/>
        <source>Japanese colour</source>
        <translation>日文色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="266"/>
        <source>Male speaker colour</source>
        <translation>男性色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="267"/>
        <source>Female speaker colour</source>
        <translation>女性色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="273"/>
        <source>Subtitle style</source>
        <translation>字幕样式</translation>
    </message>
    <message>
        <location filename="../window.py" line="274"/>
        <source>Restore defaults</source>
        <translation>恢復默认值</translation>
    </message>
    <message>
        <location filename="../window.py" line="275"/>
        <source>OK</source>
        <translation>确定</translation>
    </message>
    <message>
        <location filename="../window.py" line="276"/>
        <source>Cancel</source>
        <translation>取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="290"/>
        <source>{value} (click to choose a colour)</source>
        <translation>{value}（點击選擇色彩）</translation>
    </message>
    <message>
        <location filename="../window.py" line="294"/>
        <source>Choose subtitle colour</source>
        <translation>選擇字幕色彩</translation>
    </message>
</context>
<context>
    <name>Application</name>
    <message>
        <location filename="../app.py" line="40"/>
        <source>Application already running</source>
        <translation>程序已在執行</translation>
    </message>
    <message>
        <location filename="../app.py" line="41"/>
        <source>jp2zh Subtitle Tool is already running.</source>
        <translation>jp2zh 字幕工具已经在執行。</translation>
    </message>
</context>
<context>
    <name>DeviceStatus</name>
    <message>
        <location filename="../window.py" line="68"/>
        <source>Not detected (model missing)</source>
        <translation>未檢测（缺少模型）</translation>
    </message>
    <message>
        <location filename="../window.py" line="69"/>
        <source>Probe failed</source>
        <translation>檢测失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="70"/>
        <source>Unknown</source>
        <translation>未知</translation>
    </message>
    <message>
        <location filename="../window.py" line="73"/>
        <source>VAD {state}</source>
        <translation>語音切分 {state}</translation>
    </message>
    <message>
        <location filename="../window.py" line="74"/>
        <source>Translation {state}</source>
        <translation>翻譯 {state}</translation>
    </message>
    <message>
        <location filename="../window.py" line="79"/>
        <source>Device: CUDA · {gpu} (ASR ✓ / VAD ✓ / Translation ✓)</source>
        <translation>執行裝置：CUDA · {gpu}（ASR ✓ / VAD ✓ / 翻譯 ✓）</translation>
    </message>
    <message>
        <location filename="../window.py" line="81"/>
        <source>Device: partial CUDA · {gpu} ({parts})</source>
        <translation>執行裝置：部分 CUDA · {gpu}（{parts}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="82"/>
        <source>Device: CUDA unavailable; ASR cannot start ({parts})</source>
        <translation>執行裝置：CUDA 不可用，ASR 無法啟动（{parts}）</translation>
    </message>
</context>
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../window.py" line="619"/>
        <source>Japanese Video Subtitle Tool</source>
        <translation>日文影片中文字幕工具</translation>
    </message>
    <message>
        <location filename="../window.py" line="620"/>
        <source>Input tasks (drop videos or folders here)</source>
        <translation>輸入工作（可直接拖入影片或資料夾）</translation>
    </message>
    <message>
        <location filename="../window.py" line="622"/>
        <source>Video</source>
        <translation>影片</translation>
    </message>
    <message>
        <location filename="../window.py" line="622"/>
        <source>Status</source>
        <translation>状態</translation>
    </message>
    <message>
        <location filename="../window.py" line="622"/>
        <source>Progress</source>
        <translation>進度</translation>
    </message>
    <message>
        <location filename="../window.py" line="622"/>
        <source>Output</source>
        <translation>輸出</translation>
    </message>
    <message>
        <location filename="../window.py" line="624"/>
        <source>Add videos</source>
        <translation>新增影片</translation>
    </message>
    <message>
        <location filename="../window.py" line="625"/>
        <source>Add folder</source>
        <translation>新增資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="626"/>
        <source>Remove selected</source>
        <translation>移除選中</translation>
    </message>
    <message>
        <location filename="../window.py" line="627"/>
        <source>Clear</source>
        <translation>清空</translation>
    </message>
    <message>
        <location filename="../window.py" line="628"/>
        <source>Models and common settings</source>
        <translation>模型與常用設定</translation>
    </message>
    <message>
        <location filename="../window.py" line="629"/>
        <source>ASR model</source>
        <translation>ASR 模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="630"/>
        <source>Translation model</source>
        <translation>翻譯模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="632"/>
        <source>Anime (recommended)</source>
        <translation>Anime（推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="636"/>
        <source>GalTransl 7B (recommended)</source>
        <translation>GalTransl 7B（推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="639"/>
        <location filename="../window.py" line="878"/>
        <source>Probing…</source>
        <translation>檢测中…</translation>
    </message>
    <message>
        <location filename="../window.py" line="639"/>
        <location filename="../window.py" line="883"/>
        <source>Refresh</source>
        <translation>刷新</translation>
    </message>
    <message>
        <location filename="../window.py" line="640"/>
        <source>Output folder</source>
        <translation>輸出資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="641"/>
        <source>Work folder</source>
        <translation>工作資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="642"/>
        <source>After success</source>
        <translation>成功后清理</translation>
    </message>
    <message>
        <location filename="../window.py" line="643"/>
        <location filename="../window.py" line="644"/>
        <source>Browse…</source>
        <translation>浏览…</translation>
    </message>
    <message>
        <location filename="../window.py" line="646"/>
        <source>Keep all intermediate files</source>
        <translation>保留全部中间产物</translation>
    </message>
    <message>
        <location filename="../window.py" line="647"/>
        <source>Delete WAV after success</source>
        <translation>成功后刪除 WAV</translation>
    </message>
    <message>
        <location filename="../window.py" line="648"/>
        <source>Keep only final subtitles, QC report, and logs</source>
        <translation>成功后仅保留最终字幕、質檢和記錄</translation>
    </message>
    <message>
        <location filename="../window.py" line="650"/>
        <source>Output and performance</source>
        <translation>輸出與性能</translation>
    </message>
    <message>
        <location filename="../window.py" line="652"/>
        <source>Generate bilingual ASS</source>
        <translation>生成双語 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="653"/>
        <source>Generate quality report</source>
        <translation>生成質量报告</translation>
    </message>
    <message>
        <location filename="../window.py" line="655"/>
        <source>Reuse complete WAV, Japanese SRT, and Chinese translation files; disable this after changing models or key settings.</source>
        <translation>復用已存在的完整 WAV、日語 SRT 和中文字幕翻譯；更換模型或參數后应关闭。</translation>
    </message>
    <message>
        <location filename="../window.py" line="658"/>
        <source>ASR batch size</source>
        <translation>ASR 批大小</translation>
    </message>
    <message>
        <location filename="../window.py" line="660"/>
        <source>Performance (24; 14 GB+ VRAM)</source>
        <translation>性能优先（24，14GB以上顯存推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="661"/>
        <source>Balanced (16)</source>
        <translation>均衡（16）</translation>
    </message>
    <message>
        <location filename="../window.py" line="662"/>
        <source>Low VRAM (8)</source>
        <translation>低顯存（8）</translation>
    </message>
    <message>
        <location filename="../window.py" line="663"/>
        <source>Stability (4)</source>
        <translation>稳定优先（4）</translation>
    </message>
    <message>
        <location filename="../window.py" line="665"/>
        <source>Affects ASR speed and VRAM usage; actual usage varies by model and GPU.</source>
        <translation>影响 ASR 速度和顯存占用；不同模型和顯卡的实際占用不同。</translation>
    </message>
    <message>
        <location filename="../window.py" line="651"/>
        <source>Scan subfolders</source>
        <translation>掃描子資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="654"/>
        <source>Resume completed stages</source>
        <translation>重用已完成階段</translation>
    </message>
    <message>
        <location filename="../window.py" line="656"/>
        <source>Copy subtitles beside video</source>
        <translation>將字幕複製到影片資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="657"/>
        <source>Colour by speaker gender</source>
        <translation>依說話者性別著色</translation>
    </message>
    <message>
        <location filename="../window.py" line="666"/>
        <source>Lower if VRAM is insufficient; usage varies by model and GPU.</source>
        <translation>顯示記憶體不足時請降低；實際用量依模型及顯示卡而異。</translation>
    </message>
    <message>
        <location filename="../window.py" line="667"/>
        <source>Advanced subtitle and translation settings…</source>
        <translation>高級字幕與翻譯設定…</translation>
    </message>
    <message>
        <location filename="../window.py" line="668"/>
        <source>Tips</source>
        <translation>使用提示</translation>
    </message>
    <message>
        <location filename="../window.py" line="670"/>
        <source>Drop videos or folders into the left panel

The work folder stores intermediate files; the output folder stores final subtitles

Do not reuse completed stages after changing models or key settings</source>
        <translation>可將影片或檔案夾直接拖入左侧

工作目录保存中间产物，輸出目录保存最终字幕

更換模型或关鍵參數后，請勿復用已完成階段</translation>
    </message>
    <message>
        <location filename="../window.py" line="674"/>
        <source>Show logs</source>
        <translation>顯示記錄</translation>
    </message>
    <message>
        <location filename="../window.py" line="675"/>
        <source>Start</source>
        <translation>开始處理</translation>
    </message>
    <message>
        <location filename="../window.py" line="676"/>
        <source>Cancel</source>
        <translation>取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="677"/>
        <source>Retry failed tasks</source>
        <translation>重試失敗任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="678"/>
        <source>Open output folder</source>
        <translation>開啟輸出資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="679"/>
        <source>Settings</source>
        <translation>設定</translation>
    </message>
    <message>
        <location filename="../window.py" line="680"/>
        <source>Language</source>
        <translation>語言</translation>
    </message>
    <message>
        <location filename="../window.py" line="681"/>
        <source>System language</source>
        <translation>跟隨系統語言</translation>
    </message>
    <message>
        <location filename="../window.py" line="685"/>
        <source>Startup and behaviour</source>
        <translation>啟動與行為</translation>
    </message>
    <message>
        <location filename="../window.py" line="686"/>
        <source>Probe device at startup</source>
        <translation>啟動時偵測執行裝置</translation>
    </message>
    <message>
        <location filename="../window.py" line="687"/>
        <source>Open output folder when queue finishes</source>
        <translation>佇列完成後開啟輸出資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="688"/>
        <source>Open configuration folder</source>
        <translation>開啟設定資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="689"/>
        <source>Restore all defaults…</source>
        <translation>還原所有預設值…</translation>
    </message>
    <message>
        <location filename="../window.py" line="690"/>
        <source>Help</source>
        <translation>說明</translation>
    </message>
    <message>
        <location filename="../window.py" line="691"/>
        <source>User guide</source>
        <translation>使用說明</translation>
    </message>
    <message>
        <location filename="../window.py" line="692"/>
        <source>About</source>
        <translation>關於</translation>
    </message>
    <message>
        <location filename="../window.py" line="697"/>
        <source>Waiting for tasks</source>
        <translation>等待任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="764"/>
        <source>Preparing Japanese ASR</source>
        <translation>正在准备日語識别</translation>
    </message>
    <message>
        <location filename="../window.py" line="765"/>
        <source>Loading translation model</source>
        <translation>正在加載翻譯模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="766"/>
        <source>Generating bilingual ASS</source>
        <translation>正在生成双語 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="767"/>
        <source>Generating quality report</source>
        <translation>正在生成質量报告</translation>
    </message>
    <message>
        <location filename="../window.py" line="768"/>
        <source>Loading Anime model</source>
        <translation>正在加載 Anime 模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="769"/>
        <source>Running Anime recognition ({current}/{total})</source>
        <translation>正在進行 Anime 識别（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="770"/>
        <source>Running forced alignment ({current}/{total})</source>
        <translation>正在進行強制对齐（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="771"/>
        <source>Running Qwen recognition ({current}/{total})</source>
        <translation>正在進行 Qwen 識别（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="772"/>
        <source>Analysing semantic scenes</source>
        <translation>正在分析語义場景</translation>
    </message>
    <message>
        <location filename="../window.py" line="773"/>
        <source>Analysing speech segments</source>
        <translation>正在分析語音片段</translation>
    </message>
    <message>
        <location filename="../window.py" line="774"/>
        <source>Running Qwen Japanese ASR</source>
        <translation>正在執行 Qwen 日語識别</translation>
    </message>
    <message>
        <location filename="../window.py" line="775"/>
        <source>Finalising Japanese subtitles</source>
        <translation>正在整理日語字幕</translation>
    </message>
    <message>
        <location filename="../window.py" line="776"/>
        <source>Translating subtitles ({current}/{total})</source>
        <translation>正在翻譯字幕（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="783"/>
        <source>Extracting audio</source>
        <translation>提取音頻</translation>
    </message>
    <message>
        <location filename="../window.py" line="784"/>
        <source>Japanese ASR</source>
        <translation>日語識别</translation>
    </message>
    <message>
        <location filename="../window.py" line="785"/>
        <source>Chinese translation</source>
        <translation>中文字幕翻譯</translation>
    </message>
    <message>
        <location filename="../window.py" line="786"/>
        <source>Generating ASS</source>
        <translation>生成 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="787"/>
        <source>Quality check</source>
        <translation>質量檢查</translation>
    </message>
    <message>
        <location filename="../window.py" line="788"/>
        <source>Cleaning intermediate files</source>
        <translation>清理中间产物</translation>
    </message>
    <message>
        <location filename="../window.py" line="792"/>
        <source>Waiting</source>
        <translation>等待中</translation>
    </message>
    <message>
        <location filename="../window.py" line="793"/>
        <source>Processing</source>
        <translation>處理中</translation>
    </message>
    <message>
        <location filename="../window.py" line="794"/>
        <source>Completed</source>
        <translation>已完成</translation>
    </message>
    <message>
        <location filename="../window.py" line="795"/>
        <source>Failed</source>
        <translation>失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="796"/>
        <source>Cancelled</source>
        <translation>已取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="804"/>
        <source>Pipeline stage failed</source>
        <translation>流水線階段失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="805"/>
        <source>Task failed</source>
        <translation>任务失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="806"/>
        <source>Pipeline process crashed</source>
        <translation>流水線進程异常崩溃</translation>
    </message>
    <message>
        <location filename="../window.py" line="807"/>
        <source>Pipeline exit code: {code}</source>
        <translation>流水線退出碼：{code}</translation>
    </message>
    <message>
        <location filename="../window.py" line="808"/>
        <source>Could not start the pipeline process</source>
        <translation>無法啟动流水線進程</translation>
    </message>
    <message>
        <location filename="../window.py" line="838"/>
        <source>{status}: {error}</source>
        <translation>{status}：{error}</translation>
    </message>
    <message>
        <location filename="../window.py" line="847"/>
        <source>{video} — {status}</source>
        <translation>{video} — {status}</translation>
    </message>
    <message>
        <location filename="../window.py" line="852"/>
        <source>Select videos</source>
        <translation>選擇影片</translation>
    </message>
    <message>
        <location filename="../window.py" line="852"/>
        <source>Video files (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)</source>
        <translation>影片檔案 (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)</translation>
    </message>
    <message>
        <location filename="../window.py" line="856"/>
        <source>Select video folder</source>
        <translation>選擇影片資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="861"/>
        <source>Select folder</source>
        <translation>選擇資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="876"/>
        <location filename="../window.py" line="907"/>
        <source>Device: probing CUDA…</source>
        <translation>執行裝置：正在檢测 CUDA…</translation>
    </message>
    <message>
        <location filename="../window.py" line="887"/>
        <location filename="../window.py" line="912"/>
        <source>Device: probe failed</source>
        <translation>執行裝置：檢测失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="895"/>
        <location filename="../window.py" line="914"/>
        <source>Device: could not parse probe result</source>
        <translation>執行裝置：檢测結果無法解析</translation>
    </message>
    <message>
        <location filename="../window.py" line="909"/>
        <source>Device: automatic startup probe disabled</source>
        <translation>執行裝置：已停用啟動時自動偵測</translation>
    </message>
    <message>
        <location filename="../window.py" line="969"/>
        <source>No tasks</source>
        <translation>没有任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="969"/>
        <source>Add a video first, or retry failed tasks.</source>
        <translation>請先新增影片，或重試失敗任务。</translation>
    </message>
    <message>
        <location filename="../window.py" line="975"/>
        <source>ASR batch size must be greater than 0.</source>
        <translation>ASR 批大小必須大于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="976"/>
        <source>Translation context cannot be negative.</source>
        <translation>翻譯上下文不能小於 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="977"/>
        <source>Translation batch size cannot be negative.</source>
        <translation>翻譯批大小不能小於 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="978"/>
        <source>Maximum characters per line cannot be negative.</source>
        <translation>每行最大字元數不能小於 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="979"/>
        <source>Subtitle font sizes must be greater than 0.</source>
        <translation>字幕字号必須大于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="980"/>
        <source>Subtitle font cannot be empty.</source>
        <translation>字幕字體不能為空。</translation>
    </message>
    <message>
        <location filename="../window.py" line="983"/>
        <source>Chinese colour</source>
        <translation>中文色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="983"/>
        <source>Japanese colour</source>
        <translation>日文色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="984"/>
        <source>Male speaker colour</source>
        <translation>男性色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="984"/>
        <source>Female speaker colour</source>
        <translation>女性色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="989"/>
        <source>{field} must use ASS &amp;HAABBGGRR format.</source>
        <translation>{field}必須使用 ASS &amp;HAABBGGRR 格式。</translation>
    </message>
    <message>
        <location filename="../window.py" line="992"/>
        <source>Invalid settings</source>
        <translation>參數錯误</translation>
    </message>
    <message>
        <location filename="../window.py" line="997"/>
        <source>Models incomplete</source>
        <translation>模型不完整</translation>
    </message>
    <message>
        <location filename="../window.py" line="997"/>
        <source>The selected models are missing files:
{files}</source>
        <translation>所選模型缺少檔案：
{files}</translation>
    </message>
    <message>
        <location filename="../window.py" line="1025"/>
        <source>User guide unavailable</source>
        <translation>無法開啟使用說明</translation>
    </message>
    <message>
        <location filename="../window.py" line="1026"/>
        <source>The local user guide could not be found.</source>
        <translation>找不到本機使用說明。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1034"/>
        <source>About jp2zh Subtitle Tool</source>
        <translation>關於 jp2zh 字幕工具</translation>
    </message>
    <message>
        <location filename="../window.py" line="1036"/>
        <source>&lt;b&gt;jp2zh Subtitle Tool&lt;/b&gt;&lt;br&gt;&lt;br&gt;Generate Simplified-Chinese subtitles from Japanese videos with local models.&lt;br&gt;&lt;br&gt;&lt;a href=&quot;https://github.com/chubbyk-uu/jp2zh-video-subs&quot;&gt;Project on GitHub&lt;/a&gt;</source>
        <translation>&lt;b&gt;jp2zh 字幕工具&lt;/b&gt;&lt;br&gt;&lt;br&gt;使用本機模型為日文影片產生簡體中文字幕。&lt;br&gt;&lt;br&gt;&lt;a href=&quot;https://github.com/chubbyk-uu/jp2zh-video-subs&quot;&gt;GitHub 專案首頁&lt;/a&gt;</translation>
    </message>
    <message>
        <location filename="../window.py" line="1045"/>
        <source>Restore all defaults</source>
        <translation>還原所有預設值</translation>
    </message>
    <message>
        <location filename="../window.py" line="1046"/>
        <source>Reset all GUI settings, including paths, models, appearance, and language?</source>
        <translation>重設所有 GUI 設定，包括路徑、模型、外觀與語言嗎？</translation>
    </message>
    <message>
        <location filename="../window.py" line="1060"/>
        <source>{count} model files missing</source>
        <translation>缺少 {count} 個模型檔案</translation>
    </message>
    <message>
        <location filename="../window.py" line="1064"/>
        <source>Selected model files are complete</source>
        <translation>所選模型檔案完整</translation>
    </message>
    <message>
        <location filename="../window.py" line="1198"/>
        <source>Custom (batch size {value})</source>
        <translation>自定义（批大小 {value}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="1204"/>
        <source>Task still running</source>
        <translation>任务仍在執行</translation>
    </message>
    <message>
        <location filename="../window.py" line="1204"/>
        <source>Cancel the current task and exit?</source>
        <translation>取消当前任务并退出吗？</translation>
    </message>
    <message>
        <location filename="../window.py" line="1219"/>
        <source>Queue finished</source>
        <translation>队列處理結束</translation>
    </message>
</context>
<context>
    <name>PipelineController</name>
    <message>
        <location filename="../controller.py" line="71"/>
        <source>Could not write cancellation file: {error}</source>
        <translation>無法寫入取消檔案：{error}</translation>
    </message>
    <message>
        <location filename="../controller.py" line="73"/>
        <source>Cancellation requested; waiting for the current stage to exit safely…</source>
        <translation>已要求取消，正在等待目前階段安全結束……</translation>
    </message>
    <message>
        <location filename="../controller.py" line="120"/>
        <source>▶ Starting: {video}</source>
        <translation>▶ 開始處理：{video}</translation>
    </message>
    <message>
        <location filename="../controller.py" line="150"/>
        <source>Could not parse pipeline event: {error}</source>
        <translation>無法解析流程事件：{error}</translation>
    </message>
    <message>
        <location filename="../controller.py" line="273"/>
        <source>Could not clean GUI runtime files: {error}</source>
        <translation>無法清理 GUI 執行階段檔案：{error}</translation>
    </message>
</context>
</TS>
