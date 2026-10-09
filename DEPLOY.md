# 後端部署

使用 Python 3.12 與現有 `uv.lock`；目前鎖定的 Pydantic 相依套件不相容 Python 3.14。Dockerfile 使用 `python:3.12-slim`，以 `uv sync --frozen --no-dev --no-editable` 安裝相依套件，並啟動：

```sh
uvicorn eduinsight.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

`PORT` 是容器啟動命令使用的連接埠，預設為 8000；它不會讀取 `EDUINSIGHT_PORT`。建置需要連網下載映像、Python 套件與 lockfile 指定的 Lite-Mem Git 版本。

## 環境變數

以 `.env.example` 為基礎，另存 `.env.deploy`，透過部署服務的環境變數或 Docker `--env-file` 注入。映像不包含 `.env`、API 金鑰或本機資料庫。獨立 JWT 部署至少明確設定下列值：

```dotenv
EDUINSIGHT_AUTH_MODE=jwt
EDUINSIGHT_JWT_SECRET=replace-with-a-random-secret
EDUINSIGHT_JWT_EXPIRE_MINUTES=10080
EDUINSIGHT_MEMORY_DB_PATH=/data/eduinsight.db
EDUINSIGHT_AUTH_DB_PATH=/data/eduinsight_auth.db
EDUINSIGHT_CORS_ORIGINS=https://edu-insight-two.vercel.app,http://localhost:3000,http://127.0.0.1:3000
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

啟動會建立 demo 帳號，但完整展示資料需以教師身分呼叫 **`POST /demo/reset`**。以下為 PowerShell 範例，可將網址改為公開後端：

```powershell
$backend = 'http://localhost:8080'
$login = Invoke-RestMethod -Method Post -Uri "$backend/auth/login" -ContentType 'application/json' -Body '{"username":"teacher","password":"teacher123"}'
Invoke-RestMethod -Method Post -Uri "$backend/demo/reset" -Headers @{ Authorization = "Bearer $($login.access_token)" }
```

此端點要求 `teacher` 或 `admin` 角色，會重設展示學生資料並重新植入展示內容；只在要重設展示資料時執行。預設展示帳密適合受控展示環境，對外部署前應處理預設帳號存取。
