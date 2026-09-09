# 杀掉所有非 CodeBuddy 的 python 进程（通过命令行判断）
$allPy = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' }
Write-Host "Total python processes: $($allPy.Count)"
foreach ($p in $allPy) {
    $cmd = $p.CommandLine
    # 跳过 CodeBuddy 自己的进程
    if ($cmd -match 'codebuddy|CodeBuddy') {
        Write-Host "  SKIP (CodeBuddy) PID=$($p.ProcessId)"
        continue
    }
    # 杀掉 uvicorn / build_kb_65 / probe 相关
    if ($cmd -match 'uvicorn|build_kb_65|probe_build|lightrag') {
        Write-Host "  KILL PID=$($p.ProcessId) cmd=$($cmd.Substring(0, [Math]::Min(100, $cmd.Length)))"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "  SKIP PID=$($p.ProcessId) cmd=$($cmd.Substring(0, [Math]::Min(80, $cmd.Length)))"
    }
}
Start-Sleep -Seconds 3
Write-Host ''
Write-Host '=== 剩余 python 进程 ==='
Get-Process python -ErrorAction SilentlyContinue | Format-Table Id, ProcessName, CPU -AutoSize
