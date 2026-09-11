"""B 轮1 压测：本项目 vs LightRAG 延迟对比（KB17 140 docs）。6 组 × 40@10 并发。
复用 rerank_ab.py 的 QUERIES/pctl/worker/bench 结构，改 endpoint + body 字段映射。
公平：同 embedding 模型 + 同 LLM(gpt-4o via litellm) + 同硬件 + 同并发 + 同 top_k=10。"""
import asyncio, json, time, sys
import aiohttp, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'   # 本项目
LR = 'http://localhost:9621'  # LightRAG
KB = 17
TOKEN = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

QUERIES = ["向量数据库的核心原理", "如何优化检索延迟", "文档切片策略对比", "嵌入模型的维度选择", "重排序的作用",
           "多路召回如何融合", "查询改写的常见方法", "评估RAG系统的指标", "倒排索引构建过程", "语义缓存命中率",
           "一致性哈希的应用", "熔断降级的实现", "消息队列的可靠性", "分布式索引的分片", "知识图谱多跳查询",
           "分词算法的对比", "流式计算窗口", "数据脱敏技术", "文本压缩算法", "联邦学习隐私"]

def pctl(xs, p):
    xs = sorted(xs); k = (len(xs) - 1) * p / 100; f = int(k)
    return round(xs[f] if f + 1 >= len(xs) else xs[f] + (xs[f + 1] - xs[f]) * (k - f))

async def worker(session, url, body, headers, out, sem):
    async with sem:
        t0 = time.perf_counter()
        try:
            async with session.post(url, json={**body, 'query': QUERIES[int(time.time() * 1000) % len(QUERIES)]}, headers=headers) as r:
                await r.read(); dt = (time.perf_counter() - t0) * 1000
                out.append({'ok': r.status == 200, 'ms': dt, 'code': r.status})
        except Exception as e:
            out.append({'ok': False, 'ms': (time.perf_counter() - t0) * 1000, 'code': -1, 'err': str(e)[:80]})

async def bench(s, url, body, headers, n, conc, tag):
    out = []; sem = asyncio.Semaphore(conc)
    t0 = time.perf_counter()
    await asyncio.gather(*[worker(s, url, body, headers, out, sem) for _ in range(n)])
    wall = time.perf_counter() - t0
    ok = [o['ms'] for o in out if o['ok']]; bad = [o for o in out if not o['ok']]
    summ = {'tag': tag, 'n': n, 'conc': conc, 'wall_s': round(wall, 1), 'qps': round(n / wall, 2),
            'ok': len(ok), 'err': len(bad),
            'p50_ms': pctl(ok, 50), 'p95_ms': pctl(ok, 95), 'p99_ms': pctl(ok, 99), 'max_ms': round(max(ok)) if ok else None}
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    return summ

async def main():
    timeout = aiohttp.ClientTimeout(total=600)
    res = {}
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=40)) as s:
        # 6 组：3 对比维度 × 2 系统
        # 本项目：POST /api/milvus/query body{retrieval_mode, use_rerank, limit, knowledge_base_id, query} + Auth
        # LightRAG：POST /query body{mode, enable_rerank, top_k, query}（auth_mode=disabled 无需 header）
        groups = [
            ('native_rerank_off',      B + '/api/milvus/query', {'retrieval_mode': 'native',    'use_rerank': False, 'limit': 10, 'knowledge_base_id': KB}, H),
            ('lightrag_naive_rerank_off', LR + '/query',       {'mode': 'naive',  'enable_rerank': False, 'top_k': 10}, {}),
            ('native_rerank_on',       B + '/api/milvus/query', {'retrieval_mode': 'native',    'use_rerank': True,  'limit': 10, 'knowledge_base_id': KB}, H),
            ('lightrag_naive_rerank_on',  LR + '/query',       {'mode': 'naive',  'enable_rerank': True,  'top_k': 10}, {}),
            ('hybrid_vec',             B + '/api/milvus/query', {'retrieval_mode': 'hybrid_vec','use_rerank': False, 'limit': 10, 'knowledge_base_id': KB}, H),
            ('lightrag_hybrid',        LR + '/query',           {'mode': 'hybrid', 'enable_rerank': False, 'top_k': 10}, {}),
        ]
        for tag, url, body, headers in groups:
            print(f"[warmup] {tag}...", flush=True)
            for i in range(2):
                try:
                    async with s.post(url, json={**body, 'query': QUERIES[i]}, headers=headers) as r:
                        await r.read()
                except Exception as e:
                    print(f"  warmup err: {e}", flush=True)
            res[tag] = await bench(s, url, body, headers, 40, 10, tag)
            await asyncio.sleep(3)
    json.dump(res, open('work/lightrag-vs/result_round1.json', 'w'), ensure_ascii=False, indent=1)
    print('BENCH DONE - result_round1.json saved')

asyncio.run(main())
