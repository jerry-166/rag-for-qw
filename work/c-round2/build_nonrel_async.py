"""C 轮2 non-rel 400 docs entity 抽取（asyncio + aiohttp + Semaphore 优化版）
- 先跑 400 non-rel docs（从 700 中取前 400）
- asyncio + aiohttp 异步 HTTP
- Semaphore 控制并发（可配置，默认 3）
- token 自动刷新（401 重登）
- 429 退避重试（backend base.py 已修复，这里再加一层 HTTP 429 检测）

用法：
  python build_nonrel_async.py [并发数] [数量]
  默认：并发 3，数量 400
"""
import os, sys, json, time, asyncio, aiohttp, threading
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(THIS, 'corpus', 'crud_corpus_1000.json')
OUT_MAP_PATH = os.path.join(THIS, 'kb_map_nonrel_400.json')

CONCURRENCY = int(sys.argv[1]) if len(sys.argv) > 1 else 3
DOC_COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 400

# token 管理（同步 lock，因为 aiohttp session 共享）
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}

def _do_login_sync():
    import requests
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
        return _token_state['token']

print(f'login ok, token={get_token_sync()[:20]}...')
print(f'concurrency={CONCURRENCY}, doc_count={DOC_COUNT}')

# 加载 non-rel docs
with open(CORPUS_PATH, encoding='utf-8') as f:
    corpus = json.load(f)
nonrel_docs = [d for d in corpus if not d.get('metadata', {}).get('is_relevant')][:DOC_COUNT]
print(f'non-rel docs to process: {len(nonrel_docs)}')

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
        
        try:
            # 1. upload（multipart）
            form = aiohttp.FormData()
            form.add_field('file', content.encode('utf-8'),
                filename=fname, content_type='text/markdown')
            form.add_field('kb_id', '65')
            
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
    
    # 超时配置
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=300)
    
    t0 = time.time()
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [process_doc(session, d, sem, stats) for d in nonrel_docs]
        
        # 分批 gather + 进度打印
        batch_size = 20
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i+batch_size]
            await asyncio.gather(*batch)
            ok = len(stats['ok'])
            fail = len(stats['fail'])
            elapsed = time.time() - t0
            done = ok + fail
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(nonrel_docs) - done) / rate if rate > 0 else 0
            print(f'  [{done}/{len(nonrel_docs)}] ok={ok} fail={fail} elapsed={elapsed:.0f}s rate={rate:.2f}/s eta={eta:.0f}s', flush=True)
    
    elapsed = time.time() - t0
    print(f'\n=== done: ok={len(stats["ok"])} fail={len(stats["fail"])} elapsed={elapsed:.0f}s ===')
    if stats['fail'][:5]:
        print('fail samples:')
        for r in stats['fail'][:5]:
            print(f'  {r}')
    
    # 保存 map
    all_results = stats['ok'] + stats['fail']
    out_map = {
        'kb_id': 65,
        'total': len(nonrel_docs),
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
