"""C 轮1 LightRAG 重置一站式脚本：
1. 改 LightRAG .env（LLM 智谱 + embedding DashScope text-embedding-v4 dim 1536）
2. 停 LightRAG 进程
3. 清 rag 库中 LightRAG 表（truncate）
4. 重启 LightRAG
5. 导入 KB17 docs
6. 测 /health + /query naive

执行完再单独跑 fill_from_lightrag。
"""
import os, sys, time, json, subprocess, shutil, signal
import requests
import psycopg2
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LR_DIR = r'D:\workspace\LightRAG'
LR_ENV = os.path.join(LR_DIR, '.env')
LR_URL = 'http://localhost:9621'
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_PATH = os.path.join(THIS_DIR, 'kb17_docs.json')

# === 智谱/DashScope keys 从环境变量读 ===
ZHIPU = os.environ.get('ZHIPU_API_KEY', '')
DASH = os.environ.get('DASHSCOPE_API_KEY', '')
assert ZHIPU and DASH, 'ZHIPU_API_KEY / DASHSCOPE_API_KEY 必须在环境变量中'

# 1. 改 .env
print('=' * 60)
print('[1] 改 LightRAG .env → 智谱 GLM-4-Flash + DashScope text-embedding-v4')
print('=' * 60)

with open(LR_ENV, encoding='utf-8') as f:
    env_text = f.read()

# 精确替换（按行匹配，注释掉旧的、写新的）
replacements = [
    # LLM
    ('LLM_BINDING=openai', 'LLM_BINDING=openai'),
    ('LLM_BINDING_HOST=http://127.0.0.1:4000/v1',
     f'LLM_BINDING_HOST=https://open.bigmodel.cn/api/paas/v4/'),
    ('LLM_BINDING_API_KEY=sk-uMXpyFMXPJB4tsVTRpeQTg',
     f'LLM_BINDING_API_KEY={ZHIPU}'),
    ('LLM_MODEL=gpt-4o', 'LLM_MODEL=glm-4-flash'),
    # embedding
    ('EMBEDDING_BINDING=ollama', 'EMBEDDING_BINDING=openai'),
    ('EMBEDDING_BINDING_HOST=http://localhost:11434',
     'EMBEDDING_BINDING_HOST=https://dashscope.aliyuncs.com/compatible-mode/v1'),
    ('EMBEDDING_BINDING_API_KEY=your_api_key',
     f'EMBEDDING_BINDING_API_KEY={DASH}'),
    ('EMBEDDING_MODEL=nomic-embed-text:v1.5', 'EMBEDDING_MODEL=text-embedding-v4'),
    ('EMBEDDING_DIM=768', 'EMBEDDING_DIM=1536'),
]
for old, new in replacements:
    if old in env_text:
        env_text = env_text.replace(old, new)
        print(f'  replace OK: {old.split("=")[0]}')
    else:
        print(f'  WARN not found: {old}')

with open(LR_ENV, 'w', encoding='utf-8') as f:
    f.write(env_text)
print('  .env written')

# 2. 停 LightRAG
print('\n' + '=' * 60)
print('[2] 停 LightRAG 进程')
print('=' * 60)
try:
    r = requests.get(f'{LR_URL}/health', timeout=3)
    if r.status_code == 200:
        print('  LightRAG 还在跑，发 SIGTERM')
        # 找 LightRAG python 进程
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'lightrag_server' } | Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=10)
        pids = [int(p.strip()) for p in result.stdout.strip().split('\n') if p.strip()]
        print(f'  found pids: {pids}')
        for pid in pids:
            try:
                subprocess.run(['taskkill', '/F', '/PID', str(pid)], timeout=10)
                print(f'  killed {pid}')
            except Exception as e:
                print(f'  kill {pid} err: {e}')
        time.sleep(3)
    else:
        print(f'  health status={r.status_code}')
except Exception as e:
    print(f'  LightRAG 已停或 health err: {str(e)[:80]}')

# 3. 清 rag 库 LightRAG 表
print('\n' + '=' * 60)
print('[3] 清 LightRAG rag 库表')
print('=' * 60)
PG_DSN = 'host=localhost port=5432 dbname=rag user=postgres password=1234'
try:
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    # 查所有表
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
    tables = [r[0] for r in cur.fetchall()]
    print(f'  rag 库表: {tables}')
    # 截断所有表（保留 schema）
    for t in tables:
        cur.execute(f'TRUNCATE TABLE "{t}" CASCADE')
        print(f'  truncated: {t}')
    conn.commit()
    cur.close()
    conn.close()
    print('  done')
except Exception as e:
    print(f'  ERR: {e}')

# 4. 重启 LightRAG
print('\n' + '=' * 60)
print('[4] 重启 LightRAG')
print('=' * 60)
bat_path = os.path.join(THIS_DIR, 'start_lightrag.bat')
# 用 Start-Process 后台起
log_path = os.path.join(THIS_DIR, 'lightrag_restart.log')
err_path = os.path.join(THIS_DIR, 'lightrag_restart.err.log')
subprocess.run(
    ['powershell', '-Command',
     f"Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','{bat_path}' -WindowStyle Hidden -RedirectStandardOutput '{log_path}' -RedirectStandardError '{err_path}'"],
    timeout=15)
print(f'  started (log: {log_path})')

# 等 health
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
        print(f'  ... {(i+1)*3}s elapsed')
if not ok:
    print('  TIMEOUT waiting for LightRAG')
    # 看 err log
    if os.path.exists(err_path):
        with open(err_path, encoding='utf-8', errors='replace') as f:
            print(f'  err log: {f.read()[:500]}')
    sys.exit(1)

# 5. 导入 KB17 docs
print('\n' + '=' * 60)
print('[5] 导入 KB17 140 docs')
print('=' * 60)
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
        if r.status_code in (200, 202):
            pass
        else:
            print(f'  batch {i//BATCH+1} FAIL: {r.status_code} {r.text[:200]}')
    except Exception as e:
        print(f'  batch {i//BATCH+1} EXCEPTION: {e}')
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

# 6. 测 query
print('\n' + '=' * 60)
print('[6] 测 /query naive')
print('=' * 60)
for q in ['向量数据库的核心原理', 'BM25的打分公式', '重排序的作用']:
    try:
        r = requests.post(f'{LR_URL}/query',
            json={'query': q, 'mode': 'naive', 'top_k': 5},
            timeout=60)
        j = r.json()
        ans = j.get('response', '')
        refs = j.get('references', [])
        print(f'  [{q}] status={r.status_code} ans_len={len(ans)} refs={len(refs)}')
        if ans:
            print(f'    ans[:80]: {ans[:80]}')
        time.sleep(1)
    except Exception as e:
        print(f'  [{q}] ERR: {str(e)[:80]}')

print('\n[done] LightRAG 重置+导入+测试完成')
print(f'总耗时 {time.time()-total_start:.1f}s')
