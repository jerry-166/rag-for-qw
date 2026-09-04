"""Cohere 云端 rerank vs 本地 BGE CrossEncoder 对比。

同 raw_results（use_rerank=false 检索），分别用 BGE / Cohere rerank，
测纯 rerank 延迟 + top-5 排序重叠（Jaccard）。

重点回答：云端 API vs 本地模型的延迟/可用性/排序差异。
"""
import asyncio, json, time, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

import httpx, requests
from services.reranker import CrossEncoderReranker, CohereReranker
from config import settings

B = 'http://localhost:8003'
KB = 17
TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

QUERIES = ["向量数据库的核心原理", "如何优化检索延迟", "文档切片策略对比",
           "嵌入模型的维度选择", "重排序的作用", "多路召回如何融合",
           "查询改写的常见方法", "评估RAG系统的指标", "倒排索引构建过程", "语义缓存命中率"]


def pctl(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    f = int(k)
    return round(xs[f] if f + 1 >= len(xs) else xs[f] + (xs[f + 1] - xs[f]) * (k - f))


def _id(r):
    """结果唯一标识（chunk_id 优先，否则 content 前 50 字）。"""
    return r.get('chunk_id') or r.get('id') or r.get('content', '')[:50]


def topk_overlap(a, b, k=5):
    """top-k Jaccard 重叠。"""
    sa = set(_id(r) for r in a[:k])
    sb = set(_id(r) for r in b[:k])
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0


async def get_raw(client, query):
    """调 /api/milvus/query use_rerank=false 拿 raw_results（rerank pool=15）。"""
    resp = await client.post(B + '/api/milvus/query',
        json={'retrieval_mode': 'native', 'use_rerank': False, 'limit': 15,
              'knowledge_base_id': KB, 'query': query},
        headers=H)
    data = resp.json()
    return data.get('results', [])


async def main():
    bge = CrossEncoderReranker(model_name=settings.RERANKER_MODEL)
    cohere = CohereReranker()
    if not cohere.is_available():
        print("[FATAL] COHERE_API_KEY 未配置，退出", flush=True)
        return
    print(f"[init] BGE model={bge._model_name}", flush=True)
    print(f"[init] Cohere model={cohere._model}, key={cohere._api_key[:8]}...", flush=True)

    # BGE 模型预热（首次加载 5-10s，避免污染第一条延迟）
    print("[warmup] BGE 模型加载...", flush=True)
    t0 = time.perf_counter()
    await bge.rerank("预热查询", [{'content': '预热文档内容'}], top_k=1)
    print(f"[warmup] BGE 加载完成 {time.perf_counter()-t0:.1f}s", flush=True)

    # Cohere 预热（首次 httpx client + 鉴权）
    print("[warmup] Cohere 连通性...", flush=True)
    await cohere.rerank("预热", [{'content': 'test'}], top_k=1)

    bge_times, cohere_times, overlaps, detail = [], [], [], []

    async with httpx.AsyncClient(timeout=60) as client:
        for q in QUERIES:
            raw = await get_raw(client, q)
            if not raw:
                print(f"[{q}] raw 为空，跳过", flush=True)
                continue

            import copy
            raw_bge = copy.deepcopy(raw)
            raw_co = copy.deepcopy(raw)

            t0 = time.perf_counter()
            bge_res = await bge.rerank(q, raw_bge, top_k=5)
            bge_dt = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            co_res = await cohere.rerank(q, raw_co, top_k=5)
            co_dt = (time.perf_counter() - t0) * 1000

            ov = topk_overlap(bge_res, co_res, 5)
            bge_times.append(bge_dt)
            cohere_times.append(co_dt)
            overlaps.append(ov)
            detail.append({
                'query': q, 'bge_ms': round(bge_dt), 'cohere_ms': round(co_dt),
                'overlap': round(ov, 2),
                'bge_top1': (bge_res[0].get('content', '')[:60] if bge_res else None),
                'cohere_top1': (co_res[0].get('content', '')[:60] if co_res else None),
                'raw_n': len(raw),
            })
            print(f"[{q}] bge={bge_dt:.0f}ms cohere={co_dt:.0f}ms overlap={ov:.2f}", flush=True)

    if not bge_times:
        print("[FATAL] 无有效数据", flush=True)
        return

    summ = {
        'n': len(bge_times),
        'bge': {
            'p50_ms': pctl(bge_times, 50), 'p95_ms': pctl(bge_times, 95),
            'max_ms': round(max(bge_times)),
            'mean_ms': round(sum(bge_times) / len(bge_times)),
        },
        'cohere': {
            'p50_ms': pctl(cohere_times, 50), 'p95_ms': pctl(cohere_times, 95),
            'max_ms': round(max(cohere_times)),
            'mean_ms': round(sum(cohere_times) / len(cohere_times)),
        },
        'overlap_mean': round(sum(overlaps) / len(overlaps), 2),
        'detail': detail,
    }
    print('\n=== 汇总 ===')
    print(json.dumps(summ, ensure_ascii=False, indent=2))
    _out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result_cohere_vs_bge.json')
    json.dump(summ, open(_out, 'w'), ensure_ascii=False, indent=2)
    print(f'DONE - {_out} saved')


asyncio.run(main())
