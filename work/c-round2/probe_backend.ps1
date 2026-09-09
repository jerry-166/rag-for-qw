Write-Host '=== backend /docs ==='
try {
    $r = Invoke-WebRequest -Uri 'http://localhost:8003/docs' -TimeoutSec 5 -UseBasicParsing
    Write-Host "status=$($r.StatusCode)"
} catch {
    Write-Host "err: $($_.Exception.Message)"
}

Write-Host ''
Write-Host '=== KB 65 doc count ==='
$token = (Invoke-RestMethod -Uri 'http://localhost:8003/api/auth/login' -Method Post -Body @{username='loadtester';password='Loadtest#123'}).access_token
$r2 = Invoke-WebRequest -Uri 'http://localhost:8003/api/documents?kb_id=65&page_size=1' -Headers @{Authorization="Bearer $token"} -UseBasicParsing
Write-Host $r2.Content

Write-Host ''
Write-Host '=== build log size + mtime ==='
$f = Get-Item 'd:\workspace\rag-for-qw\work\c-round2\build_kb_ours.log'
Write-Host "size=$($f.Length) lastWrite=$($f.LastWriteTime) now=$(Get-Date)"
