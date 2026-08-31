"""Stage4 复验 场景2 补跑：仅 hybrid_endpoint 组（/api/hybrid/search）。
背景：完整 5 组跑批中，后端在 hybrid_endpoint 组进行 ~80s 时发生 c10.dll(APPCRASH 0xc0000005)
崩溃——本脚本用相同参数重跑该组：(a) 补齐数据 (b) 验证崩溃可复现性。
已修原脚本缺陷：RSS 采样 error 样本导致 KeyError。
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

rss_samples = []
stop_flag = False
def rss_sampler():
    import psutil
    try:
        pid = None
        for c in psutil.net_connections(kind='tcp'):
            if c.laddr and c.laddr.port == 8003 and c.status == 'LISTEN': pid = c.pid; break
        p = psutil.Process(pid)
        while not stop_flag:
            rss_samples.append({'t': time.time(), 'rss_mb': round(p.memory_info().rss / 1048576, 1)})
            time.sleep(2)
    except Exception as e:
        rss_samples.append({'error': str(e)})

async def worker(session, ep, body, out, sem):
    async with sem:
        t0 = time.perf_counter()
        try:
            async with session.post(B + ep, json=body, headers=H) as r:
                await r.read(); dt = (time.perf_counter() - t0) * 1000
                out.append({'ok': r.status == 200, 'ms': dt, 'code': r.status})
        except Exception as e:
            out.append({'ok': False, 'ms': (time.perf_counter() - t0) * 1000, 'code': -1, 'err': str(e)[:80]})

async def bench(s, ep, body, n, conc, tag):
    out = []; sem = asyncio.Semaphore(conc)
    t0 = time.perf_counter()
    await asyncio.gather(*[worker(s, ep, {**body, 'query': QUERIES[i % len(QUERIES)]}, out, sem) for i in range(n)])
    wall = time.perf_counter() - t0
    ok = [o['ms'] for o in out if o['ok']]; bad = [o for o in out if not o['ok']]
    summ = {'tag': tag, 'ep': ep, 'body': body, 'n': n, 'conc': conc, 'wall_s': round(wall, 1),
            'qps': round(n / wall, 2), 'ok': len(ok), 'err': len(bad), 'err_rate': round(len(bad) / n * 100, 2),
            'p50_ms': pctl(ok, 50) if ok else None, 'p95_ms': pctl(ok, 95) if ok else None,
            'p99_ms': pctl(ok, 99) if ok else None, 'max_ms': round(max(ok)) if ok else None,
            'err_codes': {}}
    for b in bad: summ['err_codes'][str(b['code'])] = summ['err_codes'].get(str(b['code']), 0) + 1
    summ['rss_start'] = next((x['rss_mb'] for x in reversed(rss_samples) if 'rss_mb' in x), None)
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    return {'summary': summ, 'detail': out}

async def main():
    global stop_flag
    th = threading.Thread(target=rss_sampler, daemon=True); th.start()
    timeout = aiohttp.ClientTimeout(total=300)
    res = {}
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=40)) as s:
        async with s.post(B + '/api/hybrid/search', json={'query': QUERIES[0], 'use_rerank': True, 'knowledge_base_id': KB, 'limit': 10}, headers=H) as r:
            print('warmup', r.status, flush=True)
        res['hybrid_endpoint'] = await bench(s, '/api/hybrid/search',
                                             {'use_rerank': True, 'knowledge_base_id': KB, 'limit': 10},
                                             200, 20, 'hybrid_endpoint')
    stop_flag = True; time.sleep(0.5)
    json.dump({'summaries': {k: v['summary'] for k, v in res.items()}, 'rss_samples': rss_samples,
               'detail': {k: v['detail'] for k, v in res.items()}},
              open('scenario2_hybrid_ep_result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    r0 = next((x for x in rss_samples if 'rss_mb' in x), {'rss_mb': None})
    r1 = next((x for x in reversed(rss_samples) if 'rss_mb' in x), {'rss_mb': None})
    print(f"RSS: start={r0['rss_mb']}MB end={r1['rss_mb']}MB samples={len(rss_samples)}")
    print('HYBRID_EP DONE')

asyncio.run(main())
