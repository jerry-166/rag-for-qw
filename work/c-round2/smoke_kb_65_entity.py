"""KB 65 entity 增强构建 smoke test：2 src + 2 non-rel docs"""
import os, sys, json, time, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(THIS, 'corpus', 'crud_corpus_1000.json')
SRC_MAP_PATH = os.path.join(THIS, 'kb_map_crud.json')

TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}
print(f'login ok')

with open(CORPUS_PATH, encoding='utf-8') as f:
    corpus = json.load(f)
with open(SRC_MAP_PATH, encoding='utf-8') as f:
    src_map = {d['doc_id']: d['file_id'] for d in json.load(f).get('docs', [])}

src_docs = [d for d in corpus if d.get('metadata', {}).get('is_relevant')][:2]
nonrel_docs = [d for d in corpus if not d.get('metadata', {}).get('is_relevant')][:2]

print(f'\n=== smoke test: 2 src + 2 non-rel ===')

print('\n--- src docs: generate + import ---')
for d in src_docs:
    doc_id = d['id']
    file_id = src_map.get(doc_id)
    print(f'\n[src] {doc_id} file_id={file_id}')
    # 先查 doc 当前状态
    r0 = requests.get(f'{B}/api/documents?kb_id=65&page_size=200', headers=H, timeout=10)
    cur_doc = None
    for dd in r0.json().get('documents', []):
        if str(dd.get('file_id')) == str(file_id):
            cur_doc = dd
            break
    if cur_doc:
        print(f'  cur status: {cur_doc.get("status")}')
    # generate（entity 抽取）
    t0 = time.time()
    r = requests.post(f'{B}/api/process/generate/{file_id}', headers=H, timeout=300)
    print(f'  generate: {r.status_code} elapsed={time.time()-t0:.1f}s body={r.text[:300]}')
    if r.status_code == 200:
        # import（让 entity vectors 进 Milvus）
        t1 = time.time()
        r2 = requests.post(f'{B}/api/process/import/{file_id}', headers=H, timeout=300)
        print(f'  import: {r2.status_code} elapsed={time.time()-t1:.1f}s body={r2.text[:300]}')

print('\n--- non-rel docs: full pipeline ---')
for d in nonrel_docs:
    doc_id = d['id']
    text = d.get('text', '')
    title = d.get('title', '')
    content = f'# {title}\n\n{text}'
    fname = f'{doc_id}.md'
    print(f'\n[nonrel] {doc_id} ({len(text)}c)')
    files = {'file': (fname, content.encode('utf-8'), 'text/markdown')}
    data = {'kb_id': '65'}
    t0 = time.time()
    r = requests.post(f'{B}/api/upload/markdown', files=files, data=data, headers=H, timeout=60)
    print(f'  upload: {r.status_code} elapsed={time.time()-t0:.1f}s body={r.text[:200]}')
    if r.status_code != 200:
        continue
    file_id = r.json().get('file_id')
    for step in ('split', 'generate', 'import'):
        t1 = time.time()
        rs = requests.post(f'{B}/api/process/{step}/{file_id}', headers=H, timeout=300)
        print(f'  {step}: {rs.status_code} elapsed={time.time()-t1:.1f}s body={rs.text[:300]}')
        if rs.status_code != 200:
            break
