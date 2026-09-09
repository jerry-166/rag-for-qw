$lines = (Get-Content 'd:\workspace\rag-for-qw\backend\logs\app.log' | Measure-Object -Line).Lines
Write-Host "total lines: $lines"
Write-Host '=== last 20 lines ==='
Get-Content 'd:\workspace\rag-for-qw\backend\logs\app.log' -Tail 20
