<#
.SYNOPSIS
  本地部署＋ngrok：以 production 模式在本機啟動後端與前端正式版，並用 ngrok 對外公開。

.DESCRIPTION
  與 start-offline-demo.ps1 不同，這裡是對公網開放的版本，因此：
  - 後端 EDUINSIGHT_ENV=production：沒有示範帳號、/demo/* 回 404、JWT 密鑰須 ≥32 字元。
  - 設定與資料放在 -ConfigDir（預設 %USERPROFILE%\.eduinsight），不在 repo 內。
    第一次執行會產生 .env.deploy（隨機 JWT 密鑰）並以隨機密碼建立管理員，
    帳密寫在 -ConfigDir\admin-credentials.txt（只在本機）。
  - 只公開前端；前端以 /api/backend 代理到只綁 127.0.0.1 的後端。
  - 後端在主機上執行（非 Docker），以便使用已登入的 claude CLI 產生 AI 回答。

  三個程序都以獨立視窗外的背景程序啟動，關閉此視窗不影響；
  要停止請執行：scripts\start-local-deploy.ps1 -Stop

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start-local-deploy.ps1 -FrontendDir ..\edu-insight-frontend
  powershell -ExecutionPolicy Bypass -File scripts\start-local-deploy.ps1 -Stop
#>
param(
    [string]$FrontendDir = (Join-Path $PSScriptRoot "..\..\edu-insight-frontend"),
    [string]$ConfigDir = (Join-Path $env:USERPROFILE ".eduinsight"),
    [int]$BackendPort = 8100,
    [int]$FrontendPort = 3000,
    [switch]$SkipBuild,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$DataDir = Join-Path $ConfigDir "data"
$PidFile = Join-Path $ConfigDir "pids.json"
New-Item -ItemType Directory -Force $DataDir | Out-Null

function Stop-Deploy {
    if (Test-Path $PidFile) {
        foreach ($id in (Get-Content $PidFile | ConvertFrom-Json)) {
            & taskkill /PID $id /T /F 2>$null | Out-Null
        }
        Remove-Item $PidFile
    }
    Write-Host "已停止本地部署（後端、前端、ngrok）。"
}
if ($Stop) { Stop-Deploy; return }
if (Test-Path $PidFile) { Stop-Deploy }

$BackendDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$FrontendDir = Resolve-Path $FrontendDir
foreach ($port in @($BackendPort, $FrontendPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port 已被占用，請先關閉占用的程式。"
    }
}

# --- 設定檔（第一次執行時產生） ------------------------------------------------
$EnvFile = Join-Path $ConfigDir ".env.deploy"
if (-not (Test-Path $EnvFile)) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    @(
        "EDUINSIGHT_ENV=production",
        "EDUINSIGHT_DEMO_MODE=false",
        "EDUINSIGHT_ENABLE_LTI_BRIDGE=false",
        "EDUINSIGHT_LOGIN_THROTTLE_ENABLED=true",
        "EDUINSIGHT_AUTH_MODE=jwt",
        "EDUINSIGHT_JWT_SECRET=$secret",
        "EDUINSIGHT_JWT_EXPIRE_MINUTES=10080",
        "EDUINSIGHT_MEMORY_EMBEDDER=stub"
    ) | Set-Content -Encoding ascii $EnvFile
    Write-Host "已產生 $EnvFile"
}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*([A-Z0-9_]+)=(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2] }
}
$env:EDUINSIGHT_MEMORY_DB_PATH = Join-Path $DataDir "eduinsight.db"
$env:EDUINSIGHT_AUTH_DB_PATH = Join-Path $DataDir "eduinsight_auth.db"
$env:EDUINSIGHT_CORS_ORIGINS = "http://localhost:$FrontendPort"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "be-deploy-venv"
$env:UV_CACHE_DIR = Join-Path $env:TEMP "be-uv-cache"
# 避免後端呼叫的 claude CLI 與 Next.js 把自己當成在 AI agent 內執行。
foreach ($name in @("CLAUDECODE", "AI_AGENT", "CLAUDE_CODE_ENTRYPOINT")) { Remove-Item "env:$name" -ErrorAction SilentlyContinue }

$uvArgs = @("run", "--project", "$BackendDir", "--python", "3.12", "--frozen")

# --- 第一個管理員 ---------------------------------------------------------------
$CredFile = Join-Path $ConfigDir "admin-credentials.txt"
if (-not (Test-Path $CredFile)) {
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789".ToCharArray()
    $bytes = New-Object byte[] 20
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
    $env:EDU_NEW_ADMIN_PASSWORD = $password
    Push-Location $DataDir
    try {
        & uv @uvArgs python -c "import os; from eduinsight.auth import init_db, create_user, RegisterRequest; init_db(); create_user(RegisterRequest(username='eduadmin', password=os.environ['EDU_NEW_ADMIN_PASSWORD'], display_name='平台管理員', role='admin'))"
        if ($LASTEXITCODE -ne 0) { throw "建立管理員失敗" }
    } finally { Pop-Location; Remove-Item env:EDU_NEW_ADMIN_PASSWORD }
    "username=eduadmin`r`npassword=$password" | Set-Content -Encoding ascii $CredFile
    Write-Host "已建立管理員，帳密在 $CredFile"
}

# --- 啟動 -----------------------------------------------------------------------
$pids = @()
$backend = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory $DataDir -FilePath "uv" `
    -ArgumentList ($uvArgs + @("uvicorn", "eduinsight.app:app", "--host", "127.0.0.1", "--port", "$BackendPort")) `
    -RedirectStandardOutput (Join-Path $ConfigDir "backend.log") -RedirectStandardError (Join-Path $ConfigDir "backend.err")
$pids += $backend.Id
$pids | ConvertTo-Json | Set-Content $PidFile
$deadline = (Get-Date).AddMinutes(3)
while ($true) {
    try { Invoke-RestMethod "http://127.0.0.1:$BackendPort/health" -TimeoutSec 3 | Out-Null; break } catch {}
    if ($backend.HasExited) { throw "後端啟動失敗，請看 $(Join-Path $ConfigDir 'backend.err')" }
    if ((Get-Date) -gt $deadline) { throw "後端 3 分鐘內未就緒" }
    Start-Sleep -Seconds 1
}
Write-Host "[1/3] 後端就緒 http://127.0.0.1:$BackendPort（production）"

$env:BACKEND_URL = "http://127.0.0.1:$BackendPort"
Push-Location $FrontendDir
try {
    if (-not $SkipBuild) {
        Write-Host "[2/3] 建置前端（next build --webpack）…"
        & npx next build --webpack | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "前端建置失敗" }
    }
    $frontend = Start-Process -PassThru -WindowStyle Hidden -FilePath "npx.cmd" `
        -ArgumentList @("next", "start", "-p", "$FrontendPort") `
        -RedirectStandardOutput (Join-Path $ConfigDir "frontend.log") -RedirectStandardError (Join-Path $ConfigDir "frontend.err")
} finally { Pop-Location }
$pids += $frontend.Id
$pids | ConvertTo-Json | Set-Content $PidFile
$deadline = (Get-Date).AddMinutes(2)
while ($true) {
    try { Invoke-WebRequest "http://localhost:$FrontendPort/login" -UseBasicParsing -TimeoutSec 5 | Out-Null; break } catch {}
    if ((Get-Date) -gt $deadline) { throw "前端 2 分鐘內未就緒，請看 $(Join-Path $ConfigDir 'frontend.err')" }
    Start-Sleep -Seconds 1
}
Write-Host "[2/3] 前端就緒 http://localhost:$FrontendPort"

$ngrok = Start-Process -PassThru -WindowStyle Hidden -FilePath "ngrok" -ArgumentList @("http", "$FrontendPort", "--log", "stdout") `
    -RedirectStandardOutput (Join-Path $ConfigDir "ngrok.log") -RedirectStandardError (Join-Path $ConfigDir "ngrok.err")
$pids += $ngrok.Id
$pids | ConvertTo-Json | Set-Content $PidFile
$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    try { $url = (Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels").tunnels | Where-Object { $_.config.addr -match "$FrontendPort" } | Select-Object -First 1 -ExpandProperty public_url } catch {}
}
if (-not $url) { throw "ngrok 未取得公開網址，請看 $(Join-Path $ConfigDir 'ngrok.log')" }
Write-Host "[3/3] 公開網址：$url"
Write-Host "管理員帳密：$CredFile；其他老師與學生請登入後在「用戶管理」建立。"
Write-Host "停止：powershell -ExecutionPolicy Bypass -File scripts\start-local-deploy.ps1 -Stop"
