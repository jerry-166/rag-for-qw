$ProgressPreference = 'SilentlyContinue'
Write-Host '=== 服务状态探测 ==='
$ports = @(8003, 9621, 4000, 5432, 6379)
foreach ($p in $ports) {
    $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $p -WarningAction SilentlyContinue
    Write-Host ("Port {0}: {1}" -f $p, $r.TcpTestSucceeded)
}

Write-Host ''
Write-Host '=== 后端 8003 /docs ==='
try {
    $r = Invoke-WebRequest -Uri 'http://localhost:8003/docs' -TimeoutSec 5 -UseBasicParsing
    Write-Host ("status={0} len={1}" -f $r.StatusCode, $r.RawContentLength)
} catch {
    Write-Host ("backend err: {0}" -f $_.Exception.Message)
}

Write-Host ''
Write-Host '=== LightRAG 9621 /health ==='
try {
    $r = Invoke-WebRequest -Uri 'http://localhost:9621/health' -TimeoutSec 5 -UseBasicParsing
    Write-Host ("status={0} body={1}" -f $r.StatusCode, $r.Content.Substring(0, [Math]::Min(200, $r.Content.Length)))
} catch {
    Write-Host ("lightrag err: {0}" -f $_.Exception.Message)
}

Write-Host ''
Write-Host '=== ZHIPU_API_KEY / DASHSCOPE_API_KEY ==='
$zk = $env:ZHIPU_API_KEY
$dk = $env:DASHSCOPE_API_KEY
Write-Host ("ZHIPU_API_KEY: {0}" -f $(if ($zk) { "$($zk.Substring(0,[Math]::Min(8,$zk.Length)))...len=$($zk.Length)" } else { 'NOT SET' }))
Write-Host ("DASHSCOPE_API_KEY: {0}" -f $(if ($dk) { "$($dk.Substring(0,[Math]::Min(8,$dk.Length)))...len=$($dk.Length)" } else { 'NOT SET' }))
