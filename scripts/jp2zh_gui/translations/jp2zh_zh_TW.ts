<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="zh_TW">
<context>
    <name>AdvancedSettingsDialog</name>
    <message>
        <location filename="../window.py" line="257"/>
        <source>Advanced subtitle and translation settings</source>
        <translation>高級字幕與翻譯設定</translation>
    </message>
    <message>
        <location filename="../window.py" line="258"/>
        <source>Number of preceding lines supplied to the translation model; 0 translates each line independently.</source>
        <translation>提供给翻譯模型的前文轮數；0 表示逐句独立翻譯。</translation>
    </message>
    <message>
        <location filename="../window.py" line="260"/>
        <source>Translation context</source>
        <translation>翻譯上下文</translation>
    </message>
    <message>
        <location filename="../window.py" line="262"/>
        <source>These settings affect translation context and grouping, not GPU parallelism.</source>
        <translation>这些參數影响翻譯語境和分組，不是顯存并行參數。</translation>
    </message>
    <message>
        <location filename="../window.py" line="263"/>
        <source>Translation</source>
        <translation>翻譯設定</translation>
    </message>
    <message>
        <location filename="../window.py" line="266"/>
        <source> chars</source>
        <translation> 字</translation>
    </message>
    <message>
        <location filename="../window.py" line="264"/>
        <source>Wrap long subtitles</source>
        <translation>長字幕自動換行</translation>
    </message>
    <message>
        <location filename="../window.py" line="268"/>
        <source>Preferred line length</source>
        <translation>建議每行字元數</translation>
    </message>
    <message>
        <location filename="../window.py" line="272"/>
        <source>Japanese font size</source>
        <translation>日文字号</translation>
    </message>
    <message>
        <location filename="../window.py" line="259"/>
        <source>Maximum number of consecutive subtitles translated together; this is not GPU parallelism.</source>
        <translation>連續成組翻譯的最大字幕條數；不是 GPU 並行數。</translation>
    </message>
    <message>
        <location filename="../window.py" line="261"/>
        <source>Translation batch size</source>
        <translation>翻譯批次大小</translation>
    </message>
    <message>
        <location filename="../window.py" line="265"/>
        <source>Wrap long Chinese text near punctuation and English text at a word boundary</source>
        <translation>中文長句按附近標點換行，英文長句在單字邊界換行</translation>
    </message>
    <message>
        <location filename="../window.py" line="267"/>
        <source>Cue count and timing stay unchanged; English uses a separately evaluated default.</source>
        <translation>字幕條數和時間軸保持不變；英文預設值需單獨評估。</translation>
    </message>
    <message>
        <location filename="../window.py" line="269"/>
        <source>Target subtitle font</source>
        <translation>譯文字幕字體</translation>
    </message>
    <message>
        <location filename="../window.py" line="270"/>
        <source>Japanese subtitle font</source>
        <translation>日文字幕字體</translation>
    </message>
    <message>
        <location filename="../window.py" line="271"/>
        <source>Target font size</source>
        <translation>譯文字幕字號</translation>
    </message>
    <message>
        <location filename="../window.py" line="274"/>
        <source>Target colour</source>
        <translation>譯文字幕顏色</translation>
    </message>
    <message>
        <location filename="../window.py" line="275"/>
        <source>Japanese colour</source>
        <translation>日文色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="276"/>
        <source>Male speaker colour</source>
        <translation>男性色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="277"/>
        <source>Female speaker colour</source>
        <translation>女性色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="283"/>
        <source>Subtitle style</source>
        <translation>字幕样式</translation>
    </message>
    <message>
        <location filename="../window.py" line="284"/>
        <source>Restore defaults</source>
        <translation>恢復默认值</translation>
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
        <translation>{value}（點击選擇色彩）</translation>
    </message>
    <message>
        <location filename="../window.py" line="316"/>
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
        <location filename="../window.py" line="76"/>
        <source>Not detected (model missing)</source>
        <translation>未檢测（缺少模型）</translation>
    </message>
    <message>
        <location filename="../window.py" line="77"/>
        <source>Probe failed</source>
        <translation>檢测失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="78"/>
        <source>Unknown</source>
        <translation>未知</translation>
    </message>
    <message>
        <location filename="../window.py" line="81"/>
        <source>VAD {state}</source>
        <translation>語音切分 {state}</translation>
    </message>
    <message>
        <location filename="../window.py" line="82"/>
        <source>Translation {state}</source>
        <translation>翻譯 {state}</translation>
    </message>
    <message>
        <location filename="../window.py" line="87"/>
        <source>Device: CUDA · {gpu} (ASR ✓ / VAD ✓ / Translation ✓)</source>
        <translation>執行裝置：CUDA · {gpu}（ASR ✓ / VAD ✓ / 翻譯 ✓）</translation>
    </message>
    <message>
        <location filename="../window.py" line="89"/>
        <source>Device: partial CUDA · {gpu} ({parts})</source>
        <translation>執行裝置：部分 CUDA · {gpu}（{parts}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="90"/>
        <source>Device: CUDA unavailable; ASR cannot start ({parts})</source>
        <translation>執行裝置：CUDA 不可用，ASR 無法啟动（{parts}）</translation>
    </message>
</context>
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../window.py" line="730"/>
        <source>Japanese Video Subtitle Tool</source>
        <translation>日文影片中文字幕工具</translation>
    </message>
    <message>
        <location filename="../window.py" line="731"/>
        <source>Input tasks (drop videos or folders here)</source>
        <translation>輸入工作（可直接拖入影片或資料夾）</translation>
    </message>
    <message>
        <location filename="../window.py" line="733"/>
        <source>Video</source>
        <translation>影片</translation>
    </message>
    <message>
        <location filename="../window.py" line="733"/>
        <source>Status</source>
        <translation>状態</translation>
    </message>
    <message>
        <location filename="../window.py" line="733"/>
        <source>Progress</source>
        <translation>進度</translation>
    </message>
    <message>
        <location filename="../window.py" line="733"/>
        <source>Output</source>
        <translation>輸出</translation>
    </message>
    <message>
        <location filename="../window.py" line="735"/>
        <source>Add videos</source>
        <translation>新增影片</translation>
    </message>
    <message>
        <location filename="../window.py" line="736"/>
        <source>Add folder</source>
        <translation>新增資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="737"/>
        <source>Remove selected</source>
        <translation>移除選中</translation>
    </message>
    <message>
        <location filename="../window.py" line="738"/>
        <source>Clear</source>
        <translation>清空</translation>
    </message>
    <message>
        <location filename="../window.py" line="739"/>
        <source>Models and common settings</source>
        <translation>模型與常用設定</translation>
    </message>
    <message>
        <location filename="../window.py" line="740"/>
        <source>ASR model</source>
        <translation>ASR 模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="741"/>
        <source>Translation model</source>
        <translation>翻譯模型</translation>
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
        <translation>英文（實驗性）</translation>
    </message>
    <message>
        <location filename="../window.py" line="757"/>
        <location filename="../window.py" line="1102"/>
        <source>Probing…</source>
        <translation>檢测中…</translation>
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
        <translation>輸出資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="760"/>
        <source>Work folder</source>
        <translation>工作資料夾</translation>
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
        <translation>成功后刪除 WAV</translation>
    </message>
    <message>
        <location filename="../window.py" line="767"/>
        <source>Keep only final subtitles, QC report, and logs</source>
        <translation>成功后仅保留最终字幕、質檢和記錄</translation>
    </message>
    <message>
        <location filename="../window.py" line="769"/>
        <source>Output and performance</source>
        <translation>輸出與性能</translation>
    </message>
    <message>
        <location filename="../window.py" line="771"/>
        <source>Generate bilingual ASS</source>
        <translation>生成双語 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="772"/>
        <source>Generate quality report</source>
        <translation>生成質量报告</translation>
    </message>
    <message>
        <location filename="../window.py" line="777"/>
        <source>ASR batch size</source>
        <translation>ASR 批大小</translation>
    </message>
    <message>
        <location filename="../window.py" line="779"/>
        <source>Performance (24; 14 GB+ VRAM)</source>
        <translation>性能优先（24，14GB以上顯存推荐）</translation>
    </message>
    <message>
        <location filename="../window.py" line="780"/>
        <source>Balanced (16)</source>
        <translation>均衡（16）</translation>
    </message>
    <message>
        <location filename="../window.py" line="781"/>
        <source>Low VRAM (8)</source>
        <translation>低顯存（8）</translation>
    </message>
    <message>
        <location filename="../window.py" line="782"/>
        <source>Stability (4)</source>
        <translation>稳定优先（4）</translation>
    </message>
    <message>
        <location filename="../window.py" line="784"/>
        <source>Affects ASR speed and VRAM usage; actual usage varies by model and GPU.</source>
        <translation>影响 ASR 速度和顯存占用；不同模型和顯卡的实際占用不同。</translation>
    </message>
    <message>
        <location filename="../window.py" line="770"/>
        <source>Scan subfolders</source>
        <translation>掃描子資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="742"/>
        <source>Subtitle language</source>
        <translation>字幕語言</translation>
    </message>
    <message>
        <location filename="../window.py" line="753"/>
        <source>Simplified Chinese</source>
        <translation>簡體中文</translation>
    </message>
    <message>
        <location filename="../window.py" line="754"/>
        <source>Traditional Chinese</source>
        <translation>繁體中文</translation>
    </message>
    <message>
        <location filename="../window.py" line="758"/>
        <source>Manage models…</source>
        <translation>管理模型…</translation>
    </message>
    <message>
        <location filename="../window.py" line="773"/>
        <source>Resume completed stages</source>
        <translation>重用已完成階段</translation>
    </message>
    <message>
        <location filename="../window.py" line="774"/>
        <source>Reuse complete WAV, Japanese SRT, and translated subtitle files; disable this after changing models or key settings.</source>
        <translation>重用完整的 WAV、日文 SRT 和譯文字幕；變更模型或關鍵設定後請關閉此項。</translation>
    </message>
    <message>
        <location filename="../window.py" line="775"/>
        <source>Copy subtitles beside video</source>
        <translation>將字幕複製到影片資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="776"/>
        <source>Colour by speaker gender</source>
        <translation>依說話者性別著色</translation>
    </message>
    <message>
        <location filename="../window.py" line="785"/>
        <source>Lower if VRAM is insufficient.</source>
        <translation>顯存不足時逐級降低；實際用量因模型、顯示卡而異。</translation>
    </message>
    <message>
        <location filename="../window.py" line="786"/>
        <source>Advanced settings…</source>
        <translation>高級字幕與翻譯設定…</translation>
    </message>
    <message>
        <location filename="../window.py" line="787"/>
        <source>Advanced subtitle and translation settings…</source>
        <translation>高級字幕與翻譯設定…</translation>
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
        <translation>可將影片或資料夾直接拖入左側
工作資料夾保存中間產物，輸出資料夾保存最終字幕
更換模型或關鍵參數後，請勿復用已完成階段</translation>
    </message>
    <message>
        <location filename="../window.py" line="794"/>
        <source>Show logs</source>
        <translation>顯示記錄</translation>
    </message>
    <message>
        <location filename="../window.py" line="795"/>
        <source>Drag to resize the log panel</source>
        <translation>拖曳以調整記錄區高度</translation>
    </message>
    <message>
        <location filename="../window.py" line="798"/>
        <source>Start</source>
        <translation>开始處理</translation>
    </message>
    <message>
        <location filename="../window.py" line="799"/>
        <source>Cancel</source>
        <translation>取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="800"/>
        <source>Open work folder</source>
        <translation>開啟工作資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="801"/>
        <source>Open output folder</source>
        <translation>開啟輸出資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="802"/>
        <source>Settings</source>
        <translation>設定</translation>
    </message>
    <message>
        <location filename="../window.py" line="803"/>
        <source>Language</source>
        <translation>語言</translation>
    </message>
    <message>
        <location filename="../window.py" line="804"/>
        <source>System language</source>
        <translation>跟隨系統語言</translation>
    </message>
    <message>
        <location filename="../window.py" line="808"/>
        <source>Startup and behaviour</source>
        <translation>啟動與行為</translation>
    </message>
    <message>
        <location filename="../window.py" line="809"/>
        <source>Probe device at startup</source>
        <translation>啟動時偵測執行裝置</translation>
    </message>
    <message>
        <location filename="../window.py" line="810"/>
        <source>Open output folder when queue finishes</source>
        <translation>佇列完成後開啟輸出資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="811"/>
        <source>Open configuration folder</source>
        <translation>開啟設定資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="812"/>
        <source>Restore all defaults…</source>
        <translation>還原所有預設值…</translation>
    </message>
    <message>
        <location filename="../window.py" line="813"/>
        <source>Help</source>
        <translation>說明</translation>
    </message>
    <message>
        <location filename="../window.py" line="814"/>
        <source>User guide</source>
        <translation>使用說明</translation>
    </message>
    <message>
        <location filename="../window.py" line="815"/>
        <source>About</source>
        <translation>關於</translation>
    </message>
    <message>
        <location filename="../window.py" line="823"/>
        <source>Waiting for tasks</source>
        <translation>等待任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="988"/>
        <source>Preparing Japanese ASR</source>
        <translation>正在准备日語識别</translation>
    </message>
    <message>
        <location filename="../window.py" line="989"/>
        <source>Loading translation model</source>
        <translation>正在加載翻譯模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="990"/>
        <source>Generating bilingual ASS</source>
        <translation>正在生成双語 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="991"/>
        <source>Generating quality report</source>
        <translation>正在生成質量报告</translation>
    </message>
    <message>
        <location filename="../window.py" line="992"/>
        <source>Loading Anime model</source>
        <translation>正在加載 Anime 模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="993"/>
        <source>Running Anime recognition ({current}/{total})</source>
        <translation>正在進行 Anime 識别（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="994"/>
        <source>Running forced alignment ({current}/{total})</source>
        <translation>正在進行強制对齐（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="995"/>
        <source>Running Qwen recognition ({current}/{total})</source>
        <translation>正在進行 Qwen 識别（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="996"/>
        <source>Analysing semantic scenes</source>
        <translation>正在分析語义場景</translation>
    </message>
    <message>
        <location filename="../window.py" line="997"/>
        <source>Analysing speech segments</source>
        <translation>正在分析語音片段</translation>
    </message>
    <message>
        <location filename="../window.py" line="998"/>
        <source>Running Qwen Japanese ASR</source>
        <translation>正在執行 Qwen 日語識别</translation>
    </message>
    <message>
        <location filename="../window.py" line="999"/>
        <source>Finalising Japanese subtitles</source>
        <translation>正在整理日語字幕</translation>
    </message>
    <message>
        <location filename="../window.py" line="1000"/>
        <source>Translating subtitles ({current}/{total})</source>
        <translation>正在翻譯字幕（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="1007"/>
        <source>Extracting audio</source>
        <translation>提取音頻</translation>
    </message>
    <message>
        <location filename="../window.py" line="1008"/>
        <source>Japanese ASR</source>
        <translation>日語識别</translation>
    </message>
    <message>
        <location filename="../window.py" line="1009"/>
        <source>Chinese translation</source>
        <translation>中文字幕翻譯</translation>
    </message>
    <message>
        <location filename="../window.py" line="1010"/>
        <source>Generating ASS</source>
        <translation>生成 ASS</translation>
    </message>
    <message>
        <location filename="../window.py" line="1011"/>
        <source>Quality check</source>
        <translation>質量檢查</translation>
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
        <translation>處理中</translation>
    </message>
    <message>
        <location filename="../window.py" line="1018"/>
        <source>Completed</source>
        <translation>已完成</translation>
    </message>
    <message>
        <location filename="../window.py" line="1019"/>
        <source>Failed</source>
        <translation>失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="1020"/>
        <source>Cancelled</source>
        <translation>已取消</translation>
    </message>
    <message>
        <location filename="../window.py" line="1028"/>
        <source>Pipeline stage failed</source>
        <translation>流水線階段失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="1029"/>
        <source>Task failed</source>
        <translation>任务失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="1030"/>
        <source>Pipeline process crashed</source>
        <translation>流水線進程异常崩溃</translation>
    </message>
    <message>
        <location filename="../window.py" line="1031"/>
        <source>Pipeline exit code: {code}</source>
        <translation>流水線退出碼：{code}</translation>
    </message>
    <message>
        <location filename="../window.py" line="1032"/>
        <source>Could not start the pipeline process</source>
        <translation>無法啟动流水線進程</translation>
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
        <translation>選擇影片</translation>
    </message>
    <message>
        <location filename="../window.py" line="1076"/>
        <source>Video files (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)</source>
        <translation>影片檔案 (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v *.ts)</translation>
    </message>
    <message>
        <location filename="../window.py" line="1080"/>
        <source>Select video folder</source>
        <translation>選擇影片資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="1085"/>
        <source>Select folder</source>
        <translation>選擇資料夾</translation>
    </message>
    <message>
        <location filename="../window.py" line="1100"/>
        <location filename="../window.py" line="1131"/>
        <source>Device: probing CUDA…</source>
        <translation>執行裝置：正在檢测 CUDA…</translation>
    </message>
    <message>
        <location filename="../window.py" line="1111"/>
        <location filename="../window.py" line="1136"/>
        <source>Device: probe failed</source>
        <translation>執行裝置：檢测失敗</translation>
    </message>
    <message>
        <location filename="../window.py" line="1119"/>
        <location filename="../window.py" line="1138"/>
        <source>Device: could not parse probe result</source>
        <translation>執行裝置：檢测結果無法解析</translation>
    </message>
    <message>
        <location filename="../window.py" line="1133"/>
        <source>Device: automatic startup probe disabled</source>
        <translation>執行裝置：已停用啟動時自動偵測</translation>
    </message>
    <message>
        <location filename="../window.py" line="1195"/>
        <source>No tasks</source>
        <translation>没有任务</translation>
    </message>
    <message>
        <location filename="../window.py" line="1195"/>
        <source>Add a video task first.</source>
        <translation>請先新增影片任務。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1201"/>
        <source>ASR batch size must be greater than 0.</source>
        <translation>ASR 批大小必須大于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1202"/>
        <source>Translation context cannot be negative.</source>
        <translation>翻譯上下文不能小於 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1203"/>
        <source>Translation batch size cannot be negative.</source>
        <translation>翻譯批大小不能小於 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1204"/>
        <source>Maximum characters per line cannot be negative.</source>
        <translation>每行最大字元數不能小於 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1205"/>
        <source>Subtitle font sizes must be greater than 0.</source>
        <translation>字幕字号必須大于 0。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1206"/>
        <source>Subtitle font cannot be empty.</source>
        <translation>字幕字體不能為空。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1207"/>
        <source>The selected translation model does not support this subtitle language.</source>
        <translation>所選翻譯模型不支援目前的字幕語言。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1210"/>
        <source>Chinese colour</source>
        <translation>中文色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="1210"/>
        <source>Japanese colour</source>
        <translation>日文色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="1211"/>
        <source>Male speaker colour</source>
        <translation>男性色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="1211"/>
        <source>Female speaker colour</source>
        <translation>女性色彩</translation>
    </message>
    <message>
        <location filename="../window.py" line="1216"/>
        <source>{field} must use ASS &amp;HAABBGGRR format.</source>
        <translation>{field}必須使用 ASS &amp;HAABBGGRR 格式。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1219"/>
        <source>Invalid settings</source>
        <translation>參數錯误</translation>
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
        <translation>所選模型缺少檔案：
{files}</translation>
    </message>
    <message>
        <location filename="../window.py" line="1263"/>
        <source>User guide unavailable</source>
        <translation>無法開啟使用說明</translation>
    </message>
    <message>
        <location filename="../window.py" line="1264"/>
        <source>The local user guide could not be found.</source>
        <translation>找不到本機使用說明。</translation>
    </message>
    <message>
        <location filename="../window.py" line="1272"/>
        <source>About jp2zh Subtitle Tool</source>
        <translation>關於 jp2zh 字幕工具</translation>
    </message>
    <message>
        <location filename="../window.py" line="1274"/>
        <source>&lt;b&gt;jp2zh Subtitle Tool&lt;/b&gt;&lt;br&gt;&lt;br&gt;Generate Chinese or experimental English subtitles from Japanese videos with local models.&lt;br&gt;&lt;br&gt;&lt;a href=&quot;https://github.com/chubbyk-uu/jp2zh-video-subs&quot;&gt;Project on GitHub&lt;/a&gt;</source>
        <translation>&lt;b&gt;jp2zh 字幕工具&lt;/b&gt;&lt;br&gt;&lt;br&gt;使用本機模型為日文影片產生中文字幕或實驗性英文字幕。&lt;br&gt;&lt;br&gt;&lt;a href=&quot;https://github.com/chubbyk-uu/jp2zh-video-subs&quot;&gt;GitHub 專案首頁&lt;/a&gt;</translation>
    </message>
    <message>
        <location filename="../window.py" line="1283"/>
        <source>Restore all defaults</source>
        <translation>還原所有預設值</translation>
    </message>
    <message>
        <location filename="../window.py" line="1284"/>
        <source>Reset all GUI settings, including window layout, paths, models, appearance, and language?</source>
        <translation>重設所有 GUI 設定，包括視窗佈局、路徑、模型、外觀與語言嗎？</translation>
    </message>
    <message>
        <location filename="../window.py" line="1310"/>
        <source>{count} models missing or incomplete</source>
        <translation>缺少或不完整的模型：{count} 個</translation>
    </message>
    <message>
        <location filename="../window.py" line="1312"/>
        <source>{count} models missing</source>
        <translation>缺少 {count} 個模型</translation>
    </message>
    <message>
        <location filename="../window.py" line="1322"/>
        <source>Selected model files are complete</source>
        <translation>所選模型檔案完整</translation>
    </message>
    <message>
        <location filename="../window.py" line="1514"/>
        <source>Custom (batch size {value})</source>
        <translation>自定义（批大小 {value}）</translation>
    </message>
    <message>
        <location filename="../window.py" line="1520"/>
        <source>Task still running</source>
        <translation>任务仍在執行</translation>
    </message>
    <message>
        <location filename="../window.py" line="1520"/>
        <source>Cancel the current task and exit?</source>
        <translation>取消当前任务并退出吗？</translation>
    </message>
    <message>
        <location filename="../window.py" line="1535"/>
        <source>Queue finished</source>
        <translation>队列處理結束</translation>
    </message>
</context>
<context>
    <name>ModelDownloadController</name>
    <message>
        <location filename="../model_download.py" line="212"/>
        <source>Could not start the model downloader.</source>
        <translation>無法啟動模型下載程式。</translation>
    </message>
</context>
<context>
    <name>ModelDownloadDialog</name>
    <message>
        <location filename="../model_download.py" line="497"/>
        <source>No models selected</source>
        <translation>未選取模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="498"/>
        <source>Select at least one missing or partial model first.</source>
        <translation>請先選取至少一個缺少或未完整下載的模型。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="514"/>
        <source>Models already installed</source>
        <translation>模型已安裝</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="516"/>
        <source>The selected models are already installed. Use Re-download selected to replace them.</source>
        <translation>所選模型均已安裝。如需覆蓋，請使用「重新下載所選」。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="555"/>
        <source>Download mode: prefer Hugging Face/Xet with compatibility fallback</source>
        <translation>下載模式：優先使用 Hugging Face/Xet，失敗時切換相容方式</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="558"/>
        <source>Download mode: compatibility HTTP only</source>
        <translation>下載模式：僅使用相容 HTTP</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="590"/>
        <source>Nothing to delete</source>
        <translation>沒有可刪除的內容</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="591"/>
        <source>None of the selected models has local files.</source>
        <translation>所選模型均沒有本機檔案。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="597"/>
        <source>Delete selected models</source>
        <translation>刪除所選模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="599"/>
        <source>Permanently delete these models, including cached and partial files?

{models}</source>
        <translation>確定永久刪除以下模型，包括快取和未完整檔案嗎？

{models}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="614"/>
        <source>Model path is not a normal directory</source>
        <translation>模型路徑不是一般目錄</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="626"/>
        <source>Could not delete some models</source>
        <translation>部分模型無法刪除</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="631"/>
        <source>{count} models deleted</source>
        <translation>已刪除 {count} 個模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="640"/>
        <source>Refusing to delete a path outside the models folder</source>
        <translation>拒絕刪除模型資料夾之外的路徑</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="646"/>
        <source>Cancelling; partial files will be kept…</source>
        <translation>正在取消；將保留未完整下載的檔案…</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="676"/>
        <source>{count} models queued</source>
        <translation>已將 {count} 個模型加入佇列</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="684"/>
        <source>Downloading {model} ({current}/{total})</source>
        <translation>正在下載 {model}（{current}/{total}）</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="701"/>
        <source>Unknown download error</source>
        <translation>未知下載錯誤</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="702"/>
        <source>Download failed: {error}</source>
        <translation>下載失敗：{error}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="708"/>
        <source>{count} models downloaded successfully</source>
        <translation>已成功下載 {count} 個模型</translation>
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
        <translation>代理連接埠無效。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="486"/>
        <source>Enter an HTTP proxy such as http://127.0.0.1:7890 without a username or password.</source>
        <translation>請輸入不含使用者名稱和密碼的 HTTP 代理，例如 http://127.0.0.1:7890。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="526"/>
        <source>Invalid proxy</source>
        <translation>代理無效</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="534"/>
        <source>Source: {source}</source>
        <translation>下載來源：{source}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="539"/>
        <source>Proxy: {proxy}</source>
        <translation>代理：{proxy}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="541"/>
        <source>Proxy: disabled</source>
        <translation>代理：未啟用</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="544"/>
        <source>Mode: re-download and replace</source>
        <translation>模式：重新下載並取代</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="546"/>
        <source>Mode: download missing or partial models</source>
        <translation>模式：下載缺少或不完整的模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="549"/>
        <source>Selected models: {models}</source>
        <translation>已選模型：{models}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="718"/>
        <source>Download helper started.</source>
        <translation>下載輔助程序已啟動。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="721"/>
        <source>Querying metadata: {model}</source>
        <translation>正在查詢中繼資料：{model}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="731"/>
        <source>Queued: {model} ({size})</source>
        <translation>已加入佇列：{model}（{size}）</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="738"/>
        <source>Skipped installed model: {model}</source>
        <translation>已略過安裝完成的模型：{model}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="742"/>
        <source>Downloading: {model}</source>
        <translation>正在下載：{model}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="746"/>
        <source>Completed: {model}</source>
        <translation>下載完成：{model}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="750"/>
        <source>Error: {error}</source>
        <translation>錯誤：{error}</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="755"/>
        <source>Download queue completed.</source>
        <translation>下載佇列已完成。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="767"/>
        <source>{downloaded} / {total} · average {speed}/s</source>
        <translation>{downloaded} / {total} · 平均 {speed}/秒</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="779"/>
        <source>Download cancelled; partial files were kept.</source>
        <translation>下載已取消；已保留未完整下載的檔案。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="782"/>
        <source>Model download failed.</source>
        <translation>模型下載失敗。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="803"/>
        <source>Anime speech recognition</source>
        <translation>Anime 日語辨識</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="804"/>
        <source>Speech segmentation</source>
        <translation>語音切分</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="805"/>
        <source>Subtitle timestamp alignment</source>
        <translation>字幕時間軸對齊</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="806"/>
        <source>Recommended Chinese translation</source>
        <translation>建議的中文翻譯</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="807"/>
        <source>Optional Qwen speech recognition</source>
        <translation>可選的 Qwen 日語辨識</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="808"/>
        <source>Optional Chinese translation</source>
        <translation>可選的中文翻譯</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="809"/>
        <source>Experimental English translation</source>
        <translation>實驗性英文翻譯</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="810"/>
        <source>Optional speaker colouring</source>
        <translation>可選的說話者配色</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="812"/>
        <source>Model download</source>
        <translation>模型下載</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="841"/>
        <source>Installed</source>
        <translation>已安裝</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="842"/>
        <source>Partial; resumable</source>
        <translation>未完整；可續傳</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="843"/>
        <source>Missing</source>
        <translation>缺少</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="844"/>
        <source>Querying…</source>
        <translation>正在查詢…</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="845"/>
        <source>Downloading…</source>
        <translation>正在下載…</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="846"/>
        <source>Failed</source>
        <translation>失敗</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="854"/>
        <source>Third-party mirror; do not use a private access token.</source>
        <translation>第三方鏡像；請勿使用私人存取權杖。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="860"/>
        <source>Model manager</source>
        <translation>模型管理</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="861"/>
        <source>Download source</source>
        <translation>下載來源</translation>
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
        <translation>僅模型下載使用的選用 HTTP 代理，例如 http://127.0.0.1:7890。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="879"/>
        <source>Prefer Hugging Face/Xet (recommended)</source>
        <translation>優先使用 Hugging Face/Xet（建議）</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="883"/>
        <source>Turn this off to use resumable compatibility HTTP directly.</source>
        <translation>取消勾選後直接使用支援續傳的相容 HTTP。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="888"/>
        <source>Download</source>
        <translation>下載</translation>
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
        <translation>狀態</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="892"/>
        <source>Size</source>
        <translation>大小</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="898"/>
        <source>Select current configuration</source>
        <translation>選取目前設定所需模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="899"/>
        <source>Select all missing</source>
        <translation>選取全部缺少的模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="900"/>
        <source>Delete selected…</source>
        <translation>刪除所選…</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="901"/>
        <source>Ready</source>
        <translation>就緒</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="902"/>
        <source>Current model</source>
        <translation>目前模型</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="903"/>
        <source>Show download details</source>
        <translation>顯示下載詳情</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="906"/>
        <source>Download details will appear after a task starts.</source>
        <translation>工作開始後將在此顯示下載詳情。</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="908"/>
        <source>Download selected</source>
        <translation>下載所選</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="909"/>
        <source>Re-download selected</source>
        <translation>重新下載所選</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="910"/>
        <source>Cancel download</source>
        <translation>取消下載</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="911"/>
        <source>Close</source>
        <translation>關閉</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="921"/>
        <source>Cancel model download</source>
        <translation>取消模型下載</translation>
    </message>
    <message>
        <location filename="../model_download.py" line="922"/>
        <source>Cancel the current download, keep partial files, and close this window?</source>
        <translation>要取消目前下載、保留未完整檔案並關閉此視窗嗎？</translation>
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
