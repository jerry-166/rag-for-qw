"""用 testset[0] 的正确 query 验证 native + graph 检索 + chunk_id 映射"""
import os, sys, json, requests, psycopg2
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'
THIS = os.path.dirname(os.path.abspath(__file__))

TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

# 加载 testset[0] 的 question
TESTSET_PATH = r'd:\workspace\rag-for-qw\backend\evaluation\testsets\crud_rag_300.json'
with open(TESTSET_PATH, encoding='utf-8') as f:
    ts = json.load(f)
s0 = ts['samples'][0]
q = s0['question']
qid = s0.get('metadata', {}).get('qid', '')
print(f'query (testset[0]): {q[:80]}')
print(f'qid: {qid}')

# 加载 qrels
with open(os.path.join(THIS, 'qrels', 'crud_qrels.json'), encoding='utf-8') as f:
    qd = json.load(f)
qrels = qd.get('qid_to_doc_id', {})
rel_docs = qrels.get(qid, {})
print(f'relevant docs: {rel_docs}')

# relevant doc_id → chunk_id 映射
print('\n=== relevant doc → chunk_id 映射 ===')
conn = psycopg2.connect(PG_DSN)
cur = conn.cursor()
for doc_id in rel_docs:
    filename = f'{doc_id}.md'
    cur.execute("SELECT id, chunk_index FROM document_chunk WHERE knowledge_base_id=65 AND metadata->>'source'=%s ORDER BY chunk_index", (filename,))
    rows = cur.fetchall()
    print(f'  {doc_id} ({filename}) → chunk_ids: {[(r[0], r[1]) for r in rows]}')

# 1. native 模式
print('\n=== native 模式 ===')
r = requests.post(f'{B}/api/milvus/query',
    json={'query': q, 'limit': 10, 'knowledge_base_id': 65,
          'retrieval_mode': 'native', 'use_rerank': False},
    headers=H, timeout=30)
d = r.json()
results = d.get('results', [])
print(f'status={r.status_code} results={len(results)}')
for i, c in enumerate(results[:5]):
    cid = c.get('chunk_id') or c.get('id')
    score = c.get('score', c.get('distance', ''))
    # 反查 filename
    cur.execute("SELECT metadata->>'source' FROM document_chunk WHERE id=%s", (cid,))
    row = cur.fetchone()
    fname = row[0] if row else '?'
    print(f'  [{i}] chunk_id={cid} score={score:.4f} source={fname}')

# 2. graph 模式
print('\n=== graph 模式 ===')
r2 = requests.post(f'{B}/api/milvus/query',
    json={'query': q, 'limit': 10, 'knowledge_base_id': 65,
          'retrieval_mode': 'graph', 'use_rerank': True},
    headers=H, timeout=60)
d2 = r2.json()
results2 = d2.get('results', [])
print(f'status={r2.status_code} results={len(results2)}')
if r2.status_code != 200:
    print(f'  body: {r2.text[:300]}')
else:
    for i, c in enumerate(results2[:5]):
        cid = c.get('chunk_id') or c.get('id')
        score = c.get('score', c.get('distance', ''))
        rtype = c.get('type', '')
        cur.execute("SELECT metadata->>'source' FROM document_chunk WHERE id=%s", (cid,))
        row = cur.fetchone()
        fname = row[0] if row else '?'
        print(f'  [{i}] chunk_id={cid} score={score:.4f} type={rtype} source={fname}')

cur.close()
conn.close()
