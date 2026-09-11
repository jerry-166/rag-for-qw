$pids = @(7164,8424,15504,32788,19668,34456,37844,37944)
foreach ($p in $pids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "killed $p"
}
Start-Sleep -Seconds 3
Write-Host '=== 剩余 python ==='
Get-Process python -ErrorAction SilentlyContinue | Format-Table Id, ProcessName, CPU -AutoSize
