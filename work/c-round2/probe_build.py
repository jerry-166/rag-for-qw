"""查 build_kb_65_entity 进度 + PG entity 数据 + err log + backend 响应"""
import os, sys, time, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))

# build log
log_path = os.path.join(THIS, 'build_kb_65_entity.log')
if os.path.exists(log_path):
    with open(log_path, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    print(f'=== build log (size={os.path.getsize(log_path)}, last mtime={time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(log_path)))}) ===')
    for line in lines[-10:]:
        print(f'  {line.rstrip()}')

# err log
err_path = os.path.join(THIS, 'build_kb_65_entity.err.log')
if os.path.exists(err_path) and os.path.getsize(err_path) > 0:
    print(f'\n=== build err log (size={os.path.getsize(err_path)}) ===')
    with open(err_path, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    for line in lines[-10:]:
        print(f'  {line.rstrip()}')

# backend /docs
try:
    r = requests.get(f'{B}/docs', timeout=15)
    print(f'\nbackend /docs: {r.status_code}')
except Exception as e:
    print(f'\nbackend /docs err: {e}')

# PG entity count
try:
    import psycopg2
    conn = psycopg2.connect('host=localhost port=5432 dbname=rag_system user=postgres password=1234')
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM entity WHERE kb_id=65')
    print(f'KB 65 entities: {cur.fetchone()[0]}')
    cur.execute('SELECT COUNT(*) FROM entity_relation WHERE kb_id=65')
    print(f'KB 65 relations: {cur.fetchone()[0]}')
    cur.close()
    conn.close()
except Exception as e:
    print(f'PG err: {e}')

# KB 65 doc count
try:
    t = requests.post(f'{B}/api/auth/login',
        data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=15).json()['access_token']
    H = {'Authorization': f'Bearer {t}'}
    r = requests.get(f'{B}/api/documents?kb_id=65&page_size=1', headers=H, timeout=15)
    d = r.json()
    print(f'\nKB 65 total docs: {d.get("total")}')
    if d.get('documents'):
        print(f'  latest: {d["documents"][0]["filename"]} status={d["documents"][0]["status"]}')
except Exception as e:
    print(f'backend docs err: {e}')

# 进程是否存活
import subprocess
r = subprocess.run(['powershell', '-Command',
    "Get-Process python | Where-Object {$_.CPU -gt 0.1} | Select-Object Id, ProcessName, CPU, WorkingSet64 | Format-Table -AutoSize"],
    capture_output=True, text=True, timeout=10)
print(f'\nactive python processes:')
print(r.stdout.strip() if r.stdout.strip() else '  none')
