$paths = @(
    'C:\Program Files\Redis\redis-server.exe',
    'D:\Redis\redis-server.exe',
    'D:\software\redis\redis-server.exe',
    'D:\ASUS\software\redis\redis-server.exe',
    'C:\tools\redis\redis-server.exe',
    'D:\AI-cache\redis\redis-server.exe',
    'C:\redis\redis-server.exe',
    'D:\dev\redis\redis-server.exe'
)
$found = $false
foreach ($p in $paths) {
    if (Test-Path $p) {
        Write-Host "FOUND: $p"
        $found = $true
    }
}
if (-not $found) {
    Write-Host 'No redis-server in common paths'
    # 浅层搜索
    $candidates = @()
    foreach ($root in @('C:\Program Files','C:\Program Files (x86)','C:\tools','D:\','D:\software','D:\AI-cache')) {
        if (Test-Path $root) {
            $c = Get-ChildItem -Path $root -Filter 'redis-server.exe' -Recurse -ErrorAction SilentlyContinue -Depth 3 | Select-Object -First 2
            $candidates += $c
        }
    }
    if ($candidates.Count -gt 0) {
        Write-Host 'Shallow search found:'
        $candidates | ForEach-Object { Write-Host $_.FullName }
    } else {
        Write-Host 'No redis found anywhere'
    }
}
