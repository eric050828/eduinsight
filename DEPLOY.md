# 後端部署

使用 Python 3.12 與現有 `uv.lock`；目前鎖定的 Pydantic 相依套件不相容 Python 3.14。Dockerfile 使用 `python:3.12-slim`，以 `uv sync --frozen --no-dev --no-editable` 安裝相依套件，並啟動：

```sh
uvicorn eduinsight.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

`PORT` 是容器啟動命令使用的連接埠，預設為 8000；它不會讀取 `EDUINSIGHT_PORT`。建置需要連網下載映像、Python 套件與 lockfile 指定的 Lite-Mem Git 版本。

## 環境變數

以 `.env.example` 為基礎，另存 `.env.deploy`，透過部署服務的環境變數或 Docker `--env-file` 注入。映像不包含 `.env`、API 金鑰或本機資料庫。獨立 JWT 部署至少明確設定下列值：

```dotenv
EDUINSIGHT_ENV=production
EDUINSIGHT_DEMO_MODE=false
EDUINSIGHT_ENABLE_LTI_BRIDGE=false
EDUINSIGHT_LOGIN_THROTTLE_ENABLED=true
EDUINSIGHT_AUTH_MODE=jwt
EDUINSIGHT_JWT_SECRET=replace-with-a-random-secret
EDUINSIGHT_JWT_EXPIRE_MINUTES=10080
EDUINSIGHT_MEMORY_DB_PATH=/data/eduinsight.db
EDUINSIGHT_AUTH_DB_PATH=/data/eduinsight_auth.db
EDUINSIGHT_CORS_ORIGINS=https://edu-insight-two.vercel.app
EDUINSIGHT_FRONTEND_URL=https://edu-insight-two.vercel.app
```

用 `python -c "import secrets; print(secrets.token_hex(32))"` 產生 JWT secret，替換範例值。相同部署的各次重啟應使用相同 secret；更換後既有 JWT 將失效。

其餘 `.env.example` 的 `EDUINSIGHT_*` 設定如下：

| 變數 | 用途 |
| --- | --- |
| `EDUINSIGHT_MEMORY_TOP_K` | 記憶搜尋筆數，預設 8。 |
| `EDUINSIGHT_MEMORY_EMBEDDER` | `auto`、`stub`、`gemini`；無金鑰的展示可用 `stub`，空字串停用。 |
| `EDUINSIGHT_HOST`、`EDUINSIGHT_PORT` | 設定物件的伺服器值；本 Dockerfile 的啟動命令明確指定 host，port 使用 `PORT`。 |
| `EDUINSIGHT_AUTH_MODE` | `jwt`（獨立）、`lti`（Moodle）或 `both`。 |
| `EDUINSIGHT_FRONTEND_URL` | LTI 登入後的前端重新導向位置；與 CORS 設定分開。 |
| `EDUINSIGHT_MOODLE_URL`、`EDUINSIGHT_MOODLE_TOKEN` | 使用 Moodle Web Services 時設定網址與服務權杖。獨立展示不需要 Moodle。 |

### CORS

確切環境變數是 **`EDUINSIGHT_CORS_ORIGINS`**。`config.py` 以 `EDUINSIGHT_` 前綴載入 `cors_origins`，以逗號切開並去除空白；`app.py` 將 `settings.cors_origin_list` 傳入 `CORSMiddleware.allow_origins`，且啟用 credentials。設定完整 origin（協定、主機及必要的 port），不加路徑或結尾斜線；額外的 Vercel preview 網址須逐一加入。修改後重新啟動後端即可，不需要修改應用程式碼。

### LLM 金鑰

AI 對話可選一組金鑰：`OPENAI_API_KEY`、`GEMINI_API_KEY` 或 `GROQ_API_KEY`，這些名稱沒有 `EDUINSIGHT_` 前綴。若同時提供，對話程式的優先順序是 OpenAI → Gemini → Groq。錄音轉寫優先使用 Groq，其次 OpenAI；Gemini 金鑰不提供目前的 Whisper 轉寫功能。

未提供金鑰時，應用程式會嘗試已安裝的 `claude` CLI；此 Docker 映像未安裝它，因此 `/chat` 只回傳記憶脈絡，不產生 LLM 回答。沒有 Groq／OpenAI 金鑰時轉寫使用 stub。金鑰只放在後端環境變數中。

## Docker 與持久化資料

下列命令供部署時執行，使用主機 8080，避免占用本機 8000：

```sh
docker build -t eduinsight-backend:local .
docker volume create eduinsight-data
docker run -d --name eduinsight-backend --env-file .env.deploy -p 8080:8000 -v eduinsight-data:/data eduinsight-backend:local
curl --fail http://localhost:8080/health
```

將整個 `/data` 掛載至持久化 volume，讓 `EDUINSIGHT_MEMORY_DB_PATH` 與 `EDUINSIGHT_AUTH_DB_PATH` 都指向此目錄；這也保留 SQLite 的 WAL／SHM 檔案。容器的工作目錄就是 `/data`，因此教材原文快取 `_materials_md/` 與作業附件 `uploads/` 也都寫在 volume 內。複製 `.env.example` 後務必覆寫資料庫路徑，否則其相對路徑會寫入容器可丟棄的檔案系統。部署服務若使用 `PORT=8080`，請同步修改容器目標連接埠。

目前部分管理功能（例如講義清單）保存在程序記憶體，掛載 SQLite 不代表所有狀態都會跨重啟保留。**仍須採單一容器與單一 Uvicorn worker**（不要加 `--workers`），避免程序間的記憶體狀態不一致；原因見下一節。

### 多 worker 現況

已改存在共用 SQLite（`EDUINSIGHT_AUTH_DB_PATH` 指向的 auth DB），多個 worker 或重啟後都看到同一份狀態：

- **登入限速**：`login_throttle` 表。username 與 IP 的失敗次數、鎖定到期時間在所有 worker 間共用（在 A 失敗 5 次，B 也回 429）；每次更新是單一 `BEGIN IMMEDIATE` 交易，過期列（30 分鐘）會刪除，總列數上限 10000。時間改用 wall clock，因此主機時鐘大幅回撥會影響鎖定時長。
- **LTI 暫存**：`lti_state` 表，存 OIDC session（含 nonce／state）、launch data 與 60 秒單次 exchange code。code 的取用是原子的，任何 worker 交換過後在其他 worker 也無法重放；TTL 與容量上限與先前相同。

因此登入限速與 LTI **已不是**多 worker 的阻礙，但下列狀態仍在程序內，**多 worker 目前仍不可行**：

- **記憶體內的管理器**：成績中心 `GradeManager` 只在啟動與批改後從 SQLite 同步，其他 worker 看不到別處新增的分類／成績；即時測驗、出席、課堂互動、Office hours 與講義清單（`LectureManager`）完全在記憶體，各 worker 會各有一份、重啟即消失。
- **Lite-Mem 共用連線鎖**（`memory_lock.py`）：`MEMORY_LOCK` 只序列化同一程序內的存取，未驗證多程序同時寫 memory DB 的行為。
- **背景教材索引**：上傳後以 FastAPI background task 在接收請求的 worker 內執行，教材鎖（`_material_lock`）也是程序內的；程序結束時進行中的索引會中斷。
- **`schema_once`**：快取是程序內的，每個 worker 會各自初始化一次；建表與 migration 都是 `IF NOT EXISTS`／交易保護，本身不是阻礙，但列在這裡以免誤以為已共用。

要支援多 worker，需先把上述管理器改為以 SQLite 為準（或改用外部儲存），並處理 Lite-Mem 與背景索引的跨程序協調。

健康檢查為 **`GET /health`**，未登入或非管理員只會得到 `{"status": "ok"}`（不含版本、路徑）；管理員才看得到 LLM、資料庫路徑與記憶統計。Dockerfile 已包含此檢查，也可在部署服務設定 HTTP health check；它不代表外部 LLM 或 Moodle 一定可連線。公開後端應提供 HTTPS。

## 本地部署＋ngrok（目前採用的方式，2026-11-04 決定）

後端與前端都跑在組員的電腦，只透過 ngrok 公開前端；前端以 `/api/backend` 代理到只綁 `127.0.0.1` 的後端。一鍵啟動：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-local-deploy.ps1 -FrontendDir ..\edu-insight-frontend
powershell -ExecutionPolicy Bypass -File scripts\start-local-deploy.ps1 -Stop      # 停止
```

- 以 **production** 模式執行：沒有示範帳號、`/demo/*` 回 404。對公網開放的版本不能用示範資料（見交接規則 2）；報告現場要用示範資料時，改用 `scripts/start-offline-demo.ps1`，不要開 ngrok。
- 設定與資料在 `%USERPROFILE%\.eduinsight\`：`.env.deploy`（第一次執行時產生隨機 JWT 密鑰）、`data\`（SQLite、教材快取、附件）、`admin-credentials.txt`（第一次執行時以隨機密碼建立的管理員 `eduadmin`）。這些都不在 repo 內，不要 commit。
- 後端在主機上執行，而不是 Docker：本機沒有 LLM API 金鑰，要用已登入的 `claude` CLI 產生 AI 回答（`/health` 的管理員檢視會顯示 `llm_provider: ClaudeCLIClient`）。Docker 映像仍可用，只是需要 API 金鑰才有 AI 回答。
- 老師、學生、課程由管理員登入後在「用戶管理」「課程管理」建立（production 預設不開放自助註冊）。
- ngrok 使用帳號設定的固定網域；免費方案的瀏覽器第一次進入會看到 ngrok 的提示頁，按「Visit Site」即可。
- 這台電腦關機或睡眠時服務就會中斷。

實測（2026-11-04）：公開網址 `/login` 200；匿名 `/health` 只回 `{"status":"ok"}`；`admin/admin123` 回 401；`POST /demo/reset` 回 404；透過公開網址呼叫 `/chat` 取得 AI 回答；管理員以瀏覽器從公開網址登入，可進入「網站管理中心」與「用戶管理」，過程沒有錯誤；`-Stop` 後重新啟動，管理員仍可登入（資料保留）。

## Vercel 前端連線

前端 repo 的 `next.config.ts` 已定義 rewrite：

```text
/api/backend/:path* → ${BACKEND_URL}/:path*
```

在 Vercel 前端專案的環境變數中設定 `BACKEND_URL=https://your-backend.example.com`（替換成實際公開後端網址，不加結尾斜線或 `/api/backend`），並對需要的 Production／Preview 環境套用，再重新部署前端使 rewrite 生效。未設定時會落到 `http://127.0.0.1:8000`，在 Vercel 上無法連到你的後端。前端經 `/api/backend` 呼叫；`BACKEND_URL` 是 Next.js 伺服器端設定，不需要 `NEXT_PUBLIC_` 前綴。後端的 CORS 清單仍應包含 `https://edu-insight-two.vercel.app` 與本機 `http://localhost:3000`。

## 展示資料初始化

僅 `EDUINSIGHT_ENV=development` 且未設 `EDUINSIGHT_DEMO_MODE=false` 時會建立 demo 帳號，完整展示資料需以**管理員**身分呼叫 **`POST /demo/reset`**。以下僅供本機開發展示使用：

```powershell
$backend = 'http://localhost:8080'
$login = Invoke-RestMethod -Method Post -Uri "$backend/auth/login" -ContentType 'application/json' -Body '{"username":"admin","password":"admin123"}'
Invoke-RestMethod -Method Post -Uri "$backend/demo/reset" -Headers @{ Authorization = "Bearer $($login.access_token)" }
```

此端點只允許 `admin`（教師呼叫回 403），會重設展示學生的記憶與示範內容；為了不覆蓋真實操作，**已存在的作業提交不會被還原**。要完全回到初始狀態，請用 `scripts/start-offline-demo.ps1`（預設會清空資料後重灌）。只在開發環境要重設展示資料時執行。Production 必須停用所有 demo 入口與 seed。

## Production 安全檢查

- 明確設定 `EDUINSIGHT_ENV=production`；Docker 映像預設為 production，但 `.env.example` 的 development 值會覆寫它。保持 demo/bridge 關閉與 login throttle 開啟。
- JWT secret 必須是至少 32 字元的隨機值；空值、預設值及 placeholder 會在設定載入與 lifespan 驗證時拒絕。僅從部署環境注入 secret，不寫進映像或版本控制。
- 使用全新的持久化 auth DB，不複製含有 `admin/admin123` 等 demo 帳號的開發資料庫。Production 不會自動刪除既有帳號。先備份既有資料庫；migration 保留帳號與密碼，加入 `token_version` 和非 NULL Moodle ID 的 UNIQUE index。若既有 ID 重複，啟動會失敗，須由管理者釐清實際身分，不能直接合併或重編資料鍵。
- 新 production DB 的 `platform_settings.allow_self_register` 預設為 false；既有 DB 保留原設定，升級時檢查 `/admin/settings`。只有管理員可修改。公開註冊只接受 username/password/display_name，永遠建立 student，由伺服器配發 Moodle ID。Teacher/admin 必須透過受信任的管理流程建立。
- 註冊、後端建帳與密碼重設的密碼長度為 8..72 UTF-8 bytes（development 為 4..72）。重設密碼、變更角色與停用帳號會撤銷既有 JWT；重新啟用帳號也不恢復舊 JWT。升級後沒有 `ver` 的舊 token 均需重新登入。
- 保持 `EDUINSIGHT_LOGIN_THROTTLE_ENABLED=true`：username 與來源 IP 各自累計，5 次失敗開始退避，最高 15 分鐘；429 的 `Retry-After` 指示等待時間。Proxy 必須提供正確、受信任的 client IP；不要信任任意使用者的 forwarded headers。
- 使用 HTTPS、精確 CORS origin，以及單一 Uvicorn worker（理由見「多 worker 現況」）。登入限速與 LTI session/launch/code 存在 auth DB，有 TTL 與容量上限，跨 worker 與重啟共用；多副本必須掛載同一個 auth DB 檔案（SQLite 不適合放在網路檔案系統上跨主機共用）。
- `/auth/lti-bridge` 須同時為 development demo 且 `EDUINSIGHT_ENABLE_LTI_BRIDGE=true` 才可用；拒絕 admin 和所有既有帳號。正式 LTI 必須通過平台 launch 驗證。LTI redirect 僅帶 60 秒單次 code，前端以 `POST /lti/exchange` 的 JSON body 交換 JWT，隨即從 history 移除 code。相關回應使用 `Cache-Control: no-store`；目前前端未使用 LTI。

### 建立第一個管理員

在部署環境設定完成後，以相同 auth DB 路徑執行受信任的後端命令。帳密透過終端提示輸入，不使用預設密碼，不放入 shell history：

```sh
uv run --python 3.12 --frozen python -c 'from getpass import getpass; from eduinsight.auth import init_db, create_user, RegisterRequest; init_db(); create_user(RegisterRequest(username=input("Admin username: "), password=getpass("Admin password: "), display_name="Administrator", role="admin"))'
```

在 Docker 容器內則用 `docker exec -it`（同樣以提示輸入帳密）：

```sh
docker exec -it eduinsight-backend python -c 'from getpass import getpass; from eduinsight.auth import init_db, create_user, RegisterRequest; init_db(); create_user(RegisterRequest(username=input("Admin username: "), password=getpass("Admin password: "), display_name="Administrator", role="admin"))'
```

後續 teacher/student 建帳使用需管理員 JWT 的 `POST /admin/users`。禁止透過公開註冊或 development bridge 建立 admin。

### 實測紀錄（2026-11-04，Docker Desktop 29.2）

依本文件從零操作，以下皆實際執行確認：

- `docker build` 成功（約 2 分鐘，需連網下載 Lite-Mem）。
- `EDUINSIGHT_JWT_SECRET` 使用開發預設值時，容器啟動即失敗並顯示「Production requires a random EDUINSIGHT_JWT_SECRET of at least 32 characters」。
- 正確設定後：`/health` 匿名回 `{"status":"ok"}`；容器 healthcheck 為 `healthy`；`admin/admin123` 登入回 401（production 不建立示範帳號）；以管理員呼叫 `POST /demo/reset` 回 **404**。
- 以 `docker exec` 建立管理員、上傳教材後，`docker restart` 與「刪除容器後以同一 volume 重建」兩種情況，帳號、教材索引、教材原文都仍存在。

尚未決定公開主機；報告現場的備援方式見 `scripts/start-offline-demo.ps1`（本機一鍵啟動前後端並灌示範資料）。

### app.py 整合責任

在 lifespan 最前面、任何 DB 或 seed 寫入前呼叫 `validate_production_settings()`（從 `.config` import）。正常 DB 初始化保持啟用；所有展示 seed 與 demo reset/semester 入口須以 `demo_enabled()` 限制。`auth.seed_demo_users()` 本身已有防護。既有 `app.include_router(lti_router)` 會自動提供 `/lti/exchange`，不需另外新增 router。

## Phase 2 hardening configuration

These settings are read from the environment or `.env`. Byte values use binary
MiB, not decimal MB; no proxy limit is required for the server's own enforcement.
Configure reverse-proxy upload limits and temporary-disk capacity consistently
with the application limits and the 64 KiB multipart envelope allowance.

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


The body middleware enforces Content-Length before reading and also counts actual
received bytes, including chunked requests. Upload-route file bytes are counted
before Starlette multipart spooling and copied to disk in bounded chunks. Do not
use streaming multipart Content-Type to exempt another route. Parsing limits
reject unsafe Office ZIPs before library extraction and reject excessive PDF pages
or PPTX slides. DOCX/XLSX are not newly supported upload formats.

Application-owned SQLite connections use WAL and the configured busy timeout.
Lazy schemas/default seeds run once per database identity per process under a
thread lock. They preserve stored settings, authoritative enrollment and existing
rows. Restart after an out-of-band schema change; do not drop live tables. SQLite
WAL/SHM files must share the database's persistent writable directory. The locked
Lite-Mem dependency already configures WAL and a 5-second busy timeout internally;
its source/dependencies are unchanged. SQLite lock failures before a response
starts return 503 (`database_busy`) with `Retry-After: 1`. Background material
jobs have already sent their initial indexing response, so check material status
and logs for job failures rather than expecting a later HTTP status change.

Monitoring can keep using unauthenticated `/health` (only status/version).
Authenticated admin requests retain diagnostic fields. Errors such as
`material_index_failed`, `moodle_unavailable`, `invalid_bundle_json`, and
`internal_server_error` contain no raw exceptions; inspect protected server logs
for full diagnostic details, including pre-existing material errors hidden at read.

For Claude CLI fallback, install a version supporting all flags verified in
**Claude Code 2.1.295**: `--print`, `--model`, `--tools`, `--strict-mcp-config`,
`--mcp-config`, `--no-session-persistence`, `--safe-mode`, `--setting-sources`,
`--disable-slash-commands`, `--system-prompt`, and `--output-format`. The client
passes an empty tool list/MCP config/settings sources, an actual system prompt,
and plain-text input over stdin. Unsupported flags fail the invocation; no unsafe
retry is performed. Do not replace safe mode with `--bare`: this installation's
help explicitly says bare mode stops reading subscription OAuth/keychain auth.
Home/config locations are retained only to keep existing Claude authentication
available; unrelated application/provider secrets are not inherited.

Help output and mocked regression tests verify option availability, command/env,
output bounding, cancellation/timeout kill-and-reap and temporary cleanup. They do
not establish live subscription authentication, model behavior, or independently
prove the CLI's internal no-tools/no-MCP/no-session semantics. Safe mode's help
also says admin-managed policy still applies. Prompt rules are a defense in depth;
the CLI is not an OS-level sandbox. No live LLM request was made for verification.
