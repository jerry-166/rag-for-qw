$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'build_kb_65_entity' }
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "stopped $($p.ProcessId)"
}
Write-Host 'build stopped'
