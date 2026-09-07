"""C 轮1 BEIR 检索质量评估
8 对象 × 3 指标（nDCG@10 / Recall@10 / MRR@10）

qrel 构建：用 kb17_supplement 的 native rerank关 contexts 反查 PG chunk_id 作为 relevant set
  （KB17 是同质 docs，同主题 20 份重复内容，native top-10 都是同主题 → 都 relevant）
run 构建：重新调各模式 query 拿 chunk_id ranking

8 对象：
  本项目 5 模式（native rerank关/开、advanced、hybrid_vec、keyword）→ milvus/hybrid/es 端点拿 chunk_id
  LightRAG 2 模式（naive/hybrid）→ /query/data 拿 chunk_id（file_path=doc_N → 反查 PG document_id）
  kb17_supplement 自身（native rerank关 baseline）
"""
import os, sys, json, time, requests, asyncio
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

import psycopg2

B = 'http://localhost:8003'
TESTSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets'))
LR = 'http://localhost:9621'
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'

# 登录
TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

# 加载 supplement 作为 query + qrel 源
src = json.load(open(os.path.join(TESTSET_DIR, 'kb17_supplement.json'), encoding='utf-8'))
src_samples = src.get('samples', [])
print(f"source samples: {len(src_samples)}")

# ── 构建 qrel：用 supplement contexts 文本反查 PG chunk_id ──
print("\n[1] 构建 qrel（supplement contexts 反查 chunk_id）")
conn = psycopg2.connect(PG_DSN)
cur = conn.cursor()

qrel = {}  # {query_idx: {chunk_id_str: 1}}
for i, s in enumerate(src_samples):
    contexts = s.get('contexts', [])
    relevant_ids = set()
    for ctx_text in contexts:
        # 用 content 前 100 字符做 LIKE 查询（KB17 chunks content 重复，取前缀足够定位）
        prefix = ctx_text[:100].replace("'", "''")
        cur.execute(
            "SELECT id FROM document_chunk WHERE knowledge_base_id=17 AND content LIKE %s LIMIT 1",
            (f"{prefix}%",))
        row = cur.fetchone()
        if row:
            relevant_ids.add(str(row[0]))
    qrel[str(i)] = {cid: 1 for cid in relevant_ids}
    if (i + 1) % 10 == 0:
        print(f"  [{i+1}/{len(src_samples)}] qrel relevant={len(relevant_ids)}")

cur.close()
conn.close()
print(f"  qrel built: {len(qrel)} queries")

# ── 构建 run：各模式重新 query 拿 chunk_id ranking ──
def query_ours(query, mode_name, endpoint, extra):
    """本项目检索，返回 chunk_id ranking list（PG document_chunk.id 字符串）"""
    try:
        r = requests.post(f"{B}/api/{endpoint}",
            json={'query': query, 'limit': 10, 'knowledge_base_id': 17, **extra},
            headers=H, timeout=30)
        results = r.json().get('results', [])
        # milvus/query 用 chunk_id，hybrid/search 和 es 用 id（PG document_chunk.id）
        ids = []
        for c in results:
            cid = c.get('chunk_id') or c.get('id')
            if cid is not None:
                ids.append(str(cid))
        return ids
    except Exception as e:
        print(f"    err: {str(e)[:60]}")
        return []

# LightRAG file_path(doc_N) → PG chunk_id 映射缓存
_lr_doc_cache = {}
def _lr_filepath_to_chunk_ids(file_path):
    """file_path=doc_N → N 是 document_id → 查 PG 拿该 doc 的 chunk_id 列表"""
    if file_path in _lr_doc_cache:
        return _lr_doc_cache[file_path]
    # 解析 doc_N → N
    try:
        doc_id = int(file_path.replace('doc_', ''))
    except Exception:
        _lr_doc_cache[file_path] = []
        return []
    try:
        _c = psycopg2.connect(PG_DSN)
        _cur = _c.cursor()
        _cur.execute("SELECT id FROM document_chunk WHERE document_id=%s AND knowledge_base_id=17 ORDER BY chunk_index LIMIT 1", (doc_id,))
        row = _cur.fetchone()
        result = [str(row[0])] if row else []
        _cur.close()
        _c.close()
        _lr_doc_cache[file_path] = result
        return result
    except Exception:
        _lr_doc_cache[file_path] = []
        return []

def query_lightrag(query, mode):
    """LightRAG /query/data 拿 file_path → 反查 PG chunk_id"""
    try:
        r = requests.post(f"{LR}/query/data",
            json={'query': query, 'mode': mode, 'chunk_top_k': 10},
            timeout=60)
        data = r.json().get('data', {})
        chunks = data.get('chunks', [])
        ids = []
        for c in chunks:
            fp = c.get('file_path', '')
            if fp:
                ids.extend(_lr_filepath_to_chunk_ids(fp))
        return ids
    except Exception as e:
        print(f"    lightrag err: {str(e)[:60]}")
        return []

MODES = [
    ('kb17_supplement', 'milvus/query', {'retrieval_mode': 'native', 'use_rerank': False}, None),
    ('kb17_ours_native_rerank_off', 'milvus/query', {'retrieval_mode': 'native', 'use_rerank': False}, None),
    ('kb17_ours_native_rerank_on', 'milvus/query', {'retrieval_mode': 'native', 'use_rerank': True}, None),
    ('kb17_ours_advanced', 'milvus/query', {'retrieval_mode': 'advanced', 'use_rerank': True}, None),
    ('kb17_ours_hybrid_vec', 'hybrid/search', {'retrieval_mode': 'hybrid', 'use_rerank': True}, None),
    ('kb17_ours_keyword', 'elasticsearch/search', {'retrieval_mode': 'native', 'use_rerank': True}, None),
    ('kb17_lightrag_naive', None, None, 'naive'),
    ('kb17_lightrag_hybrid', None, None, 'hybrid'),
]

print("\n[2] 构建 run（各模式 query 拿 chunk_id ranking）")
all_runs = {}  # {mode_name: {query_idx: [doc_id ranking]}}
for mode_name, endpoint, extra, lr_mode in MODES:
    runs = {}
    for i, s in enumerate(src_samples):
        q = s['question']
        if lr_mode:
            ranking = query_lightrag(q, lr_mode)
        else:
            ranking = query_ours(q, mode_name, endpoint, extra)
        runs[str(i)] = ranking  # list of doc_id
        time.sleep(0.2)
    all_runs[mode_name] = runs
    print(f"  [{mode_name}] done, {len(runs)} queries")

# ── 自实现 BEIR 指标（pytrec_eval 装不上，TLS 问题）──
def ndcg_at_k(ranking, qrel, k=10):
    """nDCG@k：归一化折损累计增益
    ranking: list of doc_id（按相关性排序）
    qrel: {doc_id: relevance} 字典
    """
    dcg = 0.0
    for i, doc_id in enumerate(ranking[:k]):
        rel = qrel.get(doc_id, 0)
        if rel > 0:
            dcg += (2 ** rel - 1) / (i + 1)  # 2^rel - 1 折损
    # IDCG：理想排序
    ideal = sorted(qrel.values(), reverse=True)[:k]
    idcg = sum((2 ** r - 1) / (i + 1) for i, r in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0

def recall_at_k(ranking, qrel, k=10):
    """Recall@k：前 k 条命中 relevant 的比例"""
    relevant_set = {d for d, r in qrel.items() if r > 0}
    if not relevant_set:
        return 0.0
    hit = sum(1 for d in ranking[:k] if d in relevant_set)
    return hit / len(relevant_set)

def mrr_at_k(ranking, qrel, k=10):
    """MRR@k：第一个 relevant doc 的倒数排名"""
    relevant_set = {d for d, r in qrel.items() if r > 0}
    for i, doc_id in enumerate(ranking[:k]):
        if doc_id in relevant_set:
            return 1.0 / (i + 1)
    return 0.0

def evaluate_runs(runs, qrel):
    """runs: {qid: [doc_id ranking]}, qrel: {qid: {doc_id: rel}}
    返回 {qid: {ndcg_10, recall_10, mrr_10}}"""
    results = {}
    for qid, ranking in runs.items():
        q = qrel.get(qid, {})
        results[qid] = {
            'ndcg_cut_10': ndcg_at_k(ranking, q, 10),
            'recall_10': recall_at_k(ranking, q, 10),
            'recip_rank': mrr_at_k(ranking, q, 10),
        }
    return results

print(f"\n{'对象':<32} {'nDCG@10':>10} {'Recall@10':>10} {'MRR@10':>10}")
print('-' * 64)

results = []
for mode_name, runs in all_runs.items():
    scores = evaluate_runs(runs, qrel)
    if not scores:
        print(f"{mode_name:<32} {'ERR':>10} {'':>10} {'':>10}")
        results.append({'name': mode_name, 'error': 'no scores'})
        continue
    # 平均
    ndcg = sum(s['ndcg_cut_10'] for s in scores.values()) / len(scores)
    recall = sum(s['recall_10'] for s in scores.values()) / len(scores)
    mrr = sum(s['recip_rank'] for s in scores.values()) / len(scores)
    print(f"{mode_name:<32} {ndcg:>10.3f} {recall:>10.3f} {mrr:>10.3f}")
    results.append({
        'name': mode_name,
        'ndcg_10': round(ndcg, 4),
        'recall_10': round(recall, 4),
        'mrr_10': round(mrr, 4),
    })

# 保存
out_path = os.path.join(os.path.dirname(__file__), 'beir_round1.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({'qrel_count': len(qrel), 'results': results}, f, ensure_ascii=False, indent=2)
print(f"\n汇总已保存: {out_path}")
