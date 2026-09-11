"""C 轮2 KB 65 entity 增强构建
- src docs（300，已有 file_id）：直接 generate（entity 抽取）+ import（让 entity vectors 进 Milvus）
- non-rel docs（700，新）：upload + split + generate + import
- 4 并发避免撞 Zhipu 256/window 限流
- 401 自动重新登录

输出：work/c-round2/kb_map_crud_1000.json（含 src + non-rel 的 file_id 映射）
"""
import os, sys, json, time, concurrent.futures, threading, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(THIS, 'corpus', 'crud_corpus_1000.json')
SRC_MAP_PATH = os.path.join(THIS, 'kb_map_crud.json')
OUT_MAP_PATH = os.path.join(THIS, 'kb_map_crud_1000.json')

# token 管理
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}
_TTL = 50 * 60

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
        if force or _token_state['token'] is None or now - _token_state['login_at'] > _TTL:
            _token_state['token'] = _login()
            _token_state['login_at'] = now
        return _token_state['token']

def H():
    return {'Authorization': f'Bearer {get_token()}'}

print(f'login ok, token={get_token()[:20]}...')

# 加载 corpus + src map
with open(CORPUS_PATH, encoding='utf-8') as f:
    corpus = json.load(f)
with open(SRC_MAP_PATH, encoding='utf-8') as f:
    src_map = {d['doc_id']: d['file_id'] for d in json.load(f).get('docs', [])}

src_docs = [d for d in corpus if d.get('metadata', {}).get('is_relevant')]
nonrel_docs = [d for d in corpus if not d.get('metadata', {}).get('is_relevant')]
print(f'corpus: {len(corpus)} (src={len(src_docs)}, nonrel={len(nonrel_docs)})')
print(f'src map: {len(src_map)} file_ids')

# 处理单 doc
def process_src_doc(doc):
    """src doc：已有 file_id，直接 generate + import（让 entity vectors 进 Milvus）"""
    doc_id = doc['id']
    file_id = src_map.get(doc_id)
    if not file_id:
        return (doc_id, None, 'no_file_id', 'src doc not in map')
    try:
        # generate（entity 抽取，LLM 调用）
        r = requests.post(f'{B}/api/process/generate/{file_id}',
            headers=H(), timeout=300)
        if r.status_code == 401:
            get_token(force=True)
            r = requests.post(f'{B}/api/process/generate/{file_id}',
                headers=H(), timeout=300)
        if r.status_code != 200:
            return (doc_id, file_id, 'generate_fail', f'{r.status_code} {r.text[:200]}')
        # 429 处理：智谱限流时 generate 会内部重试，但如果最终还是失败，记录后跳过 import
        gen_status = r.json().get('status', '')
        if gen_status != 'success':
            return (doc_id, file_id, 'gen_status_err', r.text[:200])
        # import（让 entity vectors 进 Milvus entity_vectors 集合）
        r2 = requests.post(f'{B}/api/process/import/{file_id}',
            headers=H(), timeout=300)
        if r2.status_code == 401:
            get_token(force=True)
            r2 = requests.post(f'{B}/api/process/import/{file_id}',
                headers=H(), timeout=300)
        if r2.status_code != 200:
            return (doc_id, file_id, 'import_fail', f'{r2.status_code} {r2.text[:200]}')
        return (doc_id, file_id, 'ok', '')
    except Exception as e:
        return (doc_id, file_id, 'exc', str(e)[:200])

def process_nonrel_doc(doc):
    """non-rel doc：upload + split + generate + import（全流程）"""
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
        # split → generate → import
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

def run_batch(docs, process_fn, label, workers=4):
    """批量处理 + 进度打印"""
    print(f'\n=== {label}: {len(docs)} docs, workers={workers} ===')
    results = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_fn, d): d for d in docs}
        for i, fut in enumerate(concurrent.futures.as_completed(futures)):
            r = fut.result()
            results.append(r)
            if (i + 1) % 20 == 0 or i == len(docs) - 1:
                ok = sum(1 for x in results if x[2] == 'ok')
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (len(docs) - i - 1) / rate if rate > 0 else 0
                print(f'  [{i+1}/{len(docs)}] ok={ok} elapsed={elapsed:.0f}s rate={rate:.2f}/s eta={eta:.0f}s', flush=True)
    ok = [r for r in results if r[2] == 'ok']
    fail = [r for r in results if r[2] != 'ok']
    print(f'  done: ok={len(ok)} fail={len(fail)} elapsed={time.time()-t0:.0f}s')
    if fail[:5]:
        print('  fail samples:')
        for r in fail[:5]:
            print(f'    {r}')
    return results

# 先跑 src docs（300，generate + import，3 并发——180 calls/h < Zhipu 256/window，避免撞 429）
src_results = run_batch(src_docs, process_src_doc, 'src docs (generate+import)', workers=3)

# 再跑 non-rel docs（700，全流程，3 并发）
nonrel_results = run_batch(nonrel_docs, process_nonrel_doc, 'non-rel docs (full pipeline)', workers=3)

# 保存 map
all_results = src_results + nonrel_results
out_map = {
    'kb_id': 65,
    'corpus_size': len(corpus),
    'docs': [{'doc_id': r[0], 'file_id': r[1], 'status': r[2], 'msg': r[3]} for r in all_results],
}
with open(OUT_MAP_PATH, 'w', encoding='utf-8') as f:
    json.dump(out_map, f, ensure_ascii=False, indent=2)
print(f'\n[done] map saved: {OUT_MAP_PATH}')
print(f'  src: {sum(1 for r in src_results if r[2]=="ok")}/{len(src_results)} ok')
print(f'  nonrel: {sum(1 for r in nonrel_results if r[2]=="ok")}/{len(nonrel_results)} ok')
