param(
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "start",
    [switch]$StartMilvus,   # 显式开关：拉起本地 milvus 容器（检索默认走 Zilliz，本地容器在 15.6GB 机器上是纯内存负担）
    [switch]$NoRedis        # 显式关闭：不拉 redis 容器（缓存层依赖，默认拉起）
)

<#
  RAGFlow 一键启动/停止/状态脚本
  用法:
    powershell -ExecutionPolicy Bypass -File start_all.ps1                # 启动（默认：不拉 milvus，拉 redis）
    powershell -ExecutionPolicy Bypass -File start_all.ps1 -StartMilvus   # 启动并拉起本地 milvus 容器组
    powershell -ExecutionPolicy Bypass -File start_all.ps1 -NoRedis       # 启动但不拉 redis（缓存降级内存模式）
    powershell -ExecutionPolicy Bypass -File start_all.ps1 stop           # 停止前后端
    powershell -ExecutionPolicy Bypass -File start_all.ps1 status         # 查看状态
  说明:
    - milvus 默认不拉本地容器：检索实际走 Zilliz Cloud（MILVUS_URI），本地 milvus 容器组
      占 4GB+ 内存在 15.6GB RAM 机器上是纯负担（Stage 4 复验实测），需要时加 -StartMilvus
    - redis 只检测本地 6379（用户约定：用本地已有 Redis，不用 docker 启动）；
      未运行时缓存自动降级内存模式，如需 Redis 层请先手动启动本地 Redis
  Git Bash 里直接: bash start_all.sh [start|stop|status] [--milvus] [--no-redis]
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$LogDir = Join-Path $Root "logs"
$BackendPort = 8003
$FrontendPort = 8001
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Get-PortOwner([int]$Port) {
    $lines = netstat -ano -p TCP | Select-String "LISTENING"
    foreach ($line in $lines) {
        $parts = ($line.Line -split "\s+") | Where-Object { $_ }
        if ($parts.Count -ge 5 -and $parts[1] -match ":$Port$") {
            return [int]$parts[-1]
        }
    }
    return $null
}

function Test-Port([int]$Port) {
    return (Get-PortOwner $Port) -ne $null
}

function Wait-Health([string]$Url, [int]$TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Ensure-Postgres {
    $svc = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1
    if (-not $svc) {
        Write-Host "[postgres] 未找到 PostgreSQL 服务，跳过（确认已安装）" -ForegroundColor Yellow
        return
    }
    if ($svc.Status -ne "Running") {
        Write-Host "[postgres] 服务 $($svc.Name) 未运行，尝试启动..." -ForegroundColor Cyan
        try { Start-Service -Name $svc.Name -ErrorAction Stop; Write-Host "[postgres] 已启动" -ForegroundColor Green }
        catch { Write-Host "[postgres] 启动失败（可能需要管理员权限）: $($_.Exception.Message)" -ForegroundColor Red }
    } else {
        Write-Host "[postgres] 服务 $($svc.Name) 运行中" -ForegroundColor Green
    }
}

function Ensure-Milvus {
    Write-Host "[milvus] 检查 Docker 容器..." -ForegroundColor Cyan
    $containers = @("milvus-etcd", "milvus-minio", "milvus-standalone", "milvus-attu")
    try {
        $existing = docker ps -a --filter "name=milvus-" --format "{{.Names}}" 2>$null
        $running = docker ps --filter "name=milvus-" --format "{{.Names}}" 2>$null
        $needStart = @($containers | Where-Object { $existing -contains $_ -and $running -notcontains $_ })
        if ($needStart.Count -gt 0) {
            Write-Host "[milvus] 启动容器: $($needStart -join ', ')" -ForegroundColor Yellow
            docker start $needStart
        } elseif ($running.Count -eq 0) {
            Write-Host "[milvus] 未找到 milvus 容器（请确认 Docker Desktop 已启动且容器已创建）" -ForegroundColor Yellow
        } else {
            Write-Host "[milvus] 容器运行中: $($running -join ', ')" -ForegroundColor Green
        }
    } catch {
        Write-Host "[milvus] Docker 检查失败（确认 Docker Desktop 已启动）: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Ensure-Redis {
    # 用户约定：Redis 用本地已有服务（可能 WSL/独立安装），不用 docker 启动。
    # 此处只做检测提示；未运行时缓存自动降级内存模式（CACHE_BACKEND 容错）。
    Write-Host "[redis] 检查本地 Redis (6379)..." -ForegroundColor Cyan
    if (Test-Port 6379) {
        Write-Host "[redis] 本地 Redis 运行中 (127.0.0.1:6379)" -ForegroundColor Green
    } else {
        Write-Host "[redis] 本地 Redis 未运行（127.0.0.1:6379 无监听）——缓存将降级内存模式" -ForegroundColor Yellow
        Write-Host "       如需启用 Redis 层，请手动启动本地 Redis 后重启后端" -ForegroundColor DarkGray
    }
}

function Start-Backend {
    $owner = Get-PortOwner $BackendPort
    if ($owner) {
        Write-Host "[backend] 端口 $BackendPort 已被 PID $owner 占用，跳过启动" -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path $PythonExe)) {
        Write-Host "[backend] 未找到 $PythonExe，请先创建虚拟环境" -ForegroundColor Red
        return
    }
    Write-Host "[backend] 启动 uvicorn (端口 $BackendPort)..." -ForegroundColor Cyan
    $logOut = Join-Path $LogDir "backend.log"
    $logErr = Join-Path $LogDir "backend.err.log"
    $cmdLine = "$PythonExe -m uvicorn app:app --host 0.0.0.0 --port $BackendPort 1> `"$logOut`" 2> `"$logErr`""
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $cmdLine) -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru
    Write-Host "[backend] 进程 PID $($p.Id)，等待健康检查..." -ForegroundColor Cyan
    if (Wait-Health "http://127.0.0.1:$BackendPort/docs" 60) {
        Write-Host "[backend] 启动成功" -ForegroundColor Green
    } else {
        Write-Host "[backend] 60 秒内未就绪，查看日志: $LogDir\backend.err.log" -ForegroundColor Red
    }
}

function Start-Frontend {
    $owner = Get-PortOwner $FrontendPort
    if ($owner) {
        Write-Host "[frontend] 端口 $FrontendPort 已被 PID $owner 占用，跳过启动" -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path (Join-Path $FrontendDir "design\index.html"))) {
        Write-Host "[frontend] 未找到 frontend\design\index.html（新前端入口）" -ForegroundColor Red
        return
    }
    Write-Host "[frontend] 启动 http.server (端口 $FrontendPort)..." -ForegroundColor Cyan
    $logOut = Join-Path $LogDir "frontend.log"
    $logErr = Join-Path $LogDir "frontend.err.log"
    $cmdLine = "$PythonExe -m http.server $FrontendPort --bind 0.0.0.0 1> `"$logOut`" 2> `"$logErr`""
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $cmdLine) -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru
    Write-Host "[frontend] 进程 PID $($p.Id)，等待健康检查..." -ForegroundColor Cyan
    if (Wait-Health "http://127.0.0.1:$FrontendPort" 15) {
        Write-Host "[frontend] 启动成功" -ForegroundColor Green
    } else {
        Write-Host "[frontend] 15 秒内未就绪，查看日志: $LogDir\frontend.err.log" -ForegroundColor Red
    }
}

function Stop-ServiceByPort([int]$Port, [string]$Name) {
    $owner = Get-PortOwner $Port
    if ($owner) {
        Write-Host "[$Name] 停止端口 $Port 的进程 PID $owner ..." -ForegroundColor Cyan
        Stop-Process -Id $owner -Force
        Write-Host "[$Name] 已停止" -ForegroundColor Green
    } else {
        Write-Host "[$Name] 端口 $Port 无进程在运行" -ForegroundColor Yellow
    }
}

function Show-Status {
    $b = Get-PortOwner $BackendPort
    $f = Get-PortOwner $FrontendPort
    Write-Host "=== RAGFlow 状态 ===" -ForegroundColor Cyan
    if ($b) { Write-Host "[backend] 端口 $BackendPort 运行中 (PID $b)" -ForegroundColor Green }
    else { Write-Host "[backend] 端口 $BackendPort 未运行" -ForegroundColor Red }
    if ($f) { Write-Host "[frontend] 端口 $FrontendPort 运行中 (PID $f)" -ForegroundColor Green }
    else { Write-Host "[frontend] 端口 $FrontendPort 未运行" -ForegroundColor Red }
    $svc = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1
    if ($svc) { Write-Host "[postgres] $($svc.Name): $($svc.Status)" -ForegroundColor Green }
    try {
        $running = docker ps --filter "name=milvus-" --format "{{.Names}}" 2>$null
        if ($running) { Write-Host "[milvus] 运行中: $($running -join ', ')" -ForegroundColor Green }
        else { Write-Host "[milvus] 无容器运行" -ForegroundColor Yellow }
    } catch { Write-Host "[milvus] Docker 不可用" -ForegroundColor Yellow }
    if (Test-Port 6379) { Write-Host "[redis] 本地 Redis 运行中 (127.0.0.1:6379)" -ForegroundColor Green }
    else { Write-Host "[redis] 本地 Redis 未运行（缓存降级内存模式）" -ForegroundColor Yellow }
}
switch ($Action) {
    "start" {
        Write-Host "===== RAGFlow 一键启动 =====" -ForegroundColor Cyan
        Ensure-Postgres
        if ($StartMilvus) { Ensure-Milvus } else { Write-Host "[milvus] 跳过（默认不拉本地容器；需要时加 -StartMilvus）" -ForegroundColor DarkGray }
        if (-not $NoRedis) { Ensure-Redis } else { Write-Host "[redis] 跳过（-NoRedis；缓存将降级内存模式）" -ForegroundColor DarkGray }
        Start-Backend
        Start-Frontend
        Write-Host ""
        Write-Host "访问地址: http://localhost:$FrontendPort/design/index.html（新前端 design）" -ForegroundColor Green
        Write-Host "API 文档: http://localhost:$BackendPort/docs" -ForegroundColor Green
        Write-Host "日志目录: $LogDir" -ForegroundColor Cyan
    }
    "stop" {
        Write-Host "===== RAGFlow 停止前后端 =====" -ForegroundColor Cyan
        Stop-ServiceByPort $FrontendPort "frontend"
        Stop-ServiceByPort $BackendPort "backend"
        Write-Host "提示: PostgreSQL 服务和 Docker 容器（milvus/redis）保持运行，如需停止请手动操作" -ForegroundColor Yellow
    }
    "status" {
        Show-Status
    }
}
