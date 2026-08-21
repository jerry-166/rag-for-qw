"""Stage5：reranker 去阻塞修复后的并发检索基准
1. native+rerank 并发8 x 16（对照 Stage4: p50=35.2s, 5/8 ok, 3 timeout）
2. native 无 rerank 并发8 x 16（回归，对照 Stage4: p50=2.97s）
3. 质量比对：同一查询，use_rerank=true 两次结果 + 与 use_rerank=false 的 top 结果对照
KB=17（loadtester）
"""
import asyncio, json, time, statistics
import aiohttp, requests

B = 'http://localhost:8003'
KB = 17
TOKEN = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

QUERIES = ["向量数据库的核心原理", "如何优化检索延迟", "文档切片策略对比", "嵌入模型的维度选择", "重排序的作用",
           "多路召回如何融合", "查询改写的常见方法", "评估RAG系统的指标", "倒排索引构建过程", "语义缓存命中率",
           "一致性哈希的应用", "熔断降级的实现", "消息队列的可靠性", "分布式索引的分片", "知识图谱多跳查询",
           "分词算法的对比"]

def pctl(xs, p):
    xs = sorted(xs); k = (len(xs) - 1) * p / 100; f = int(k)
    return round(xs[f] if f + 1 >= len(xs) else xs[f] + (xs[f + 1] - xs[f]) * (k - f))

async def worker(session, body, out, sem):
    async with sem:
        t0 = time.perf_counter()
        try:
            async with session.post(B + '/api/milvus/query', json=body, headers=H) as r:
                await r.read(); dt = (time.perf_counter() - t0) * 1000
                out.append({'ok': r.status == 200, 'ms': dt, 'code': r.status})
        except Exception as e:
            out.append({'ok': False, 'ms': (time.perf_counter() - t0) * 1000, 'code': -1, 'err': str(e)[:80]})

async def bench(s, use_rerank, n, conc, tag):
    out = []; sem = asyncio.Semaphore(conc)
    body = {'retrieval_mode': 'native', 'use_rerank': use_rerank, 'knowledge_base_id': KB, 'limit': 10}
    t0 = time.perf_counter()
    await asyncio.gather(*[worker(s, {**body, 'query': QUERIES[i % len(QUERIES)]}, out, sem) for i in range(n)])
    wall = time.perf_counter() - t0
    ok = [o['ms'] for o in out if o['ok']]; bad = [o for o in out if not o['ok']]
    summ = {'tag': tag, 'n': n, 'conc': conc, 'wall_s': round(wall, 1), 'qps': round(n / wall, 2),
            'ok': len(ok), 'err': len(bad),
            'p50_ms': pctl(ok, 50) if ok else None, 'p95_ms': pctl(ok, 95) if ok else None,
            'max_ms': round(max(ok)) if ok else None, 'err_codes': {}}
    for b in bad: summ['err_codes'][str(b['code'])] = summ['err_codes'].get(str(b['code']), 0) + 1
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    return summ

async def fetch_top(s, query, use_rerank):
    body = {'query': query, 'retrieval_mode': 'native', 'use_rerank': use_rerank, 'knowledge_base_id': KB, 'limit': 5}
    async with s.post(B + '/api/milvus/query', json=body, headers=H) as r:
        data = await r.json()
    res = data.get('results', [])
    return [x.get('content', x.get('chunk_text', ''))[:80] for x in res]

async def main():
    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=20)) as s:
        # 预热（加载 reranker 模型 + embedding），不计数
        for ur in (True, False):
            t0 = time.perf_counter()
            async with s.post(B + '/api/milvus/query', json={'query': QUERIES[0], 'retrieval_mode': 'native',
                              'use_rerank': ur, 'knowledge_base_id': KB, 'limit': 10}, headers=H) as r:
                print(f'warmup use_rerank={ur} status={r.status} {round(time.perf_counter()-t0,1)}s', flush=True)

        results = []
        results.append(await bench(s, True, 16, 8, 'native+rerank conc8'))
        results.append(await bench(s, False, 16, 8, 'native-no-rerank conc8'))

        # 质量比对：同一查询，rerank 两次稳定性 + rerank vs 无 rerank top 对照
        quality = {}
        for q in QUERIES[:3]:
            rr1 = await fetch_top(s, q, True)
            rr2 = await fetch_top(s, q, True)
            nr = await fetch_top(s, q, False)
            quality[q] = {
                'rerank_run1': rr1, 'rerank_run2': rr2,
                'rerank_stable': rr1 == rr2,
                'no_rerank_top': nr,
                'top1_same': bool(rr1 and nr and rr1[0] == nr[0]),
            }
            print(json.dumps({q: quality[q]}, ensure_ascii=False), flush=True)

        with open('quality.json', 'w', encoding='utf-8') as f:
            json.dump({'bench': results, 'quality': quality}, f, ensure_ascii=False, indent=2)
        print('DONE', flush=True)

asyncio.run(main())
