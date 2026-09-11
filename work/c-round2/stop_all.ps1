# 停 build + backend
$buildPids = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'build_kb_65_entity' } | Select-Object -ExpandProperty ProcessId
foreach ($p in $buildPids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "stopped build $p"
}

# 停 backend uvicorn（含 workers）
$backendPids = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' } | Select-Object -ExpandProperty ProcessId
foreach ($p in $backendPids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "stopped backend $p"
}

Start-Sleep -Seconds 3
Write-Host 'all stopped'
