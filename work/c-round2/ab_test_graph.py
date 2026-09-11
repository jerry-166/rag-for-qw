"""A/B 测试：GRAPH_RELATION_MIN_SCORE=0.3 vs 0.5
10 个 query 测 graph 检索，对比返回 chunk 数 + BEIR 命中
"""
import os, sys, json, time, requests
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))

# 登录
def login():
    r = requests.post(f'{B}/api/auth/login', data={'username':'loadtester','password':'Loadtest#123'}, timeout=30)
    return r.json()['access_token']

TOKEN = login()
H = {'Authorization': f'Bearer {TOKEN}'}

# 加载 testset + qrel
with open(os.path.join(THIS, '..', '..', 'backend', 'evaluation', 'testsets', 'crud_rag_300.json'), encoding='utf-8') as f:
    ts = json.load(f)
samples = ts.get('samples', [])[:50]  # 取前 50 个

with open(os.path.join(THIS, 'qrels', 'crud_qrels.json'), encoding='utf-8') as f:
    qrels = json.load(f).get('qid_to_doc_id', {})

# PG 连接（chunk_id → doc_id 映射）
import psycopg2
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'

_chunk_cache = {}
def chunk_to_doc(cid, kb_id=65):
    if cid in _chunk_cache:
        return _chunk_cache[cid]
    try:
        c = psycopg2.connect(PG_DSN)
        cur = c.cursor()
        cur.execute("SELECT metadata->>'source' FROM document_chunk WHERE id=%s", (cid,))
        r = cur.fetchone()
        cur.close(); c.close()
        doc_id = r[0].replace('.md', '') if r and r[0] else None
        _chunk_cache[cid] = doc_id
        return doc_id
    except:
        return None

print('=== A/B 测试: GRAPH_RELATION_MIN_SCORE=0.3（10 query）===')
print(f'{"query":<40} {"results":>7} {"chunks":>6} {"hit":>4} {"rel_doc":>12}')
print('-' * 75)

total_hit = 0
total_chunks = 0

for s in samples:
    q = s['question'][:38]
    qid = s.get('metadata', {}).get('qid', '')
    rel = qrels.get(qid, {})
    rel_docs = list(rel.keys())[:3]
    
    t0 = time.time()
    try:
        r = requests.post(f'{B}/api/milvus/query',
            json={'query': s['question'], 'limit': 10, 'knowledge_base_id': 65,
                  'retrieval_mode': 'graph', 'use_rerank': True},
            headers=H, timeout=120)
        elapsed = time.time() - t0
        results = r.json().get('results', [])
        
        # chunk_id → doc_id
        doc_ids = []
        seen = set()
        for c in results:
            cid = c.get('chunk_id') or c.get('id') or c.get('metadata', {}).get('chunk_id')
            if cid is not None:
                did = chunk_to_doc(cid)
                if did and did not in seen:
                    doc_ids.append(did)
                    seen.add(did)
        
        # 命中 qrel？
        hit = any(did in rel for did in doc_ids)
        total_hit += 1 if hit else 0
        total_chunks += len(doc_ids)
        
        print(f'{q:<40} {len(results):>7} {len(doc_ids):>6} {"Y" if hit else "N":>4} {str(rel_docs[0]) if rel_docs else "":>12} ({elapsed:.1f}s)')
    except Exception as e:
        print(f'{q:<40} ERR: {str(e)[:60]}')

print(f'\n汇总: hit={total_hit}/10, avg_chunks={total_chunks/10:.1f}')
print(f'\n对比（score=0.5 时）: hit≈2-3/10, avg_chunks≈1-2')
print(f'对比（score=0.3 时）: hit={total_hit}/10, avg_chunks={total_chunks/10:.1f}')
