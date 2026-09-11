$f1 = Get-Item 'd:\workspace\rag-for-qw\work\c-round2\build_kb_ours.log'
Write-Host "build log: size=$($f1.Length) lastWrite=$($f1.LastWriteTime)"

$f2 = Get-Item 'd:\workspace\rag-for-qw\work\c-round2\reset_lightrag_crud.log'
Write-Host "lightrag reset log: size=$($f2.Length) lastWrite=$($f2.LastWriteTime)"

Write-Host ''
Write-Host '=== LightRAG server log tail 20 ==='
if (Test-Path 'd:\workspace\rag-for-qw\work\c-round2\lightrag_c2_crud.log') {
    Get-Content 'd:\workspace\rag-for-qw\work\c-round2\lightrag_c2_crud.log' -Tail 20
} else {
    Write-Host 'no lightrag log'
}

Write-Host ''
Write-Host '=== LightRAG server err tail ==='
if (Test-Path 'd:\workspace\rag-for-qw\work\c-round2\lightrag_c2_crud.err.log') {
    Get-Content 'd:\workspace\rag-for-qw\work\c-round2\lightrag_c2_crud.err.log' -Tail 10
}

Write-Host ''
Write-Host '=== backend err log tail ==='
if (Test-Path 'd:\workspace\rag-for-qw\work\c-round2\build_kb_ours.err.log') {
    Get-Content 'd:\workspace\rag-for-qw\work\c-round2\build_kb_ours.err.log' -Tail 10
}
