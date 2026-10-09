# EduInsight

AI 學習助教平台 — 兩種部署模式：

- **Version A — Standalone**：自帶 JWT 登入，不依賴 Moodle，適合 demo / 校外場景
- **Version B — Moodle LTI 1.3**：嵌入 Moodle 課程作為 External Tool，由 Moodle 負責認證

兩個版本共用同一份 codebase 和 [Lite-Mem](https://github.com/eric050828/lite-mem) 記憶核心；切換靠環境變數。

## 架構

```
Next.js Frontend (jiangyanmu/edu-insight, cloned to ../edu-insight-frontend)
   │
   │  Authorization: Bearer <jwt>
   │
   ▼
FastAPI Backend (this repo)
   ├─ /auth/* ............ Version A: JWT 登入 (auth.py)
   ├─ /lti/* ............. Version B: LTI 1.3 launch → JWT (lti.py)
   ├─ /chat .............. AI 助教 (RAG + Lite-Mem)
   ├─ /analytics/* ....... 學生與班級分析
   ├─ /grades/* .......... 成績管理
   ├─ /courses/*/materials  教材管理 (RAG 索引)
   ├─ /quiz/sessions/* ... 即時測驗
   ├─ /interaction/* ..... 投票 / 匿名提問 / 彈幕
   ├─ /attendance/* ...... 點名簽到
   ├─ /reports/* ......... 教學分析報表 + Excel 匯出
   ├─ /lectures/* ........ 課堂錄音 + Whisper 轉文字
   ├─ /classroom/* ....... AI 課堂助理
   └─ /office-hours/* .... Office Hour 預約
   │
   ▼
Lite-Mem (github.com/eric050828/lite-mem) — 記憶核心，唯讀依賴
```

## 快速開始

### 後端（共用）

使用 Python 3.12（`.python-version` 已固定版本）；目前 `uv.lock` 的 Pydantic 相依套件不相容 Python 3.14。Docker 部署與 Vercel 前端連線設定請見 [DEPLOY.md](DEPLOY.md)。

```bash
uv sync
cp .env.example .env  # 預設值即可在本機跑起來
uv run uvicorn eduinsight.app:app --reload
# http://127.0.0.1:8000/health
# http://127.0.0.1:8000/docs (OpenAPI)
```

啟動時會自動：
- 建立 `eduinsight_auth.db`
- Seed 6 個 demo 帳號（teacher / student1001 ~ 1005，密碼分別為 `teacher123` / `student123`）
- 連到 `eduinsight_demo.db` 的 Lite-Mem 記憶

### 前端

```bash
git clone https://github.com/jiangyanmu/edu-insight.git ../edu-insight-frontend
cd ../edu-insight-frontend
bun install
cp .env.example .env.local  # 設定 NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
bun run dev
# http://localhost:3000
```

## Version A — Standalone (JWT)

### 流程

1. 使用者開啟 `/login`
2. 點選「教師端入口」或「學生端入口」（demo 一鍵登入）
3. 或展開「使用帳號密碼登入」輸入自訂帳號
4. 後端 `/auth/login` 回傳 JWT，前端存 localStorage
5. 後續所有 API 呼叫帶 `Authorization: Bearer <jwt>`

### Demo 帳號

安全注意：僅 development 且 demo 啟用時會建立這些帳號；production 使用全新 auth DB，請依 DEPLOY.md 建立管理員。

| 帳號 | 密碼 | 角色 | moodle_user_id |
|---|---|---|---|
| teacher | teacher123 | teacher | — |
| student1001 | student123 | student | 1001 |
| student1002 | student123 | student | 1002 |
| student1003 | student123 | student | 1003 |
| student1004 | student123 | student | 1004（high risk） |
| student1005 | student123 | student | 1005 |

### 切到「只開 JWT、不開 LTI」

```bash
EDUINSIGHT_AUTH_MODE=jwt
```

## Version B — Moodle LTI 1.3

### 部署成 Moodle External Tool

1. **設定環境變數**
   ```
   EDUINSIGHT_AUTH_MODE=lti  # 或 both
   EDUINSIGHT_FRONTEND_URL=https://your-edu-insight.vercel.app
   ```

2. **取得 EduInsight 的 LTI 設定資訊**
   ```
   GET /lti/config
   ```
   回傳要在 Moodle 註冊的 URLs（Tool URL / Login URL / JWKS URL）。

3. **在 Moodle 後台註冊**
   - 站台管理 → 外掛 → External Tool → 管理工具
   - 新增手動設定，填入上述 URLs
   - Privacy 設為 Always 分享 launcher name + email

4. **加入課程**
   - 課程編輯 → 新增活動 → External Tool → 選 EduInsight

### Launch 流程

```
[Moodle 學生點擊]
       │
       ▼  POST /lti/login (OIDC initiation)
   後端
       │
       ▼  redirect to Moodle auth
   Moodle
       │
       ▼  POST /lti/launch (id_token JWT)
   後端 ── 驗證 JWT ── 解 LTI claims ── 自動建 lti_<moodle_id> 帳號
       │
       ▼  redirect to ${FRONTEND_URL}/lti/return?code=<single-use-code>&role=...
   LTI return handler（目前前端未使用 LTI，整合時需實作此步）
       │
       ▼  POST /lti/exchange {"code":"..."} → JWT；移除 URL code → 進入對應角色頁面
```

### 本機驗證 LTI flow（不用 Moodle）

開發時須設定 `EDUINSIGHT_ENV=development`、啟用 demo 與 `EDUINSIGHT_ENABLE_LTI_BRIDGE=true`。Bridge 僅能建立全新身分，拒絕既有帳號與 admin；回傳的 JWT 只透過 Authorization header 使用，禁止放入 URL：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/lti-bridge \
  -H "Content-Type: application/json" \
  -d '{"moodle_user_id":7777,"display_name":"LTI test","role":"student"}' \
  | jq -r .access_token)

# 驗證新帳號；重複呼叫 bridge 會回 409，需使用正常登入流程
curl -s http://127.0.0.1:8000/auth/me -H "Authorization: Bearer $TOKEN"
```

## 主要 API

完整列表見 `/docs`（FastAPI auto-generated）。重點：

| Endpoint | 用途 |
|---|---|
| `POST /chat` | AI 對話（含 Lite-Mem 記憶 + RAG 教材引用） |
| `GET /analytics/student/{id}` | 學生弱項、提問主題、偏好 |
| `GET /analytics/student/{id}/risk` | 學生風險分數（persistence + factors） |
| `GET /analytics/student/{id}/trajectory` | 學習軌跡（時間序列） |
| `GET /analytics/class` | 班級共通困難排行 + 主題分布 |
| `GET /teacher/students` | 教師儀表板：所有學生統計 |
| `GET /teacher/summaries` | 教師快速總覽：每位學生的 AI 摘要 |
| `GET /grades/{course}/overview` | 成績分布 + 排名 + A-F 區間 |
| `GET /reports/export/excel/{course}` | Excel 報表下載（4 工作表） |
| `POST /demo/reset` | 一鍵重置 Demo 資料（5 學生 / 60 facts / 教材 / 成績 / Quiz） |

## 環境變數總覽

完整列表見 `.env.example`。

| 變數 | Version A | Version B | 說明 |
|---|---|---|---|
| `EDUINSIGHT_AUTH_MODE` | `jwt` | `lti` | 預設 `both` |
| `EDUINSIGHT_JWT_SECRET` | ✅ | ✅ | 兩邊都用 |
| `EDUINSIGHT_FRONTEND_URL` | – | ✅ | LTI launch 跳轉目標 |
| `EDUINSIGHT_MOODLE_URL` | – | ✅ | Moodle Web Services |
| `EDUINSIGHT_MOODLE_TOKEN` | – | ✅ | 從 Moodle 後台產生 |
| `EDUINSIGHT_CORS_ORIGINS` | ✅ | ✅ | 前端網址列表 |

## 設計原則

- **Lite-Mem 是套件依賴** — 不修改其原始碼，教育只是它的一種應用情境
- **記憶層與 LLM 分離** — assistant.py 負責記憶操作，LLM provider 可插拔
- **Moodle 標準 API** — 只用官方 Web Services + LTI 1.3，不動 Moodle 核心
- **單一 codebase 雙模式** — 用 env var 切 Version A / B，不分 fork

## 測試

```bash
uv run pytest          # 529+ tests
uv run ruff check .    # lint
```

## Production security notes

Follow the production checklist in [DEPLOY.md](DEPLOY.md) before deployment. Set
`EDUINSIGHT_ENV=production` and a random `EDUINSIGHT_JWT_SECRET` of at least 32 characters;
unsafe defaults fail startup. Docker defaults to production; `.env.example` is for
development and overrides that default when used as an env file. Production disables
demo account seeding and the development LTI bridge. Use a clean persistent auth DB and
provision the initial admin through the trusted command in DEPLOY.md.

Public registration accepts only username, password and display_name, creates students,
and assigns unique Moodle IDs. New production databases default to closed registration;
existing `allow_self_register` settings persist, so check `/admin/settings` on upgrades.
Passwords use UTF-8 byte limits: 8..72 in production, 4..72 in development. Password resets,
role changes and account disabling revoke existing tokens. Old JWTs without a token
version require a fresh login. Duplicate legacy Moodle IDs stop migration until an
administrator reconciles the identities.

Keep `EDUINSIGHT_LOGIN_THROTTLE_ENABLED=true`, use HTTPS and exact CORS origins, and deploy
one worker while login throttles and LTI stores remain process-local. The development
bridge requires explicit `EDUINSIGHT_ENABLE_LTI_BRIDGE=true` and refuses admin roles and
existing accounts. LTI uses a 60-second single-use code exchanged via `POST /lti/exchange`;
JWTs are never included in redirect URLs. The current frontend does not use LTI.

## Phase 2 resource limits

Upload limits apply while receiving multipart data, before the complete upload is
spooled, and again while copying 64 KiB chunks into a temporary file. Oversize
requests return HTTP 413 (`payload_too_large`), including chunked requests without
Content-Length. Other bodies are limited to 1 MiB; setting a multipart Content-Type
on a normal route does not bypass that limit. Upload requests allow an additional
64 KiB for multipart framing/metadata; individual file bytes retain the exact limit.

| Variable | Default | Purpose |
| --- | ---: | --- |
| `EDUINSIGHT_MAX_MATERIAL_BYTES` | 26214400 | Material upload: 25 MiB |
| `EDUINSIGHT_MAX_LECTURE_BYTES` | 209715200 | Lecture audio: 200 MiB |
| `EDUINSIGHT_MAX_IMPORT_BYTES` | 52428800 | Memory JSON import: 50 MiB |
| `EDUINSIGHT_MAX_BODY_BYTES` | 1048576 | Other request bodies: 1 MiB |
| `EDUINSIGHT_MAX_ZIP_UNCOMPRESSED_BYTES` | 209715200 | Office ZIP expansion: 200 MiB |
| `EDUINSIGHT_MAX_ZIP_ENTRIES` | 5000 | ZIP central-directory entries |
| `EDUINSIGHT_MAX_ZIP_COMPRESSION_RATIO` | 100 | Per-entry and aggregate expansion ratio |
| `EDUINSIGHT_MAX_DOCUMENT_PAGES` | 500 | PDF pages / PPTX slides / inspected XLSX sheets |
| `EDUINSIGHT_LLM_CLI_TIMEOUT_SECONDS` | 120 | Claude subprocess deadline |
| `EDUINSIGHT_LLM_CLI_MAX_OUTPUT_BYTES` | 1048576 | Combined stdout + stderr cap |
| `EDUINSIGHT_SQLITE_BUSY_TIMEOUT_MS` | 10000 | Application-owned SQLite connection wait |


All limits must be positive, except the SQLite wait may be zero. Office archives
are inspected before extraction; excessive expansion/entry counts or page counts
fail parsing. Current material formats remain PDF, PPTX, Markdown and text;
DOCX/XLSX ZIP inspection is available without adding format support. Assignment
attachments retain their existing 10 MiB / five-file limits. Forum bodies retain
20,000 characters; direct messages retain 2,000 characters and history pages <=100.
Legacy history/admin query limits are capped at 200.

`/health` returns only status and version publicly and to non-admin users. A valid
admin bearer token enables diagnostics. Client errors use stable messages/codes;
exception details go to server logs. SQLite contention returns HTTP 503 with
`Retry-After: 1`; retry writes only with appropriate application-level handling.

Claude CLI requests use tools/MCP disabled, safe mode, no saved sessions, a fresh
empty temporary working directory and a minimal environment. OS/home locations
and Claude authentication (`ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`) are
retained; unrelated JWT/Moodle/provider/cloud secrets are omitted. Flags were
verified with installed Claude Code **2.1.295** `claude --help`; deployments must
provide a CLI supporting these flags. The CLI and Gemini/OpenAI/Groq clients all
identify retrieved memories/materials/transcripts as untrusted reference data.
See [AUTH_ISOLATION_REPORT.md](AUTH_ISOLATION_REPORT.md) for verification boundaries.
