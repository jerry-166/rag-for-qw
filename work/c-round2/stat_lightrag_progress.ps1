$lines = Get-Content 'd:\workspace\rag-for-qw\work\c-round2\lightrag_c2_crud.err.log' | Select-String 'Completed processing file'
Write-Host "Total 'Completed processing file' lines: $($lines.Count)"
$lines | Select-Object -Last 15 | ForEach-Object { Write-Host $_.Line }

Write-Host ''
Write-Host '=== Extracting stage count ==='
$extract_lines = Get-Content 'd:\workspace\rag-for-qw\work\c-round2\lightrag_c2_crud.err.log' | Select-String 'Extracting stage'
Write-Host "Total 'Extracting stage' lines: $($extract_lines.Count)"
$extract_lines | Select-Object -Last 5 | ForEach-Object { Write-Host $_.Line }

Write-Host ''
Write-Host '=== Merging stage count ==='
$merge_lines = Get-Content 'd:\workspace\rag-for-qw\work\c-round2\lightrag_c2_crud.err.log' | Select-String 'Merging stage'
Write-Host "Total 'Merging stage' lines: $($merge_lines.Count)"
$merge_lines | Select-Object -Last 5 | ForEach-Object { Write-Host $_.Line }
