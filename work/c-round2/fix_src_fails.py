"""修复 src docs 的 2 个 fail
- crud_221: file_id=442 存在，重试 generate + import
- crud_274: file_id=None，重新 upload + split + generate + import
"""
import os, sys, json, time, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(THIS, 'corpus', 'crud_corpus_1000.json')

TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=30).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}
print(f'login ok')

with open(CORPUS_PATH, encoding='utf-8') as f:
    corpus = json.load(f)
docs_by_id = {d['id']: d for d in corpus}

# crud_221: 重试 generate + import
print('\n=== crud_221: 重试 generate + import (file_id=442) ===')
file_id = 442
for step in ('generate', 'import'):
    t0 = time.time()
    r = requests.post(f'{B}/api/process/{step}/{file_id}', headers=H, timeout=300)
    print(f'  {step}: {r.status_code} elapsed={time.time()-t0:.1f}s body={r.text[:200]}')
    if r.status_code != 200:
        break

# crud_274: 重新上传 + 全流程
print('\n=== crud_274: 重新 upload + split + generate + import ===')
doc = docs_by_id.get('crud_274')
if doc:
    content = f'# {doc.get("title", "")}\n\n{doc.get("text", "")}'
    fname = 'crud_274.md'
    files = {'file': (fname, content.encode('utf-8'), 'text/markdown')}
    data = {'kb_id': '65'}
    r = requests.post(f'{B}/api/upload/markdown', files=files, data=data, headers=H, timeout=60)
    print(f'  upload: {r.status_code} body={r.text[:200]}')
    if r.status_code == 200:
        file_id = r.json().get('file_id')
        print(f'  file_id={file_id}')
        for step in ('split', 'generate', 'import'):
            t0 = time.time()
            rs = requests.post(f'{B}/api/process/{step}/{file_id}', headers=H, timeout=300)
            print(f'  {step}: {rs.status_code} elapsed={time.time()-t0:.1f}s body={rs.text[:200]}')
            if rs.status_code != 200:
                break
else:
    print('  crud_274 not in corpus')

# 验证
import psycopg2
conn = psycopg2.connect('host=localhost port=5432 dbname=rag_system user=postgres password=1234')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM entity WHERE kb_id=65')
print(f'\nKB 65 entities: {cur.fetchone()[0]}')
cur.close()
conn.close()
