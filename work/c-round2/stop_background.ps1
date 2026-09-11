Write-Host '=== 停 LightRAG CRUD reset+import (PID 38096) ==='
Stop-Process -Id 38096 -Force -ErrorAction SilentlyContinue
Write-Host 'done'

Write-Host ''
Write-Host '=== 停后端 KB build (PID 28992) ==='
Stop-Process -Id 28992 -Force -ErrorAction SilentlyContinue
Write-Host 'done'

Write-Host ''
Write-Host '=== 停 LightRAG server 进程 ==='
$pids = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'lightrag_server' } | Select-Object -ExpandProperty ProcessId
Write-Host "lightrag_server pids: $($pids -join ',')"
foreach ($p in $pids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "killed $p"
}

Write-Host ''
Write-Host '=== 验证残留 ==='
Start-Sleep -Seconds 2
$remaining = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'lightrag_server|build_kb_ours|reset_lightrag' } | Select-Object ProcessId, Name, CommandLine
if ($remaining) {
    $remaining | Format-Table -AutoSize
} else {
    Write-Host 'all stopped'
}
