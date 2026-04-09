# EduInsight

AI 學習助教平台 — 接 NTUST Moodle LMS，以 [Lite-Mem](https://github.com/xiaoming/lite-mem) 為記憶層。

## 架構

- **Moodle Client** (`moodle.py`) — 透過 Web Services REST API 取得課程、作業、成績、論壇資料
- **Learning Assistant** (`assistant.py`) — 以 Lite-Mem 記住每位學生的提問、弱點、偏好
- **FastAPI App** (`app.py`) — REST API 供前端 / Moodle plugin 串接

## 快速開始

```bash
# 安裝
uv sync

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入 Moodle token

# 啟動
uv run uvicorn eduinsight.app:app --reload

# 跑測試
uv run pytest
```

## 環境變數

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `EDUINSIGHT_MOODLE_URL` | Moodle 網址 | `https://moodle.ntust.edu.tw` |
| `EDUINSIGHT_MOODLE_TOKEN` | Moodle API token | (必填) |
| `EDUINSIGHT_MEMORY_DB_PATH` | Lite-Mem SQLite 路徑 | `eduinsight.db` |

## 設計原則

- **Lite-Mem 是套件依賴** — 不修改其原始碼，教育只是它的一種應用情境
- **記憶層與 LLM 分離** — assistant.py 負責記憶操作，LLM provider 可插拔
- **Moodle 標準 API** — 只用官方 Web Services，不動 Moodle 核心
