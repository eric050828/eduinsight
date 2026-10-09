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

將整個 `/data` 掛載至持久化 volume，讓 `EDUINSIGHT_MEMORY_DB_PATH` 與 `EDUINSIGHT_AUTH_DB_PATH` 都指向此目錄；這也保留 SQLite 的 WAL／SHM 檔案。複製 `.env.example` 後務必覆寫資料庫路徑，否則其相對路徑會寫入容器可丟棄的檔案系統。部署服務若使用 `PORT=8080`，請同步修改容器目標連接埠。

目前部分管理功能（例如講義清單）保存在程序記憶體，掛載 SQLite 不代表所有狀態都會跨重啟保留。先採單一容器與單一 Uvicorn worker，避免程序間的記憶體狀態不一致。

健康檢查為 **`GET /health`**，正常回應包含 `"status": "ok"`。Dockerfile 已包含此檢查，也可在部署服務設定 HTTP health check；它不代表外部 LLM 或 Moodle 一定可連線。公開後端應提供 HTTPS。

## Vercel 前端連線

前端 repo 的 `next.config.ts` 已定義 rewrite：

```text
/api/backend/:path* → ${BACKEND_URL}/:path*
```

在 Vercel 前端專案的環境變數中設定 `BACKEND_URL=https://your-backend.example.com`（替換成實際公開後端網址，不加結尾斜線或 `/api/backend`），並對需要的 Production／Preview 環境套用，再重新部署前端使 rewrite 生效。未設定時會落到 `http://127.0.0.1:8000`，在 Vercel 上無法連到你的後端。前端經 `/api/backend` 呼叫；`BACKEND_URL` 是 Next.js 伺服器端設定，不需要 `NEXT_PUBLIC_` 前綴。後端的 CORS 清單仍應包含 `https://edu-insight-two.vercel.app` 與本機 `http://localhost:3000`。

## 展示資料初始化

僅 `EDUINSIGHT_ENV=development` 且未設 `EDUINSIGHT_DEMO_MODE=false` 時會建立 demo 帳號，完整展示資料需以教師身分呼叫 **`POST /demo/reset`**。以下僅供本機開發展示使用：

```powershell
$backend = 'http://localhost:8080'
$login = Invoke-RestMethod -Method Post -Uri "$backend/auth/login" -ContentType 'application/json' -Body '{"username":"teacher","password":"teacher123"}'
Invoke-RestMethod -Method Post -Uri "$backend/demo/reset" -Headers @{ Authorization = "Bearer $($login.access_token)" }
```

此端點要求 `teacher` 或 `admin` 角色，會重設展示學生資料並重新植入展示內容；只在開發環境要重設展示資料時執行。Production 必須停用所有 demo 入口與 seed。

## Production 安全檢查

- 明確設定 `EDUINSIGHT_ENV=production`；Docker 映像預設為 production，但 `.env.example` 的 development 值會覆寫它。保持 demo/bridge 關閉與 login throttle 開啟。
- JWT secret 必須是至少 32 字元的隨機值；空值、預設值及 placeholder 會在設定載入與 lifespan 驗證時拒絕。僅從部署環境注入 secret，不寫進映像或版本控制。
- 使用全新的持久化 auth DB，不複製含有 `admin/admin123` 等 demo 帳號的開發資料庫。Production 不會自動刪除既有帳號。先備份既有資料庫；migration 保留帳號與密碼，加入 `token_version` 和非 NULL Moodle ID 的 UNIQUE index。若既有 ID 重複，啟動會失敗，須由管理者釐清實際身分，不能直接合併或重編資料鍵。
- 新 production DB 的 `platform_settings.allow_self_register` 預設為 false；既有 DB 保留原設定，升級時檢查 `/admin/settings`。只有管理員可修改。公開註冊只接受 username/password/display_name，永遠建立 student，由伺服器配發 Moodle ID。Teacher/admin 必須透過受信任的管理流程建立。
- 註冊、後端建帳與密碼重設的密碼長度為 8..72 UTF-8 bytes（development 為 4..72）。重設密碼、變更角色與停用帳號會撤銷既有 JWT；重新啟用帳號也不恢復舊 JWT。升級後沒有 `ver` 的舊 token 均需重新登入。
- 保持 `EDUINSIGHT_LOGIN_THROTTLE_ENABLED=true`：username 與來源 IP 各自累計，5 次失敗開始退避，最高 15 分鐘；429 的 `Retry-After` 指示等待時間。Proxy 必須提供正確、受信任的 client IP；不要信任任意使用者的 forwarded headers。
- 使用 HTTPS、精確 CORS origin，以及單一 Uvicorn worker。登入限速與 LTI session/launch/code 是有 TTL 與容量上限的程序記憶體；多副本需共用限速及 session/code store，重啟會清空記憶體狀態。
- `/auth/lti-bridge` 須同時為 development demo 且 `EDUINSIGHT_ENABLE_LTI_BRIDGE=true` 才可用；拒絕 admin 和所有既有帳號。正式 LTI 必須通過平台 launch 驗證。LTI redirect 僅帶 60 秒單次 code，前端以 `POST /lti/exchange` 的 JSON body 交換 JWT，隨即從 history 移除 code。相關回應使用 `Cache-Control: no-store`；目前前端未使用 LTI。

### 建立第一個管理員

在部署環境設定完成後，以相同 auth DB 路徑執行受信任的後端命令。帳密透過終端提示輸入，不使用預設密碼，不放入 shell history：

```sh
uv run --python 3.12 --frozen python -c 'from getpass import getpass; from eduinsight.auth import init_db, create_user, RegisterRequest; init_db(); create_user(RegisterRequest(username=input("Admin username: "), password=getpass("Admin password: "), display_name="Administrator", role="admin"))'
```

後續 teacher/student 建帳使用需管理員 JWT 的 `POST /admin/users`。禁止透過公開註冊或 development bridge 建立 admin。

### app.py 整合責任

在 lifespan 最前面、任何 DB 或 seed 寫入前呼叫 `validate_production_settings()`（從 `.config` import）。正常 DB 初始化保持啟用；所有展示 seed 與 demo reset/semester 入口須以 `demo_enabled()` 限制。`auth.seed_demo_users()` 本身已有防護。既有 `app.include_router(lti_router)` 會自動提供 `/lti/exchange`，不需另外新增 router。
