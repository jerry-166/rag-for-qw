$p = 'C:\Users\ASUS\.android'
if (Test-Path $p) {
    $s = (Get-ChildItem $p -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    Write-Output ('Total: {0:N2} MB' -f ($s/1MB))
    Write-Output ''
    Write-Output '===== contents ====='
    Get-ChildItem $p -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $isDir = $_.PSIsContainer
        if ($isDir) {
            $ds = (Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
            '{0,10:N2} MB  [DIR]  {1}' -f ($ds/1MB), $_.Name
        } else {
            '{0,10:N2} MB  [FILE] {1}  ({2:yyyy-MM-dd HH:mm})' -f ($_.Length/1MB), $_.Name, $_.LastWriteTime
        }
    }
} else {
    Write-Output 'not exists'
}
