# 停旧 backend
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' }
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "stopped backend $($p.ProcessId)"
}
# 停孤儿 workers
$orphans = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'cpython-3.13' -and $_.CommandLine -notmatch 'http.server|server.py|codebuddy' }
foreach ($p in $orphans) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "stopped orphan $($p.ProcessId)"
}
Start-Sleep -Seconds 3
Write-Host 'all stopped'

# 重启 backend with --workers 4
Set-Location d:\workspace\rag-for-qw\backend
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m","uvicorn","app:app","--host","0.0.0.0","--port","8003","--workers","4" -WorkingDirectory $PWD -WindowStyle Hidden -PassThru | Select-Object Id, ProcessName
Write-Host 'backend restarted'
