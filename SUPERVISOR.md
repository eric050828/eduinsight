# Supervisor 指示 2026-04-12 (第二十次)

## 上次指示執行狀況

- [x] **Bug 1 [Critical] — RAG/Quiz global 宣告** — 終於修復。`app.py:93` 現在是 `global _memory, _assistant, _llm, _lectures, _rag, _quiz`。RAG materials API 回 200，Quiz generate API 正確拒絕（無教材時給業務邏輯錯誤而非 503）。**驗證通過。**
- [x] **Bug 2 [Low] — student.html sid URL 參數** — 修復。`?sid=1005` 正確載入 E 張同學 (B11209025)，breadcrumb 顯示資料庫系統。**驗證通過。**
- [x] **Bug 3 [Low] — student.html grades 404** — 修復。demo_grades.py 擴展到 ds101/py101/db101 三門課。E 張同學成績正常顯示 50.5 F 排名 2/5。**驗證通過。**
- [x] **出席 UI auto-detect** — 修復。教師端載入時自動偵測 open session，顯示「進行中」和簽到碼 KZCB9W。**驗證通過。**
- [x] **回歸測試** — 新增 `test_app_init.py`（6 tests）防止 global 宣告問題復發。**正確做法。**
- [x] **Commit 79bb2bd** — 一次性修復三個 Bug + 出席 UI + 回歸測試 + .gitignore 清理。Commit message 清晰。
- [ ] **OBS 試錄** — 不再催。

**整體評價：所有三個連續報告未修的 Bug 全部修復並驗證通過。Dev 這次還順手修了出席 UI 的 auto-detect 問題（上次報告第 133 行提到的建議），並加了 6 個回歸測試防止復發。這是正確的修復方式——不只改 code，還加了 guard。513 tests 全過。**

## 當前最重要的事（dev 下次必須做這個）

**修復 Bug 4 — office-hours/bookings API 的 student_id 類型不匹配。**

student.html 送 `?student_id=B11209001`（字串），但 `app.py:2432` 定義為 `student_id: int | None`，導致 422 Unprocessable Content。

```python
# app.py:2430-2434 現在:
async def list_office_hour_bookings(
    course_id: str | None = None,
    student_id: int | None = None,  # ← 問題：student.html 送的是 "B11209001"

# 修復方案 A（推薦）：改成 str
    student_id: str | None = None,

# 修復方案 B：student.html 改送 moodle numeric ID (1001)
```

修完後驗證：
```bash
curl -s "http://localhost:8000/office-hours/bookings?student_id=B11209001" # 不應是 422
```

## 發現的 Bug

### Bug 4 [Low, New] — office-hours/bookings student_id ��型不匹配

**現象：** student.html 載入時 console error: `GET /office-hours/bookings?student_id=B11209001` → 422 Unprocessable Content

**根因：** `app.py:2432` 的 `student_id` 參數定義為 `int`，但 student.html 送的是學號字串 "B11209001"。

**影響範圍：**
- 學生端 console 每次載入都有一個 422 error（不影響其他功能，但不乾淨）
- 學生端的 office-hours 預約查詢功能不 work

**嚴重度：** Low。不影響核心功能，但在 demo 時如果打開 console 會看到紅字。

## 使用測試結果

Server: uvicorn eduinsight.app:app (HEAD commit 79bb2bd)。POST /demo/reset 後用 Playwright + API 測試。

| # | 場景 | 結果 | 問題 |
|---|------|------|------|
| 1 | GET /health | **PASS** | status ok, llm_provider: ClaudeCLIClient, total_users: 7, total_facts: 67 |
| 2 | Landing page (/) | **PASS** | 學生端/教師端入口、Tech Stack、0 errors |
| 3 | POST /demo/reset | **PASS** | 5 students, 60 memories |
| 4 | Student A 載��� | **PASS** | 3 courses / 成績 43.1 F / 排名 3/5 / 0 新 errors |
| 5 | Student ?sid=1005 URL | **PASS** | E 張同學 (B11209025) / 資料庫系統 / **Bug 2 已修** |
| 6 | Student E 按鈕切換 | **PASS** | 成績 50.5 F / 排名 2/5 / breadcrumb 資料庫系統 / **Bug 3 已修** |
| 7 | Student E grades API (db101) | **PASS** | 作業 86.5% + 期中考 82% + 專題 0% = 50.55 |
| 8 | Student office-hours bookings | **FAIL** | 422: student_id int parsing error (Bug 4, new) |
| 9 | RAG materials API (ds101) | **PASS** | 200, documents: [] / **Bug 1 已修** |
| 10 | Quiz generate API (ds101) | **PASS** | 正確業務拒絕「No materials」而非 503 / **Bug 1 已修** |
| 11 | Teacher dashboard 載入 | **PASS** | 17 sidebar sections / 0 errors |
| 12 | Teacher 預警中心 | **PASS** | D 李、C 王、A 陳 |
| 13 | Teacher 出席 auto-detect | **PASS** | 自動顯示「進行中」+ 簽到碼 KZCB9W |
| 14 | Teacher AI 出題 UI | **PASS** | 課程/主題/題數 input |
| 15 | Teacher 成績管理 UI | **PASS** | 評分項目 + 分布 |
| 16 | Teacher 教學分析報表 | **PASS** | weekly + correlation (r=0.31) |
| 17 | Teacher Office Hour UI | **PASS** | 建立時段 + 預約列表 |
| 18 | Grades API py101 | **PASS** | 1001: Lab avg 84.3%, weighted 53.23 |
| 19 | Grades API db101 overview | **PASS** | 5 students, mean 39.09 |
| 20 | Reports weekly ds101 | **PASS** | 6 students, 61 facts |
| 21 | Reports correlation ds101 | **PASS** | r=0.31 弱正相關 |
| 22 | Analytics student 1001 | **PASS** | 12 facts, 3 struggles |
| 23 | Analytics class | **PASS** | 6 students, 61 facts |
| 24 | Lectures ds101 | **PASS** | [] 空列表（正確） |
| 25 | Attendance sessions API | **PASS** | 建立 + list 正常 |
| 26 | Console errors (teacher) | **PASS** | 0 errors |
| 27 | Console errors (student) | **FAIL** | 1 error: office-hours 422 (Bug 4) |
| 28 | 513 unit tests | **PASS** | 63.29s, ruff clean |

**總結：26 pass / 2 fail / 0 未實作。2 個 fail 都是同一個 Bug 4（office-hours student_id 類型）。上次報告的 Bug 1/2/3 全部驗證修復。Core 功能連續十二次全 PASS。**

## 方向修正

### 正面肯定

1. **Bug 修復態度正確** — 一次修三個 Bug，每個都有驗證、有回歸測試。`test_app_init.py` 的 6 個測試直接防止 global 宣告問題復發。這是本專案歷史上最好的一次 Bug 修復 commit。
2. **Demo 成績資料擴展** — 從只有 ds101 擴展到三門課（ds101/py101/db101），讓切換學生的體驗更完整。E 張同學的 db101 成績（作業 86.5%）符合她「資料庫專長」的設定。
3. **513 tests** — 比上次 492 多了 21 個（6 個 app_init + quiz/rag test 重構）。測試覆蓋面繼續增長。
4. **產品穩定度** — 連續十二次核心功能全 PASS。teacher dashboard 0 console errors。student dashboard 從多個 errors 降到只剩 1 個（Bug 4）。

### 問題

1. **Bug 4 (office-hours)** — 低優先級但應該在 commit 前就發現。建議修復時順便確認 student.html 中所有 fetch 呼叫的參數類型是否與 API 定義匹配。
2. **Untracked files** — `docker-compose.moodle.yml`、`docs/`、`src/eduinsight/lti_config.json` 仍在 untracked 狀態。如果是預計要用的，commit 它們；如果不是，加到 .gitignore。

### 產品成熟度評估

從「參賽作品」角度：
- **功能廣度**：17 個教師端 section + 完整學生端 = 非常充足
- **數據深度**：記憶系統 + 成績分析 + 相關性報表 + 預警 = 有說服力
- **穩定度**：513 tests + 連續十二次核心全 PASS = 可以信賴
- **缺口**：RAG→AI 出題→即時測驗的端到端流程未經過真實測試（需要上傳教材才能完整走通）

## 下一步優先級

### 1.【5 分鐘】Bug 4 — office-hours student_id 類型

`app.py:2432`: `student_id: int | None` → `student_id: str | None`
同時檢查 `office_hours.py` 內部是否用 int 做 student_id 比對，確保改成 str 後不會壞��。

### 2.【10 分鐘】整理 untracked files

- `docker-compose.moodle.yml` → 有用就 commit，沒用就刪
- `docs/` → 同上
- `src/eduinsight/lti_config.json` → 同上
- 保持工作目錄乾淨

### 3.【30 分鐘】端到端 RAG → AI 出題 → 即時測驗流程

這是 InnoServe demo 的殺手功能。需要：
1. 上傳一份真實教材 PDF 到 ds101
2. AI 出題（3 題選擇題）
3. 建立即時測驗 session
4. 學生端加入測驗並作答
5. 教師端查看即時統計

如果這條路打通，demo 就有了完整的「教材→AI→互動→分析」閉環。

### 4.【可以等】Demo 影片錄製

功能已經夠完整。建議 Demo 路線（3 分鐘）：
1. Landing → 一鍵 Demo (20s)
2. Student 學習記憶 + AI 對話 (50s)
3. Teacher 預警中心 + 成績分析 + 教學報表 (60s)
4. 教材上傳 → AI 出題 → 即時測驗 (40s)（如果流程打通）
5. 收尾：Tech Stack + 記憶系統架構 (10s)

### 5.【��以等】Moodle 整合實測

Docker Compose 檔案已就位，但還沒做過真實的 Moodle ↔ EduInsight 同步測試。這對評審問「有沒有真的跟 LMS 整合」會很有幫助，但目前功能展示已經足夠有說服力。
