"""C 轮2 KB 构建：本项目后端 KB（CRUD-RAG + NFCorpus）
- 用 loadtester 登录，token 1 小时过期 → 50 分钟主动刷新 + 401 自动重登
- 创建 KB enhancers=[]（控制 LLM 成本，跳过 generate 步骤）
- 并发上传 markdown + 触发 split/generate/import（embedding only）
- 后端按 file_hash 去重，重跑会自动跳过已上传的 doc

用法：
  python build_kb_ours.py crud        # 只跑 CRUD-RAG（KB 65）
  python build_kb_ours.py nfcorpus    # 只跑 NFCorpus（KB 66/67）
  python build_kb_ours.py              # 两个都跑

输出：
  work/c-round2/kb_map_crud.json     — {kb_id, docs:[{doc_id, file_id, status}]}
  work/c-round2/kb_map_nfcorpus.json
"""
import os, sys, json, time, concurrent.futures, threading, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(THIS, 'corpus')

# 带锁的 token 管理器
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}
_TOKEN_TTL = 50 * 60  # 50 分钟主动刷新

def _do_login():
    r = requests.post(f'{B}/api/auth/login',
        data={'username': 'loadtester', 'password': 'Loadtest#123'},
        timeout=10)
    r.raise_for_status()
    return r.json()['access_token']

def get_token(force=False):
    with _token_lock:
        now = time.time()
        if force or _token_state['token'] is None or now - _token_state['login_at'] > _TOKEN_TTL:
            _token_state['token'] = _do_login()
            _token_state['login_at'] = now
            print(f'[token] refreshed at {time.strftime("%H:%M:%S")}', flush=True)
        return _token_state['token']

def auth_headers():
    return {'Authorization': f'Bearer {get_token()}'}

print(f'initial login ok, token={get_token()[:20]}...')

def find_kb_by_name(name):
    """查 KB by name，返回 id 或 None"""
    r = requests.get(f'{B}/api/knowledge-bases', headers=auth_headers(), timeout=10)
    if r.status_code != 200:
        return None
    for kb in r.json().get('knowledge_bases', []):
        if kb.get('kb_name') == name:
            return kb['id']
    return None

def create_or_get_kb(name, description):
    """创建 KB enhancers=[]，已存在则复用"""
    existing = find_kb_by_name(name)
    if existing:
        print(f'  reused existing KB: {name} -> id={existing}')
        return existing
    r = requests.post(f'{B}/api/knowledge-bases',
        json={'kb_name': name, 'description': description,
              'metadata': {'source': 'c-round2'},
              'chunk_strategy': 'recursive',
              'enhancers': []},
        headers=auth_headers(), timeout=15)
    if r.status_code == 200:
        kb_id = r.json().get('kb_id')
        print(f'  KB created: {name} -> id={kb_id}')
        return kb_id
    raise RuntimeError(f'cannot create KB {name}: {r.status_code} {r.text[:200]}')

def upload_one(args):
    """上传单 doc + split → generate → import
    args: (doc_dict, kb_id)
    返回: (doc_id, file_id, status, msg)
    """
    doc, kb_id = args
    doc_id = doc['id']
    text = doc.get('text', '')
    title = doc.get('title', '')
    content = f'# {title}\n\n{text}'
    fname = f'{doc_id}.md'
    try:
        files = {'file': (fname, content.encode('utf-8'), 'text/markdown')}
        data = {'kb_id': str(kb_id)}
        r = requests.post(f'{B}/api/upload/markdown',
            files=files, data=data, headers=auth_headers(), timeout=60)
        if r.status_code == 401:
            get_token(force=True)
            r = requests.post(f'{B}/api/upload/markdown',
                files=files, data=data, headers=auth_headers(), timeout=60)
        if r.status_code != 200:
            return (doc_id, None, 'upload_fail', f'{r.status_code} {r.text[:120]}')
        file_id = r.json().get('file_id')
        # 三步流水线
        for step in ('split', 'generate', 'import'):
            rs = requests.post(f'{B}/api/process/{step}/{file_id}',
                headers=auth_headers(), timeout=300)
            if rs.status_code == 401:
                get_token(force=True)
                rs = requests.post(f'{B}/api/process/{step}/{file_id}',
                    headers=auth_headers(), timeout=300)
            if rs.status_code != 200:
                return (doc_id, file_id, f'{step}_fail', f'{rs.status_code} {rs.text[:200]}')
        return (doc_id, file_id, 'ok', '')
    except Exception as e:
        return (doc_id, None, 'exc', str(e)[:120])

def build_kb(name, description, corpus_path, workers=5):
    print(f'\n=== build KB: {name} ===')
    kb_id = create_or_get_kb(name, description)
    print(f'  kb_id={kb_id}', flush=True)
    with open(corpus_path, encoding='utf-8') as f:
        docs = json.load(f)
    print(f'  docs to upload: {len(docs)}', flush=True)
    args = [(d, kb_id) for d in docs]
    results = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(upload_one, a): a for a in args}
        for i, fut in enumerate(concurrent.futures.as_completed(futures)):
            r = fut.result()
            results.append(r)
            if (i + 1) % 50 == 0 or i == len(args) - 1:
                ok = sum(1 for x in results if x[2] == 'ok')
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                print(f'  [{i+1}/{len(args)}] ok={ok} elapsed={elapsed:.0f}s rate={rate:.2f}/s', flush=True)
    ok = [r for r in results if r[2] == 'ok']
    fail = [r for r in results if r[2] != 'ok']
    print(f'  done: ok={len(ok)} fail={len(fail)} elapsed={time.time()-t0:.0f}s')
    if fail[:5]:
        print('  fail samples:')
        for r in fail[:5]:
            print(f'    {r}')
    return kb_id, results

def save_map(name, kb_id, results, path):
    m = {
        'kb_id': kb_id,
        'docs': [{'doc_id': r[0], 'file_id': r[1], 'status': r[2], 'msg': r[3]} for r in results],
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    print(f'  map saved: {path}')

mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

if mode in ('crud', 'all'):
    crud_kb_id, crud_results = build_kb(
        'C2-CRUD-RAG-300',
        'C 轮2 CRUD-RAG 中文 300 docs（questanswer_1doc 子集），enhancers=[]',
        os.path.join(CORPUS_DIR, 'crud_corpus_300.json'),
        workers=8,
    )
    save_map('crud', crud_kb_id, crud_results, os.path.join(THIS, 'kb_map_crud.json'))

if mode in ('nfcorpus', 'all'):
    nf_kb_id, nf_results = build_kb(
        'C2-NFCorpus-3633',
        'C 轮2 NFCorpus 英文 3633 docs（BEIR corpus），enhancers=[]',
        os.path.join(CORPUS_DIR, 'nfcorpus_corpus.json'),
        workers=8,
    )
    save_map('nfcorpus', nf_kb_id, nf_results, os.path.join(THIS, 'kb_map_nfcorpus.json'))

print('\n=== done ===')
