"""C 轮2 BEIR 评估（简化版）：native + graph 2 模式 × CRUD-RAG 300 query × 3 指标
- chunk_id 映射：filename `crud_000.md` → PG document_chunk.id（按 metadata->>'source' LIKE）
- graph 模式检索后 chunk_id 跟 native 一样从 results[].chunk_id 取
- 输出 beir_c2_native_graph.json
"""
import os, sys, json, time, requests, psycopg2
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
TESTSET_DIR = os.path.normpath(os.path.join(THIS, '..', '..', 'backend', 'evaluation', 'testsets'))
QRELS_DIR = os.path.join(THIS, 'qrels')
OUT_DIR = THIS
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'

# token 管理
import threading
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}
def get_token(force=False):
    with _token_lock:
        now = time.time()
        if force or _token_state['token'] is None or now - _token_state['login_at'] > 50*60:
            r = requests.post(f'{B}/api/auth/login',
                data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10)
            r.raise_for_status()
            _token_state['token'] = r.json()['access_token']
            _token_state['login_at'] = now
        return _token_state['token']
def H():
    return {'Authorization': f'Bearer {get_token()}'}
print(f'login ok, token={get_token()[:20]}...')

KB_ID = 65  # CRUD-RAG KB
TESTSET_NAME = 'crud_rag_300'
QRELS_NAME = 'crud_qrels'

# ── chunk_id 映射缓存 ──
_filename_chunk_cache = {}
def filename_to_chunk_ids(filename, kb_id):
    key = (filename, kb_id)
    if key in _filename_chunk_cache:
        return _filename_chunk_cache[key]
    try:
        conn = psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM document_chunk WHERE knowledge_base_id=%s AND metadata->>'source'=%s ORDER BY chunk_index",
            (kb_id, filename))
        rows = cur.fetchall()
        result = [str(r[0]) for r in rows]
        cur.close()
        conn.close()
    except Exception as e:
        print(f'  pg err: {e}')
        result = []
    _filename_chunk_cache[key] = result
    return result

def query_ours(query, mode_name, retrieval_mode, use_rerank, kb_id):
    """本项目 milvus/query 检索 → 返回 chunk_id ranking list"""
    try:
        r = requests.post(f"{B}/api/milvus/query",
            json={'query': query, 'limit': 10, 'knowledge_base_id': kb_id,
                  'retrieval_mode': retrieval_mode, 'use_rerank': use_rerank},
            headers=H(), timeout=30)
        if r.status_code == 401:
            get_token(force=True)
            r = requests.post(f"{B}/api/milvus/query",
                json={'query': query, 'limit': 10, 'knowledge_base_id': kb_id,
                      'retrieval_mode': retrieval_mode, 'use_rerank': use_rerank},
                headers=H(), timeout=30)
        results = r.json().get('results', [])
        ids = []
        for c in results:
            # native 模式 chunk_id 在顶层；graph 模式 chunk_id 在 metadata.chunk_id
            cid = c.get('chunk_id') or c.get('id')
            if cid is None:
                # graph 模式：chunk_id 在 metadata 里
                cid = c.get('metadata', {}).get('chunk_id')
            if cid is not None:
                ids.append(str(cid))
        return ids
    except Exception as e:
        print(f'    {mode_name} err: {str(e)[:80]}')
        return []

# ── BEIR 指标 ──
def ndcg_at_k(ranking, qrel, k=10):
    dcg = 0.0
    for i, doc_id in enumerate(ranking[:k]):
        rel = qrel.get(doc_id, 0)
        if rel > 0:
            dcg += (2 ** rel - 1) / (i + 1)
    ideal = sorted(qrel.values(), reverse=True)[:k]
    idcg = sum((2 ** r - 1) / (i + 1) for i, r in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0

def recall_at_k(ranking, qrel, k=10):
    relevant_set = {d for d, r in qrel.items() if r > 0}
    if not relevant_set:
        return 0.0
    hit = sum(1 for d in ranking[:k] if d in relevant_set)
    return hit / len(relevant_set)

def mrr_at_k(ranking, qrel, k=10):
    relevant_set = {d for d, r in qrel.items() if r > 0}
    for i, doc_id in enumerate(ranking[:k]):
        if doc_id in relevant_set:
            return 1.0 / (i + 1)
    return 0.0

# ── 2 模式定义 ──
MODES = [
    ('native_rerank_off', 'native', False),
    ('graph', 'graph', True),
]

# ── 主流程 ──
print(f'\n=== BEIR C2: native + graph × CRUD-RAG 300 ===')
print(f'KB id: {KB_ID}')

# 加载 testset + qrels
with open(os.path.join(TESTSET_DIR, f'{TESTSET_NAME}.json'), encoding='utf-8') as f:
    ts = json.load(f)
samples = ts.get('samples', [])
print(f'samples: {len(samples)}')

with open(os.path.join(QRELS_DIR, f'{QRELS_NAME}.json'), encoding='utf-8') as f:
    qd = json.load(f)
qrels = qd.get('qid_to_doc_id', {})
print(f'qrels: {len(qrels)} queries')

# qrel 的 key 是 qid（如 'crud_q000'），需要把 qid → chunk_ids 映射
# CRUD qrel: qid → {doc_id: 1}（doc_id 是 'crud_000' 等）
# 我们要把 doc_id → chunk_ids（PG document_chunk.id）映射
# 然后 qrel_chunk: qid → {chunk_id: 1}
def build_qrel_chunk_ids(qrels, kb_id):
    """把 doc_id 形式的 qrel 转成 chunk_id 形式"""
    qrel_chunk = {}
    for qid, rels in qrels.items():
        chunk_rels = {}
        for doc_id, score in rels.items():
            # doc_id 是 'crud_000'，对应 filename 'crud_000.md'
            filename = f'{doc_id}.md' if not doc_id.endswith('.md') else doc_id
            chunk_ids = filename_to_chunk_ids(filename, kb_id)
            for cid in chunk_ids:
                chunk_rels[cid] = score
        qrel_chunk[qid] = chunk_rels
    return qrel_chunk

print(f'\n[1] 构建 qrel → chunk_id 映射')
qrel_chunk = build_qrel_chunk_ids(qrels, KB_ID)
total_rel = sum(len(v) for v in qrel_chunk.values())
print(f'  qrel_chunk: {len(qrel_chunk)} queries, total rel chunks: {total_rel}')

# 跑 2 模式
results = []
for mode_name, retrieval_mode, use_rerank in MODES:
    print(f'\n[mode] {mode_name} (retrieval_mode={retrieval_mode}, use_rerank={use_rerank})')
    runs = {}
    for i, s in enumerate(samples):
        q = s['question']
        qid = s.get('metadata', {}).get('qid', str(i))
        ranking = query_ours(q, mode_name, retrieval_mode, use_rerank, KB_ID)
        runs[qid] = ranking
        time.sleep(0.1)
        if (i + 1) % 50 == 0:
            print(f'  [{i+1}/{len(samples)}] done')
    # 评估
    if not runs:
        print(f'  ERR: no runs')
        continue
    n = len(runs)
    ndcgs = sum(ndcg_at_k(runs[qid], qrel_chunk.get(qid, {}), 10) for qid in runs)
    recalls = sum(recall_at_k(runs[qid], qrel_chunk.get(qid, {}), 10) for qid in runs)
    mrrs = sum(mrr_at_k(runs[qid], qrel_chunk.get(qid, {}), 10) for qid in runs)
    scores = {
        'nDCG@10': round(ndcgs / n, 4),
        'Recall@10': round(recalls / n, 4),
        'MRR@10': round(mrrs / n, 4),
        'n': n,
    }
    print(f'  {mode_name}: nDCG={scores["nDCG@10"]} Recall={scores["Recall@10"]} MRR={scores["MRR@10"]} (n={n})')
    results.append({'mode': mode_name, **scores})

# 保存
out_path = os.path.join(OUT_DIR, 'beir_c2_native_graph.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({'dataset': 'CRUD-RAG-300', 'kb_id': KB_ID, 'results': results},
              f, ensure_ascii=False, indent=2)
print(f'\n[done] saved: {out_path}')

# 汇总打印
print(f'\n=== 汇总 ===')
print(f'{"mode":<25} {"nDCG@10":>10} {"Recall@10":>10} {"MRR@10":>10}')
print('-' * 60)
for r in results:
    print(f'{r["mode"]:<25} {r["nDCG@10"]:>10.3f} {r["Recall@10"]:>10.3f} {r["MRR@10"]:>10.3f}')
