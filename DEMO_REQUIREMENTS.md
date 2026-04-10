# EduInsight Demo 功能需求與開發狀態

> 曉明 2026-04-10 確認的需求。負責開發的 Claude 請讀這份文件。

## Demo 定位

這是**成品預覽圖**，不是 MVP。目的是讓專題評審和組員看到完整產品的理想狀態。

## 情境設定

- 114學年第2學期，**第10週（期中考後）**
- 2 位教授：王教授（資料結構、Python）、張教授（資料庫、資料結構共開）
- 5 位學生交叉修課：
  - A 陳同學：認真但基礎弱，期中考 B-，Binary Tree 反覆卡關
  - B 林同學：進階生，期中考 A，問深度問題
  - C 王同學：重修 Python（去年被當），態度消極，期中考 D
  - D 李同學：期中考 F，第10週完全消失，疑似考慮二退
  - E 張同學：中等偏實作，期中考 C+
- 模擬已累積 10 週使用資料（facts + 對話紀錄都有 backdate）

## 頁面結構

1. `/` Landing — 選學生端/教師端
2. `/student` 學生端 — 模仿台科大 Moodle 藍白配色
3. `/teacher` 教師端 — 深色數據儀表板

## 曉明確認的功能需求

### 學生端

- [x] 5 位學生可切換
- [x] 課程卡片可切換（每位學生修不同課）
- [x] 雷達圖（知識維度掌握度 vs 班級平均）
- [x] 學習軌跡折線圖 + 預測帶
- [x] AI 複習建議（紅黃綠三級）
- [x] AI 觀察到的學習偏好
- [x] **過去的對話紀錄**顯示在聊天面板裡（從 DB messages table 載入）
- [x] AI 聊天支援 **Markdown**（marked.js）
- [x] AI 聊天支援 **LaTeX**（KaTeX）
- [x] AI 聊天支援**內嵌互動 HTML**（iframe srcdoc）
  - 可互動的靜態 HTML 讓學生視覺化與互動式學習
  - 避免純文字對話的限制
  - **可放大到全螢幕**（ESC 或 ✕ 關閉），也可縮小回聊天室
- [x] 課堂即時回饋（方案B）— 匿名標記「聽不懂」
- [x] AI 後端：Claude Haiku（via `claude -p`）

### 教師端

- [x] 3 門課 × 2 教授可切換
- [x] 左側導航可捲動到對應區塊
- [x] 散佈圖（成績 vs AI 互動，四象限識別 at-risk）
- [x] AI 使用時段熱力圖
- [x] 🚨 預警中心（Persistence Score + 風險等級）
- [x] 困難概念排行榜
- [x] 一鍵發送 AI 生成個人化關懷訊息（OnTask 風格）
- [x] 學生詳情 modal（點名字→弱科雷達圖+偏好+軌跡）
- [x] 💬 AI 互動摘要（聚合式，**不暴露原始對話**，隱私設計）
- [x] 趨勢圖、學習偏好/成績分布、AI 行為雷達圖

### 設計決策

- **隱私優先**：老師看聚合分析，看不到逐字對話
  - 老師能看到：「學生A在linked list掙扎3次」
  - 老師看不到：「學生A的具體問句」
  - 學生可自願分享特定對話給老師（主動權在學生）
  - 詳見 `knowledge/eduinsight-設計決策-教師對話可見性.md`

- **線上線下整合（方案B）**：課堂即時回饋
  - 上課時學生匿名標記「聽不懂」
  - 老師端即時看到全班哪個概念多少人不懂

### 資料來源

- 88 條 Lite-Mem facts（5 學生 × 10 週，backdate timestamps）
- 42 條 messages（20 段真實對話，含互動 HTML embed 範例）
- Seed scripts: `scripts/seed_rich_demo.py` + `scripts/seed_conversations.py`
- DB: `eduinsight_demo.db`（.env 設定絕對路徑）

## 待完成 / 需改進

- [ ] 更多互動式 HTML embed 範例（binary tree traversal 視覺化、sorting animation 等）
- [ ] 教師端 AI 互動摘要接真實 DB 資料（目前 hardcoded）
- [x] 新的 AI 對話也要寫入 messages table（commit f55ff4f）
- [ ] Office Hour 預約整合（方案A — 老師見面前看到學生 AI 記憶摘要）
- [ ] NLM 簡報修訂美化
- [ ] 學生端 hardcoded 資料和 API 資料完全統一

## 技術架構

- **記憶層**: Lite-Mem（SQLite + BM25 + Embedding）
- **AI 後端**: ClaudeCLIClient（`claude -p --model haiku`）
- **Web**: FastAPI + 純 HTML/CSS/JS + Chart.js + marked.js + KaTeX
- **LMS**: Moodle REST API（台科大 moodle2.ntust.edu.tw）
- **DB**: eduinsight_demo.db

## 競品研究

詳見 adamant memory: `knowledge/eduinsight-競品研究與-demo-設計情報-2026-04.md`

關鍵借鏡：
- Squirrel AI → 知識圖譜
- Carnegie Learning → APLSE 預測分數
- Khanmigo → AI 使用行為追蹤
- Century Tech → 散佈圖四象限
- OnTask → 條件式個人化反饋
- Civitas → Persistence Score
- Echo360 → 可調權重參與度

## 核心差異化

> 「現有 LMS 只告訴老師『誰考幾分』，EduInsight 告訴老師『誰可能要放棄了、為什麼、怎麼幫他』。」

**數據 → 洞察 → 行動** 的完整閉環
