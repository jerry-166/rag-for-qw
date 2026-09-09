"""C 轮2 方案 B：non-rel 700 docs 只做 upload + split + import（embedding only，不做 entity 抽取）
- PUT KB 65 enhancers=[]（临时关闭 entity 抽取）
- 上传 700 non-rel docs（upload + split + generate skip + import embedding only）
- PUT KB 65 enhancers=['entity']（改回，让 src docs 的 graph 模式工作）
- non-rel docs 有 chunk 向量但没 entity → graph 模式不检索 non-rel（设计特性），native 模式检索 non-rel（噪声让 native 非平凡）

输出：work/c-round2/kb_map_crud_nonrel.json（700 non-rel file_id 映射）
"""
import os, sys, json, time, concurrent.futures, threading, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(THIS, 'corpus', 'crud_corpus_1000.json')
OUT_MAP_PATH = os.path.join(THIS, 'kb_map_crud_nonrel.json')

# token 管理
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}
def _login():
    for attempt in range(5):
        try:
            r = requests.post(f'{B}/api/auth/login',
                data={'username': 'loadtester', 'password': 'Loadtest#123'},
                timeout=30)
            r.raise_for_status()
            return r.json()['access_token']
        except Exception as e:
            print(f'[login] attempt {attempt+1} err: {str(e)[:80]}', flush=True)
            time.sleep(5)
    raise RuntimeError('login failed after 5 attempts')

def get_token(force=False):
    with _token_lock:
        now = time.time()
        if force or _token_state['token'] is None or now - _token_state['login_at'] > 50*60:
            _token_state['token'] = _login()
            _token_state['login_at'] = now
        return _token_state['token']

def H():
    return {'Authorization': f'Bearer {get_token()}'}

print(f'login ok, token={get_token()[:20]}...')

# Step 1: PUT KB 65 enhancers=[]（临时关闭 entity 抽取）
print('\n[Step 1] PUT KB 65 enhancers=[]')
r = requests.put(f'{B}/api/knowledge-bases/65',
    json={'enhancers': []}, headers=H(), timeout=15)
print(f'  status={r.status_code} body={r.text[:100]}')

# Step 2: 加载 non-rel docs
with open(CORPUS_PATH, encoding='utf-8') as f:
    corpus = json.load(f)
nonrel_docs = [d for d in corpus if not d.get('metadata', {}).get('is_relevant')]
print(f'\n[Step 2] non-rel docs: {len(nonrel_docs)}')

# Step 3: 上传 + split + generate（skip）+ import（embedding only）
def process_nonrel(doc):
    doc_id = doc['id']
    text = doc.get('text', '')
    title = doc.get('title', '')
    content = f'# {title}\n\n{text}'
    fname = f'{doc_id}.md'
    try:
        files = {'file': (fname, content.encode('utf-8'), 'text/markdown')}
        data = {'kb_id': '65'}
        r = requests.post(f'{B}/api/upload/markdown',
            files=files, data=data, headers=H(), timeout=60)
        if r.status_code == 401:
            get_token(force=True)
            r = requests.post(f'{B}/api/upload/markdown',
                files=files, data=data, headers=H(), timeout=60)
        if r.status_code != 200:
            return (doc_id, None, 'upload_fail', f'{r.status_code} {r.text[:120]}')
        file_id = r.json().get('file_id')
        for step in ('split', 'generate', 'import'):
            rs = requests.post(f'{B}/api/process/{step}/{file_id}',
                headers=H(), timeout=300)
            if rs.status_code == 401:
                get_token(force=True)
                rs = requests.post(f'{B}/api/process/{step}/{file_id}',
                    headers=H(), timeout=300)
            if rs.status_code != 200:
                return (doc_id, file_id, f'{step}_fail', f'{rs.status_code} {rs.text[:200]}')
        return (doc_id, file_id, 'ok', '')
    except Exception as e:
        return (doc_id, None, 'exc', str(e)[:200])

print(f'\n[Step 3] 上传 700 non-rel docs（4 并发，embedding only）')
results = []
t0 = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    futures = {ex.submit(process_nonrel, d): d for d in nonrel_docs}
    for i, fut in enumerate(concurrent.futures.as_completed(futures)):
        r = fut.result()
        results.append(r)
        if (i + 1) % 50 == 0 or i == len(nonrel_docs) - 1:
            ok = sum(1 for x in results if x[2] == 'ok')
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(nonrel_docs) - i - 1) / rate if rate > 0 else 0
            print(f'  [{i+1}/{len(nonrel_docs)}] ok={ok} elapsed={elapsed:.0f}s rate={rate:.2f}/s eta={eta:.0f}s', flush=True)

# Step 4: PUT KB 65 enhancers=['entity']（改回）
print(f'\n[Step 4] PUT KB 65 enhancers=[entity]')
r = requests.put(f'{B}/api/knowledge-bases/65',
    json={'enhancers': ['entity']}, headers=H(), timeout=15)
print(f'  status={r.status_code} body={r.text[:100]}')

# 保存 map
ok = sum(1 for r in results if r[2] == 'ok')
fail = sum(1 for r in results if r[2] != 'ok')
out_map = {
    'kb_id': 65,
    'total': len(nonrel_docs),
    'ok': ok,
    'fail': fail,
    'docs': [{'doc_id': r[0], 'file_id': r[1], 'status': r[2], 'msg': r[3]} for r in results],
}
with open(OUT_MAP_PATH, 'w', encoding='utf-8') as f:
    json.dump(out_map, f, ensure_ascii=False, indent=2)
print(f'\n[done] ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s')
print(f'  map saved: {OUT_MAP_PATH}')
