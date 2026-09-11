"""KB 构建流程 smoke test：上传 2 docs + full_process"""
import os, sys, json, time, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(THIS, 'corpus')

# 登录
TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}
print(f'login ok')

# 创建 KB
r = requests.post(f'{B}/api/knowledge-bases',
    json={'kb_name': 'C2-SmokeTest', 'description': 'smoke test',
          'metadata': {'source': 'c-round2-smoke'},
          'chunk_strategy': 'recursive',
          'enhancers': []},
    headers=H, timeout=15)
print(f'create KB: status={r.status_code} body={r.text[:200]}')
kb_id = r.json().get('kb_id')
print(f'  kb_id={kb_id}')

# 上传 2 docs
with open(os.path.join(CORPUS_DIR, 'crud_corpus_300.json'), encoding='utf-8') as f:
    docs = json.load(f)[:2]

for i, doc in enumerate(docs):
    doc_id = doc['id']
    text = doc.get('text', '')
    title = doc.get('title', '')
    content = f'# {title}\n\n{text}'
    fname = f'{doc_id}.md'
    print(f'\n--- doc {i+1}: {doc_id} ({len(text)}c) ---')
    files = {'file': (fname, content.encode('utf-8'), 'text/markdown')}
    data = {'kb_id': str(kb_id)}
    t0 = time.time()
    r = requests.post(f'{B}/api/upload/markdown',
        files=files, data=data, headers=H, timeout=60)
    print(f'  upload: {r.status_code} elapsed={time.time()-t0:.1f}s body={r.text[:200]}')
    if r.status_code != 200:
        continue
    file_id = r.json().get('file_id')
    print(f'  file_id={file_id}')
    # 三步流水线（绕开 full_process 的 DI bug）
    for step in ('split', 'generate', 'import'):
        t1 = time.time()
        rr = requests.post(f'{B}/api/process/{step}/{file_id}',
            headers=H, timeout=300)
        print(f'  {step}: {rr.status_code} elapsed={time.time()-t1:.1f}s body={rr.text[:200]}')
        if rr.status_code != 200:
            break

# 列 KB 文档
r3 = requests.get(f'{B}/api/documents?kb_id={kb_id}&page_size=20',
    headers=H, timeout=10)
print(f'\nlist docs: {r3.status_code}')
print(r3.text[:600])
