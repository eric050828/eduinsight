# Supervisor 指示 2026-04-13 (第二十二次)

## 上次指示執行狀況

- [x] **Bug 5 [Critical] — teacher.html layout** — Commit `79b4e8f` 修復了 office-hours-section 的位置。工作目錄中另有一筆未提交的修改（移動 `</div>` 到正確位置），兩筆合起來完整解決了 layout 問題。**實測驗證：`.main` width=1680px, `#mainContent` height=843px。所有 section 可見，sidebar 導航正常滾動。Bug 5 已修復。**
- [x] **Bug 4 — office-hours student_id** — 現在會驗證 "must be numeric"，拒絕非數字輸入。前端送 numeric ID（1001），API 正常回應。**行為正確，不再是 bug。**
- [x] **moodle:2001 name mapping** — `/teacher/summaries` 現在顯示 "林小明（學期模擬）" 而非 "moodle:2001"。**已修復。**
- [x] **Demo quiz session seeding** — `/demo/reset` 後 quiz sessions API 回傳 1 個 seeded session（5 題、3 人作答、closed）。**完成。**
- [ ] **OBS 試錄** — 不再催。

**整體評價：Dev 完成了上次指示的所有 3 個優先項目（Bug 5 layout、Bug 4 類型、moodle:2001 name），外加 demo quiz session seeding。但 teacher.html 有一筆關鍵修改未提交（`</div>` 位置調整），必須 commit。**

## 當前最重要的事（dev 下次必須做這個）

**提交 teacher.html 的未提交修改，然後進入 demo 準備階段。**

工作目錄中 `teacher.html` 有一筆未提交的 `</div>` 位置修復。不提交的話，重建環境或 checkout 到其他 branch 時會丟失 Bug 5 的完整修復。

```bash
git add src/eduinsight/static/teacher.html
git commit -m "fix: correct closing div placement in teacher.html layout"
```

## 發現的問題

### Issue 1 [Low] — 未提交的 teacher.html 修改

**現象：** `git diff HEAD -- src/eduinsight/static/teacher.html` 顯示 `</div>` 的移動。commit `79b4e8f` 只做了部分修復，這筆未提交修改是完整修復的另一半。

**風險：** 如果不提交，checkout/reset/pull 時會丟失修復，Bug 5 會復發。

**修復：** 立刻 commit。

### Issue 2 [Info] — Quiz generate 仍返回空結果

**現象：** `POST /courses/ds101/quiz/generate {"topic":"linked list","count":2}` → `{"questions":[], "chunks_used":2}`

**原因：** ClaudeCLIClient 的 LLM 回應無法被 JSON 解析。RAG 檢索正常。

**不是 bug** — demo 時用手動建立 quiz session 的方式展示。但如果要展示 "AI 出題" 功能，需要真正的 LLM provider。

## 使用測試結果

Server: uvicorn eduinsight.app:app (HEAD `c8ea61f` + uncommitted teacher.html fix)。POST /demo/reset 後測試。

| # | 場景 | 結果 | 問題 |
|---|------|------|------|
| 1 | GET /health | **PASS** | ClaudeCLIClient, 8 users, 69 facts |
| 2 | Landing page (/) | **PASS** | 學生端/教師端入口、Demo 按鈕、Tech Stack |
| 3 | POST /demo/reset | **PASS** | 5 students, 60 memories |
| 4 | Student A 載入 | **PASS** | 12 記憶、3 弱項、雷達圖、軌跡圖、2 段對話、0 errors |
| 5 | Student E 切換 | **PASS** | 資料正確載入、0 errors |
| 6 | Student console errors | **PASS** | 0 errors, 1 warning (無害) |
| 7 | **Teacher dashboard 載入** | **PASS** | **.main width=1680px, mainContent height=843px。Bug 5 已修復** |
| 8 | Teacher 班級總覽 | **PASS** | 52 students, 71.3 avg, 散佈圖可見 |
| 9 | Teacher 預警中心 | **PASS** | 預警列表、困難長條圖、學習曲線圖 |
| 10 | Teacher AI 互動摘要 | **PASS** | 6 學生卡片、risk levels、摘要文字 |
| 11 | Teacher sidebar 導航 → AI 摘要 | **PASS** | scrollIntoView top=50px，元素可見 |
| 12 | Teacher sidebar 導航 → Office Hours | **PASS** | scrollIntoView top=373px，元素可見 |
| 13 | Teacher 課程切換 (Python) | **PASS** | 標題切換、數據更新 (28 students, 76.8 avg) |
| 14 | Teacher console errors | **PASS** | 0 errors, 0 warnings |
| 15 | Quiz session 建立 | **PASS** | session_id 返回, status: waiting |
| 16 | Quiz session 啟動 | **PASS** | status: active |
| 17 | Quiz 學生作答 | **PASS** | is_correct: true |
| 18 | Quiz 即時統計 | **PASS** | correct_rate: 1.0, option_distribution 正確 |
| 19 | Teacher AI summaries API | **PASS** | 6 students, moodle:2001→林小明（學期模擬）|
| 20 | Analytics student 1001 | **PASS** | 12 facts, 3 struggles |
| 21 | Analytics class | **PASS** | 6 students, 61 facts |
| 22 | Analytics risk 1004 | **PASS** | risk_level: low, persistence: 94 |
| 23 | Conversations 1001 | **PASS** | 2 conversations, messages 正確 |
| 24 | Grades overview ds101 | **PASS** | 5 students, mean 38.12 |
| 25 | Reports weekly ds101 | **PASS** | 完整報表含 risk/grades/struggles |
| 26 | RAG materials ds101 | **PASS** | documents: ["ds101_lecture_notes.pdf"] |
| 27 | Quiz generate (linked list) | **PARTIAL** | chunks_used: 2, questions: [] (LLM 限制) |
| 28 | Office-hours bookings (numeric) | **PASS** | 空列表，正常 |
| 29 | Office-hours bookings (string) | **PASS** | 返回 "must be numeric" 驗證訊息 |
| 30 | 529 unit tests | **PASS** | 59.98s, ruff clean |

**總結：28 pass / 0 fail / 1 partial（LLM 限制，非 bug） / 0 未實作。上次的 3 個 fail 全部修復。產品狀態是目前為止最穩定的一次。**

## 方向修正

### 產品已進入 Demo-Ready 狀態

所有核心功能通過實測：

- **學生端**：記憶載入、弱項分析、雷達圖、軌跡圖、對話歷史、AI 助教 ✅
- **教師端**：班級總覽、預警中心、困難分析、學生列表、AI 互動摘要、課程切換、sidebar 導航 ✅
- **即時測驗**：建立→啟動→作答→統計 端到端 ✅
- **成績管理**：overview、rankings ✅
- **API 層**：30 個場景中 28 pass、1 partial（LLM）、0 fail ✅
- **品質**：529 tests、ruff clean ✅

### 進入 Demo 最佳化階段

產品功能完整且穩定。接下來應該把精力放在 **demo 展示效果** 而不是新功能。

## 下一步優先級

### 1.【5 分鐘】提交未提交的 teacher.html 修改

```bash
git add src/eduinsight/static/teacher.html
git commit -m "fix: correct closing div placement in teacher.html layout"
```

### 2.【30 分鐘】Demo 腳本排練 — 定義 demo 路線並驗證順暢度

建議 Demo 路線（3 分鐘版本）：

1. **Landing Page** (15s) — 一鍵 Demo 載入資料
2. **學生端 — A 陳同學** (45s) — 記憶系統展示：弱項分析、雷達圖、軌跡圖
3. **學生端 — AI 對話** (30s) — 問一個問題，展示 AI 用記憶回答
4. **教師端 — 班級總覽** (20s) — 統計卡片、散佈圖
5. **教師端 — 預警中心** (20s) — at-risk 學生、一鍵關懷
6. **教師端 — AI 互動摘要** (15s) — 每位學生的 AI 生成分析
7. **即時測驗** (25s) — 教師出題→學生作答→即時統計
8. **Tech Stack** (10s) — Lite-Mem 記憶層、FastAPI、Chart.js

Dev 可以寫一個 `scripts/demo_script.md` 記錄每一步的操作和預期畫面。

### 3.【20 分鐘】Demo 資料品質提升

目前 demo 資料的幾個小問題：
- 所有學生 `risk_level` 都是 `low`（除了 moodle:2001 是 medium）。Demo 時至少需要 1 個 `high` 風險學生來展示預警功能的價值。
- 成績都是 F（mean 38.12）。雖然能展示功能，但不太真實。可以調整 demo_data 讓成績分佈更自然（A~F 都有）。
- 建議在 `/demo/reset` 中加入一個 `high risk` 學生 profile，讓預警中心更有看頭。

### 4.【可以等】OBS 錄製 Demo 影片

修完以上後再錄。

### 5.【可以等】InnoServe 文件準備

海報、簡報等文件可以等 demo 影片錄好後再做。
