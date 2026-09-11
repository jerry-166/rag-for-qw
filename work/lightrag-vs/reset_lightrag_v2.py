"""LightRAG 重置 v2（.env 已改好 EMBEDDING_DIM=1024，只做清库+重启+导入+测）"""
import os, sys, time, json, subprocess, requests, psycopg2
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LR_DIR = r'D:\workspace\LightRAG'
LR_URL = 'http://localhost:9621'
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_PATH = os.path.join(THIS_DIR, 'kb17_docs.json')

# 1. 停 LightRAG
print('[1] 停 LightRAG')
try:
    r = requests.get(f'{LR_URL}/health', timeout=3)
    if r.status_code == 200:
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'lightrag_server' } | Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=10)
        pids = [int(p.strip()) for p in result.stdout.strip().split('\n') if p.strip()]
        print(f'  pids: {pids}')
        for pid in pids:
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], timeout=10)
            print(f'  killed {pid}')
        time.sleep(3)
    else:
        print(f'  health status={r.status_code}')
except Exception as e:
    print(f'  已停或 err: {str(e)[:80]}')

# 2. 清 rag 库
print('\n[2] 清 rag 库 LightRAG 表')
PG_DSN = 'host=localhost port=5432 dbname=rag user=postgres password=1234'
try:
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
    tables = [r[0] for r in cur.fetchall()]
    print(f'  tables: {tables}')
    for t in tables:
        cur.execute(f'TRUNCATE TABLE "{t}" CASCADE')
        print(f'  truncated: {t}')
    conn.commit()
    cur.close()
    conn.close()
except Exception as e:
    print(f'  ERR: {e}')

# 3. 重启
print('\n[3] 重启 LightRAG')
bat_path = os.path.join(THIS_DIR, 'start_lightrag.bat')
log_path = os.path.join(THIS_DIR, 'lightrag_restart2.log')
err_path = os.path.join(THIS_DIR, 'lightrag_restart2.err.log')
subprocess.run(
    ['powershell', '-Command',
     f"Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','{bat_path}' -WindowStyle Hidden -RedirectStandardOutput '{log_path}' -RedirectStandardError '{err_path}'"],
    timeout=15)
print('  started')

print('  waiting for /health ...')
ok = False
for i in range(60):
    time.sleep(3)
    try:
        r = requests.get(f'{LR_URL}/health', timeout=5)
        if r.status_code == 200:
            ok = True
            print(f'  health OK after {(i+1)*3}s')
            break
    except Exception:
        pass
    if (i + 1) % 5 == 0:
        print(f'  ... {(i+1)*3}s')
if not ok:
    print('  TIMEOUT')
    if os.path.exists(err_path):
        with open(err_path, encoding='utf-8', errors='replace') as f:
            print(f'  err: {f.read()[:500]}')
    sys.exit(1)

# 4. 导入 KB17
print('\n[4] 导入 KB17 140 docs')
with open(DOCS_PATH, encoding='utf-8') as f:
    docs = json.load(f)
print(f'  docs: {len(docs)}')

BATCH = 5
total_start = time.time()
for i in range(0, len(docs), BATCH):
    batch = docs[i:i + BATCH]
    texts = [d['text'] for d in batch]
    file_sources = [d.get('metadata', {}).get('filename', f'doc_{i+j}') for j, d in enumerate(batch)]
    body = {'texts': texts, 'file_sources': file_sources}
    try:
        r = requests.post(f'{LR_URL}/documents/texts', json=body, timeout=120)
        if r.status_code not in (200, 202):
            print(f'  batch {i//BATCH+1} FAIL: {r.status_code} {r.text[:200]}')
    except Exception as e:
        print(f'  batch {i//BATCH+1} EXC: {e}')
    if (i // BATCH) % 10 == 0:
        print(f'  [{i+1}-{i+len(batch)}/{len(docs)}] sent', flush=True)

print(f'\n  导入请求完成 {time.time()-total_start:.1f}s，等 pipeline 空闲 ...')
for attempt in range(120):
    time.sleep(10)
    try:
        r = requests.get(f'{LR_URL}/health', timeout=10)
        d = r.json()
        busy = d.get('pipeline_busy')
        active = d.get('pipeline_active')
        if busy is False and active is False:
            print(f'  pipeline 空闲 after {(attempt+1)*10}s')
            break
        if (attempt + 1) % 3 == 0:
            print(f'  [{(attempt+1)*10}s] busy={busy} active={active}')
    except Exception as e:
        print(f'  [{(attempt+1)*10}s] health err: {str(e)[:60]}')
else:
    print('  TIMEOUT: pipeline 仍忙')

# 5. 测 query
print('\n[5] 测 /query naive + hybrid')
for q in ['向量数据库的核心原理', 'BM25的打分公式', '重排序的作用']:
    for mode in ['naive', 'hybrid']:
        try:
            r = requests.post(f'{LR_URL}/query',
                json={'query': q, 'mode': mode, 'top_k': 5},
                timeout=60)
            j = r.json()
            ans = j.get('response', '')
            refs = j.get('references', [])
            print(f'  [{q}/{mode}] status={r.status_code} ans_len={len(ans)} refs={len(refs)}')
            if ans and len(ans) > 30:
                print(f'    ans[:80]: {ans[:80]}')
            time.sleep(0.5)
        except Exception as e:
            print(f'  [{q}/{mode}] ERR: {str(e)[:80]}')

print(f'\n[done] {time.time()-total_start:.1f}s')
