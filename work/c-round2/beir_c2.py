"""C 轮2 BEIR 检索质量评估
8 对象 × 3 指标（nDCG@10 / Recall@10 / MRR@10）× 2 数据集（CRUD-RAG + NFCorpus）= 48 数据点

8 对象：
  本项目 6 模式（native rerank关/开、advanced、hybrid_vec、keyword、graph）
  LightRAG 2 模式（naive/hybrid）

控制变量：
  切块 1000 + overlap 100（两系统 .env 已对齐）
  embedding dim 1536（两系统 .env 已对齐）

qrel：
  CRUD-RAG: query i → doc_id_i（1 relevant doc per query，自然 qrel）
  NFCorpus: BEIR test qrels（3-level relevance，avg 48 rel/query）

输出：work/c-round2/beir_c2_{crud,nfcorpus}.json + beir_c2_summary.json
"""
import os, sys, json, time, requests, psycopg2, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

B = 'http://localhost:8003'
LR = 'http://localhost:9621'
THIS = os.path.dirname(os.path.abspath(__file__))
TESTSET_DIR = os.path.normpath(os.path.join(THIS, '..', '..', 'backend', 'evaluation', 'testsets'))
QRELS_DIR = os.path.join(THIS, 'qrels')
OUT_DIR = THIS
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'

# 登录
def get_token():
    r = requests.post(f'{B}/api/auth/login',
        data={'username': 'loadtester', 'password': 'Loadtest#123'},
        timeout=10)
    r.raise_for_status()
    return r.json()['access_token']

TOKEN = get_token()
H = {'Authorization': f'Bearer {TOKEN}'}
_last_login = time.time()
def ensure_token():
    global TOKEN, H, _last_login
    if time.time() - _last_login > 50 * 60:
        TOKEN = get_token()
        H = {'Authorization': f'Bearer {TOKEN}'}
        _last_login = time.time()
        print(f'[token] refreshed at {time.strftime("%H:%M:%S")}')

# ── chunk_id 映射缓存 ──
# 1) ours：filename → PG chunk_ids（按 metadata->>'source' 反查）
_filename_chunk_cache = {}
def filename_to_chunk_ids(filename, kb_id):
    """filename like 'crud_000.md' → list of PG document_chunk.id（字符串）"""
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
        print(f'    pg err: {e}')
        result = []
    _filename_chunk_cache[key] = result
    return result

# 2) LightRAG：file_path → ours filename（直接同名，因为导入时 file_source=doc_id）
def lr_filepath_to_filename(file_path):
    """LightRAG file_path = 我们传入的 file_source = doc_id（如 crud_000）
    对应 ours 上传的 filename = doc_id + '.md'（如 crud_000.md）"""
    if not file_path:
        return None
    # LightRAG 可能存了 file_path = 'crud_000' 或 'crud_000.md'，都兼容
    if not file_path.endswith('.md'):
        return file_path + '.md'
    return file_path

# ── 各模式 query 端点 ──
def query_ours(query, mode_name, endpoint, extra, kb_id):
    """本项目检索 → 返回 doc_id ranking list（映射 chunk_id→doc_id 匹配 qrel）"""
    ensure_token()
    try:
        r = requests.post(f"{B}/api/{endpoint}",
            json={'query': query, 'limit': 10, 'knowledge_base_id': kb_id, **extra},
            headers=H, timeout=120)
        if r.status_code == 401:
            ensure_token()
            r = requests.post(f"{B}/api/{endpoint}",
                json={'query': query, 'limit': 10, 'knowledge_base_id': kb_id, **extra},
                headers=H, timeout=120)
        results = r.json().get('results', [])
        ids = []
        seen = set()  # 去重（同 doc 多 chunk 只算一次）
        for c in results:
            # chunk_id 可能在顶层、id 字段、或 metadata 里（graph 模式）
            cid = c.get('chunk_id') or c.get('id') or c.get('metadata', {}).get('chunk_id')
            if cid is not None:
                doc_id = _chunk_to_doc_id(cid, kb_id)
                did = str(doc_id) if doc_id else str(cid)
                if did not in seen:
                    ids.append(did)
                    seen.add(did)
        return ids
    except Exception as e:
        print(f'    {mode_name} err: {str(e)[:80]}')
        return []

# chunk_id → doc_id 缓存
_chunk_doc_cache = {}
def _chunk_to_doc_id(chunk_id, kb_id):
    """PG chunk_id → doc_id（metadata->>'source' 去掉 .md 后缀）"""
    key = (chunk_id, kb_id)
    if key in _chunk_doc_cache:
        return _chunk_doc_cache[key]
    try:
        conn = psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        cur.execute(
            "SELECT metadata->>'source' FROM document_chunk WHERE id=%s AND knowledge_base_id=%s",
            (chunk_id, kb_id))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            # source = 'crud_000.md' → doc_id = 'crud_000'
            doc_id = row[0].replace('.md', '')
            _chunk_doc_cache[key] = doc_id
            return doc_id
    except Exception as e:
        print(f'    chunk_to_doc err: {e}')
    _chunk_doc_cache[key] = None
    return None

def query_lightrag(query, mode, kb_id):
    """LightRAG /query/data → file_path → 反查 PG chunk_id"""
    try:
        r = requests.post(f"{LR}/query/data",
            json={'query': query, 'mode': mode, 'chunk_top_k': 10},
            timeout=120)
        data = r.json().get('data', {})
        chunks = data.get('chunks', [])
        ids = []
        for c in chunks:
            fp = c.get('file_path', '')
            fname = lr_filepath_to_filename(fp)
            if fname:
                ids.extend(filename_to_chunk_ids(fname, kb_id))
        return ids
    except Exception as e:
        print(f'    lightrag {mode} err: {str(e)[:80]}')
        return []

# ── 模式定义（C 轮2 只测 graph vs native，3 对象） ──
# (mode_name, ours_endpoint, ours_extra, lr_mode_or_None)
_ALL_MODES = [
    ('native_rerank_off', 'milvus/query', {'retrieval_mode': 'native', 'use_rerank': False}, None),
    ('native_rerank_on',  'milvus/query', {'retrieval_mode': 'native', 'use_rerank': True}, None),
    ('graph',             'milvus/query', {'retrieval_mode': 'graph', 'use_rerank': True}, None),
]
# 支持模式选择：python beir_c2.py native（只跑 native）| graph（只跑 graph）| all（全 3 个）
_mode_filter = sys.argv[1] if len(sys.argv) > 1 else 'all'
if _mode_filter == 'native':
    MODES = [m for m in _ALL_MODES if m[0].startswith('native')]
elif _mode_filter == 'graph':
    MODES = [m for m in _ALL_MODES if m[0] == 'graph']
else:
    MODES = _ALL_MODES
print(f'modes: {[m[0] for m in MODES]}')

# ── BEIR 指标（自实现，pytrec_eval TLS 装不上）──
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

def evaluate_runs(runs, qrel):
    """runs: {qid: [doc_id ranking]}, qrel: {qid: {doc_id: rel}}
    返回 {nDCG@10, Recall@10, MRR@10} 平均"""
    if not runs:
        return {'nDCG@10': 0.0, 'Recall@10': 0.0, 'MRR@10': 0.0, 'n': 0}
    n = len(runs)
    ndcgs, recalls, mrrs = 0, 0, 0
    for qid, ranking in runs.items():
        q = qrel.get(qid, {})
        ndcgs += ndcg_at_k(ranking, q, 10)
        recalls += recall_at_k(ranking, q, 10)
        mrrs += mrr_at_k(ranking, q, 10)
    return {
        'nDCG@10': round(ndcgs / n, 4),
        'Recall@10': round(recalls / n, 4),
        'MRR@10': round(mrrs / n, 4),
        'n': n,
    }

def run_dataset(dataset_name, testset_path, qrels_path, kb_id):
    """跑单个数据集的 BEIR 评估，8 模式 × 3 指标"""
    print(f'\n{"="*60}\n=== BEIR: {dataset_name} (kb_id={kb_id}) ===\n{"="*60}')
    with open(testset_path, encoding='utf-8') as f:
        ts = json.load(f)
    samples = ts.get('samples', [])
    print(f'testset: {len(samples)} samples')

    with open(qrels_path, encoding='utf-8') as f:
        qd = json.load(f)
    qrels = qd.get('qid_to_doc_id', {})
    print(f'qrels: {len(qrels)} queries')

    # 把 query → qid 映射；query 文本来自 testset 的 metadata.qid
    # qrel 的 key 是 qid（如 'crud_q000' 或 'PLAIN-2'）
    # testset sample 的 metadata.qid 是 qid
    # 对每个 sample，构建 query→qid 映射
    query_to_qid = {}
    for s in samples:
        qid = s.get('metadata', {}).get('qid', '')
        if qid:
            query_to_qid[s['question']] = qid
    print(f'query→qid mapped: {len(query_to_qid)}')

    # 各模式 run（3 并发，避免 LLM 限流）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []
    for mode_name, endpoint, extra, lr_mode in MODES:
        print(f'\n[mode] {mode_name}')
        runs = {}
        t1 = time.time()

        def _query_one(args):
            i, s = args
            q = s['question']
            qid = s.get('metadata', {}).get('qid', str(i))
            if lr_mode:
                ranking = query_lightrag(q, lr_mode, kb_id)
            else:
                ranking = query_ours(q, mode_name, endpoint, extra, kb_id)
            return qid, ranking

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(_query_one, (i, s)) for i, s in enumerate(samples)]
            done = 0
            for future in as_completed(futures):
                qid, ranking = future.result()
                runs[qid] = ranking
                done += 1
                if done % 50 == 0 or done == len(samples):
                    print(f'  [{done}/{len(samples)}] elapsed={time.time()-t1:.0f}s')
        scores = evaluate_runs(runs, qrels)
        print(f'  {mode_name}: nDCG={scores["nDCG@10"]} Recall={scores["Recall@10"]} MRR={scores["MRR@10"]} (n={scores["n"]})')
        results.append({
            'dataset': dataset_name,
            'mode': mode_name,
            **scores,
        })
    return results

# ── 跑 CRUD-RAG（C 轮2 只做 CRUD-RAG，不做 NFCorpus） ──
all_results = []

crud_kb_id = 65
crud_map_path = os.path.join(THIS, 'kb_map_crud.json')
if os.path.exists(crud_map_path):
    with open(crud_map_path, encoding='utf-8') as f:
        crud_kb_id = json.load(f).get('kb_id', 65)
crud_results = run_dataset(
    'CRUD-RAG-300',
    os.path.join(TESTSET_DIR, 'crud_rag_300.json'),
    os.path.join(QRELS_DIR, 'crud_qrels.json'),
    crud_kb_id,
)
all_results.extend(crud_results)
with open(os.path.join(OUT_DIR, 'beir_c2_crud.json'), 'w', encoding='utf-8') as f:
    json.dump({'dataset': 'CRUD-RAG-300', 'kb_id': crud_kb_id, 'results': crud_results},
              f, ensure_ascii=False, indent=2)

# 汇总
print(f'\n{"="*80}\n=== BEIR C2 汇总 ===\n{"="*80}')
print(f'{"dataset":<18} {"mode":<22} {"nDCG@10":>10} {"Recall@10":>10} {"MRR@10":>10} {"n":>5}')
print('-' * 80)
for r in all_results:
    print(f'{r["dataset"]:<18} {r["mode"]:<22} {r["nDCG@10"]:>10.3f} {r["Recall@10"]:>10.3f} {r["MRR@10"]:>10.3f} {r["n"]:>5}')

with open(os.path.join(OUT_DIR, 'beir_c2_summary.json'), 'w', encoding='utf-8') as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)
print(f'\n汇总已保存: {os.path.join(OUT_DIR, "beir_c2_summary.json")}')
