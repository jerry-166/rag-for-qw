# 停 build 进程（保留 backend 运行）
$buildPids = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'build_kb_65_entity' } | Select-Object -ExpandProperty ProcessId
foreach ($p in $buildPids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "stopped build $p"
}
Write-Host 'build stopped, backend kept running'
