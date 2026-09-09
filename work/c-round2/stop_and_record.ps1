# 停 build 进程
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'build_nonrel_async' }
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "stopped $($p.ProcessId)"
}
Write-Host 'build stopped, backend kept running'

# 查 entity 数
$py = 'd:\workspace\rag-for-qw\backend\.venv\Scripts\python.exe'
& $py -c "import psycopg2; conn=psycopg2.connect('host=localhost port=5432 dbname=rag_system user=postgres password=1234'); cur=conn.cursor(); cur.execute('SELECT COUNT(*) FROM entity WHERE kb_id=65'); print('entities:', cur.fetchone()[0]); cur.close(); conn.close()"
