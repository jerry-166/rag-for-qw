"""等两个 import 实例(31964+39768)都结束 + 查 entity + 跑 graph vs LightRAG hybrid 压测 + 存 result_graph.json。"""
import asyncio, json, time, sys, os, subprocess
import aiohttp, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
PIDS = [31964, 39768]

# 1. 等两个 import 都结束
print(f"[wait] 等 import {PIDS} 都结束...", flush=True)
for i in range(720):  # 120min max
    time.sleep(10)
    alive = []
    for pid in PIDS:
        try:
            r = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], capture_output=True, text=True, timeout=5)
            if str(pid) in r.stdout:
                alive.append(pid)
        except Exception:
            pass
    if not alive:
        print(f"[wait] 两个 import 都结束（{i*10}s）", flush=True)
        break
    if i % 6 == 0:
        try:
            with open('backend/logs/app.log', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-2:]
            print(f"[{i*10}s] alive={alive}, app.log: {' | '.join(l.strip()[:80] for l in lines if l.strip())[:150]}", flush=True)
        except Exception:
            pass
else:
    print("[wait] TIMEOUT 120min，强制跑压测", flush=True)

# 2. 查 entity
sys.path.insert(0, os.path.abspath('backend'))
from config import settings
import psycopg2
conn = psycopg2.connect(host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT, user=settings.POSTGRES_USER, password=settings.POSTGRES_PASSWORD, dbname=settings.POSTGRES_DB)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM entity WHERE kb_id = 17")
ent = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM entity_relation WHERE kb_id = 17")
rel = cur.fetchone()[0]
print(f"[entity] KB17 PG entities={ent} entity_relations={rel}", flush=True)
conn.close()

if ent == 0:
    print("[FATAL] KB17 无 entity，graph 降级 native，abort", flush=True)
    sys.exit(1)

# 3. 跑 graph vs LightRAG hybrid（2 组 rerank 关）
B = 'http://localhost:8003'
LR = 'http://localhost:9621'
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
        groups = [
            ('graph_ours',      B + '/api/milvus/query', {'retrieval_mode': 'graph', 'use_rerank': False, 'limit': 10, 'knowledge_base_id': KB}, H),
            ('hybrid_lightrag', LR + '/query',           {'mode': 'hybrid', 'enable_rerank': False, 'top_k': 10}, {}),
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
    json.dump(res, open('work/lightrag-vs/result_graph.json', 'w'), ensure_ascii=False, indent=1)
    print('GRAPH BENCH DONE - result_graph.json saved', flush=True)

asyncio.run(main())
