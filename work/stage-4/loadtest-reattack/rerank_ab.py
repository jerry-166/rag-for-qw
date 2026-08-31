"""补充实验：rerank 开/关对照（修复后瓶颈归因）。
native 模式 conc=10 n=40 两组：use_rerank=True vs False——隔离 rerank（CPU 容量）在并发下的贡献。
在主场景2完成后运行。
"""
import asyncio, json, time, threading
import aiohttp, requests

B = 'http://localhost:8003'
KB = 17
TOKEN = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

QUERIES = ["向量数据库的核心原理", "如何优化检索延迟", "文档切片策略对比", "嵌入模型的维度选择", "重排序的作用",
           "多路召回如何融合", "查询改写的常见方法", "评估RAG系统的指标", "倒排索引构建过程", "语义缓存命中率",
           "一致性哈希的应用", "熔断降级的实现", "消息队列的可靠性", "分布式索引的分片", "知识图谱多跳查询",
           "分词算法的对比", "流式计算窗口", "数据脱敏技术", "文本压缩算法", "联邦学习隐私"]

def pctl(xs, p):
    xs = sorted(xs); k = (len(xs) - 1) * p / 100; f = int(k)
    return round(xs[f] if f + 1 >= len(xs) else xs[f] + (xs[f + 1] - xs[f]) * (k - f))

async def worker(session, ep, body, out, sem):
    async with sem:
        t0 = time.perf_counter()
        try:
            async with session.post(B + ep, json={**body, 'query': QUERIES[int(time.time() * 1000) % len(QUERIES)]}, headers=H) as r:
                await r.read(); dt = (time.perf_counter() - t0) * 1000
                out.append({'ok': r.status == 200, 'ms': dt, 'code': r.status})
        except Exception as e:
            out.append({'ok': False, 'ms': (time.perf_counter() - t0) * 1000, 'code': -1, 'err': str(e)[:80]})

async def bench(s, ep, body, n, conc, tag):
    out = []; sem = asyncio.Semaphore(conc)
    t0 = time.perf_counter()
    await asyncio.gather(*[worker(s, ep, body, out, sem) for _ in range(n)])
    wall = time.perf_counter() - t0
    ok = [o['ms'] for o in out if o['ok']]; bad = [o for o in out if not o['ok']]
    summ = {'tag': tag, 'n': n, 'conc': conc, 'wall_s': round(wall, 1), 'qps': round(n / wall, 2),
            'ok': len(ok), 'err': len(bad),
            'p50_ms': pctl(ok, 50), 'p95_ms': pctl(ok, 95), 'max_ms': round(max(ok)) if ok else None}
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    return summ

async def main():
    timeout = aiohttp.ClientTimeout(total=600)
    res = {}
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=40)) as s:
        for tag, rerank in [('native_rerank_on', True), ('native_rerank_off', False)]:
            body = {'use_rerank': rerank, 'knowledge_base_id': KB, 'limit': 10, 'retrieval_mode': 'native'}
            # 预热 2 次
            for i in range(2):
                async with s.post(B + '/api/milvus/query', json={**body, 'query': QUERIES[i]}, headers=H) as r:
                    await r.read()
            res[tag] = await bench(s, '/api/milvus/query', body, 40, 10, tag)
            await asyncio.sleep(3)
    json.dump(res, open('rerank_ab.json', 'w'), ensure_ascii=False, indent=1)
    print('RERANK_AB DONE')

asyncio.run(main())
