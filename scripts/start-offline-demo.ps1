<#
.SYNOPSIS
  報告現場備援：在本機啟動後端（development + 示範資料）與前端，不依賴任何雲端部署。

.DESCRIPTION
  1. 以 Python 3.12 啟動後端於 http://127.0.0.1:8000（EDUINSIGHT_ENV=development，資料放在 -DataDir）
     預設先清空 -DataDir 的資料庫與上傳檔，確保每次都是乾淨的示範資料；加 -KeepData 則保留。
  2. 等待 /health，以 admin/admin123 登入並 POST /demo/reset 灌示範資料
  3. 啟動前端於 http://localhost:3000（預設 dev；-Prod 則 next build --webpack 後 next start）
  Ctrl+C 結束時會一併關閉前後端。

  需要網路的部分（現場斷網時無法使用）：AI 助教的 LLM 回答（claude CLI 或 API 金鑰）、
  Python 執行器（Pyodide 由 jsDelivr 載入）、YouTube 教材影片。其餘頁面與資料都在本機。

.EXAMPLE
  pwsh -File scripts/start-offline-demo.ps1 -FrontendDir ..\edu-insight-frontend
  pwsh -File scripts/start-offline-demo.ps1 -FrontendDir ..\edu-insight-frontend -Prod
#>
param(
    [string]$FrontendDir = (Join-Path $PSScriptRoot "..\..\edu-insight-frontend"),
    [string]$DataDir = (Join-Path $env:TEMP "eduinsight-offline-demo"),
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$Prod,
    [switch]$KeepData
)

$ErrorActionPreference = "Stop"
$BackendDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$FrontendDir = Resolve-Path $FrontendDir
New-Item -ItemType Directory -Force $DataDir | Out-Null
$Backend = "http://127.0.0.1:$BackendPort"

function Test-PortFree([int]$Port) {
    -not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}
foreach ($port in @($BackendPort, $FrontendPort)) {
    if (-not (Test-PortFree $port)) { throw "Port $port 已被占用，請先關閉占用的程式。" }
}

if (-not $KeepData) {
    # 只清本腳本產生的資料（資料庫、教材 Markdown 快取、作業上傳檔），不動其他檔案。
    Get-ChildItem $DataDir -Filter "eduinsight*.db*" -ErrorAction SilentlyContinue | Remove-Item -Force
    foreach ($dir in @("_materials_md", "uploads")) {
        $path = Join-Path $DataDir $dir
        if (Test-Path $path) { Remove-Item -Recurse -Force $path }
    }
}

# --- 後端 -------------------------------------------------------------------
$env:EDUINSIGHT_ENV = "development"
$env:EDUINSIGHT_ENABLE_LTI_BRIDGE = "false"
$env:EDUINSIGHT_MEMORY_DB_PATH = Join-Path $DataDir "eduinsight.db"
$env:EDUINSIGHT_AUTH_DB_PATH = Join-Path $DataDir "eduinsight_auth.db"
$env:EDUINSIGHT_CORS_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"
# 獨立 venv：不影響開發用、含測試套件的 be-venv。
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP "be-demo-venv"
$env:UV_CACHE_DIR = Join-Path $env:TEMP "be-uv-cache"

Write-Host "[1/3] 啟動後端 $Backend（資料：$DataDir）"
# 在 DataDir 執行，讓教材 Markdown 快取也寫在同一處。
$backendProc = Start-Process -PassThru -NoNewWindow -WorkingDirectory $DataDir `
    -FilePath "uv" -ArgumentList @(
        "run", "--project", "$BackendDir", "--python", "3.12", "--frozen",
        "uvicorn", "eduinsight.app:app", "--host", "127.0.0.1", "--port", "$BackendPort"
    ) -RedirectStandardOutput (Join-Path $DataDir "backend.log") `
    -RedirectStandardError (Join-Path $DataDir "backend.err")

$frontendProc = $null
try {
    $deadline = (Get-Date).AddMinutes(3)
    while ($true) {
        try { Invoke-RestMethod "$Backend/health" -TimeoutSec 3 | Out-Null; break } catch {}
        if ($backendProc.HasExited) { throw "後端啟動失敗，請看 $(Join-Path $DataDir 'backend.err')" }
        if ((Get-Date) -gt $deadline) { throw "後端 3 分鐘內未就緒" }
        Start-Sleep -Seconds 1
    }

    Write-Host "[2/3] 灌示範資料（POST /demo/reset）"
    $login = Invoke-RestMethod -Method Post -Uri "$Backend/auth/login" -ContentType "application/json" `
        -Body '{"username":"admin","password":"admin123"}'
    $seed = Invoke-RestMethod -Method Post -Uri "$Backend/demo/reset" `
        -Headers @{ Authorization = "Bearer $($login.access_token)" }
    Write-Host "      示範學生 $($seed.students_seeded) 位、記憶 $($seed.total_memories) 筆"

    # --- 前端 ---------------------------------------------------------------
    $env:BACKEND_URL = $Backend
    Push-Location $FrontendDir
    try {
        if ($Prod) {
            Write-Host "[3/3] 建置前端（next build --webpack）…"
            & npx next build --webpack
            if ($LASTEXITCODE -ne 0) { throw "前端建置失敗" }
            $frontArgs = @("next", "start", "-p", "$FrontendPort")
        } else {
            $frontArgs = @("next", "dev", "--webpack", "-p", "$FrontendPort")
        }
        Write-Host "[3/3] 啟動前端 http://localhost:$FrontendPort"
        $frontendProc = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" -ArgumentList $frontArgs
    } finally { Pop-Location }

    Write-Host ""
    Write-Host "就緒：http://localhost:$FrontendPort"
    Write-Host "帳號：admin/admin123、teacher/teacher123、student1001/student123（其餘見交接文件）"
    Write-Host "按 Ctrl+C 結束。"
    Wait-Process -Id $frontendProc.Id
} finally {
    foreach ($proc in @($frontendProc, $backendProc)) {
        if ($proc -and -not $proc.HasExited) {
            # 連同子程序（uvicorn / node）一起結束。
            & taskkill /PID $proc.Id /T /F 2>$null | Out-Null
        }
    }
}
