"""C 轮2 NFCorpus KB 66 异步 build（续跑 3533 docs）
- KB 66 已有 ~100 docs（264 chunks），续跑剩 3533 docs
- asyncio + aiohttp 异步，Semaphore 控制并发
- 跳过已存在的 docs（PG 查 metadata->>'source' 去重）
- token 自动刷新（401 重登）

用法：
  python build_nfcorpus_async.py [并发数]
  默认：并发 5
"""
import os, sys, json, time, asyncio, aiohttp, threading, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(THIS, 'corpus', 'nfcorpus_corpus.json')
OUT_MAP_PATH = os.path.join(THIS, 'kb_map_nfcorpus.json')
KB_ID = 66

CONCURRENCY = int(sys.argv[1]) if len(sys.argv) > 1 else 5

# token 管理
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}

def _do_login_sync():
    r = requests.post(f'{B}/api/auth/login',
        data={'username': 'loadtester', 'password': 'Loadtest#123'},
        timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

def get_token_sync(force=False):
    with _token_lock:
        now = time.time()
        if force or _token_state['token'] is None or now - _token_state['login_at'] > 50*60:
            _token_state['token'] = _do_login_sync()
            _token_state['login_at'] = now
            print(f'[token] refreshed at {time.strftime("%H:%M:%S")}')
        return _token_state['token']

print(f'login ok, token={get_token_sync()[:20]}...')
print(f'concurrency={CONCURRENCY}, kb_id={KB_ID}')

# 加载 corpus
with open(CORPUS_PATH, encoding='utf-8') as f:
    corpus = json.load(f)
print(f'corpus: {len(corpus)} docs')

# 查已存在的 docs（PG 去重）
import psycopg2
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'
existing_filenames = set()
try:
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT metadata->>'source' FROM document_chunk WHERE knowledge_base_id=%s",
        (KB_ID,))
    for r in cur.fetchall():
        if r[0]:
            existing_filenames.add(r[0])
    cur.close()
    conn.close()
    print(f'existing docs in KB{KB_ID}: {len(existing_filenames)}')
except Exception as e:
    print(f'PG err: {e}')

# 过滤出待处理 docs
todo_docs = [d for d in corpus if f"{d['id']}.md" not in existing_filenames]
print(f'todo docs: {len(todo_docs)} (skipped {len(corpus) - len(todo_docs)} existing)')

async def process_doc(session, doc, sem, stats):
    """上传 + split + generate + import 单 doc（异步）"""
    doc_id = doc['id']
    text = doc.get('text', '')
    title = doc.get('title', '')
    content = f'# {title}\n\n{text}'
    fname = f'{doc_id}.md'

    async with sem:
        token = get_token_sync()
        headers = {'Authorization': f'Bearer {token}'}
        file_id = None

        try:
            # 1. upload
            form = aiohttp.FormData()
            form.add_field('file', content.encode('utf-8'),
                filename=fname, content_type='text/markdown')
            form.add_field('kb_id', str(KB_ID))

            async with session.post(f'{B}/api/upload/markdown',
                data=form, headers=headers, timeout=60) as r:
                if r.status == 401:
                    get_token_sync(force=True)
                    headers = {'Authorization': f'Bearer {get_token_sync()}'}
                    async with session.post(f'{B}/api/upload/markdown',
                        data=form, headers=headers, timeout=60) as r2:
                        r = r2
                if r.status != 200:
                    body = await r.text()
                    stats['fail'].append((doc_id, None, 'upload_fail', f'{r.status} {body[:120]}'))
                    return
                j = await r.json()
                file_id = j.get('file_id')

            # 2. split → generate → import
            for step in ('split', 'generate', 'import'):
                async with session.post(f'{B}/api/process/{step}/{file_id}',
                    headers=headers, timeout=300) as r:
                    if r.status == 401:
                        get_token_sync(force=True)
                        headers = {'Authorization': f'Bearer {get_token_sync()}'}
                        async with session.post(f'{B}/api/process/{step}/{file_id}',
                            headers=headers, timeout=300) as r2:
                            r = r2
                    if r.status != 200:
                        body = await r.text()
                        stats['fail'].append((doc_id, file_id, f'{step}_fail', f'{r.status} {body[:200]}'))
                        return

            stats['ok'].append((doc_id, file_id, 'ok', ''))

        except asyncio.TimeoutError:
            stats['fail'].append((doc_id, file_id, 'timeout', f'{step} timeout 300s'))
        except Exception as e:
            stats['fail'].append((doc_id, file_id, 'exc', str(e)[:200]))

async def main():
    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {'ok': [], 'fail': []}

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=300)
    t0 = time.time()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [process_doc(session, d, sem, stats) for d in todo_docs]

        batch_size = 20
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i+batch_size]
            await asyncio.gather(*batch)
            ok = len(stats['ok'])
            fail = len(stats['fail'])
            elapsed = time.time() - t0
            done = ok + fail
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(todo_docs) - done) / rate if rate > 0 else 0
            print(f'  [{done}/{len(todo_docs)}] ok={ok} fail={fail} elapsed={elapsed:.0f}s rate={rate:.2f}/s eta={eta:.0f}s', flush=True)

    elapsed = time.time() - t0
    print(f'\n=== done: ok={len(stats["ok"])} fail={len(stats["fail"])} elapsed={elapsed:.0f}s ===')
    if stats['fail'][:5]:
        print('fail samples:')
        for r in stats['fail'][:5]:
            print(f'  {r}')

    # 保存 map
    all_results = stats['ok'] + stats['fail']
    out_map = {
        'kb_id': KB_ID,
        'total': len(todo_docs),
        'ok': len(stats['ok']),
        'fail': len(stats['fail']),
        'concurrency': CONCURRENCY,
        'elapsed': elapsed,
        'docs': [{'doc_id': r[0], 'file_id': r[1], 'status': r[2], 'msg': r[3]} for r in all_results],
    }
    with open(OUT_MAP_PATH, 'w', encoding='utf-8') as f:
        json.dump(out_map, f, ensure_ascii=False, indent=2)
    print(f'map saved: {OUT_MAP_PATH}')

if __name__ == '__main__':
    asyncio.run(main())
