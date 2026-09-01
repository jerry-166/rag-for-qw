# A/B 验收包装脚本（避开 PowerShell 内联引号转义坑）
$ErrorActionPreference = "Stop"
Set-Location "d:\workspace\rag-for-qw\backend"
& .\.venv\Scripts\python.exe ..\work\stage-cache\verify_task13_ab.py `
    --admin-user admin --admin-pass admin `
    --user loadtester --pass 'Loadtest#123' `
    --kb-id 17 --query 'RAG retrieval augmented generation' --rounds 6
