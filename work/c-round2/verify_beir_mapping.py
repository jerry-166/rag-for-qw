"""验证 BEIR chunk_id 映射：用 src doc query 测试 native + graph 模式"""
import os, sys, json, requests, psycopg2
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'

TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

# 用 crud_000 的 query 测试
q = '国家卫生健康委员会于2023年7月28日启动了名为"启明行动"的专项活动，旨在针对特定群体的特定健康问题进行防控。请问这项活动具体针对哪个群体的健康问题？'
print(f'query: {q[:60]}...')

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
    content = str(c.get('content', c.get('chunk_text', '')))[:80]
    print(f'  [{i}] chunk_id={cid} score={score} content={content}')

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
        content = str(c.get('content', c.get('chunk_text', '')))[:80]
        rtype = c.get('type', '')
        print(f'  [{i}] chunk_id={cid} score={score} type={rtype} content={content}')

# 3. chunk_id → filename 反查（验证 PG 映射）
print('\n=== chunk_id → filename 反查 ===')
if results:
    cid = results[0].get('chunk_id') or results[0].get('id')
    if cid:
        conn = psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        cur.execute("SELECT metadata->>'source', document_id, chunk_index FROM document_chunk WHERE id=%s", (cid,))
        row = cur.fetchone()
        if row:
            print(f'  chunk_id={cid} → source={row[0]} document_id={row[1]} chunk_index={row[2]}')
        cur.close()
        conn.close()

# 4. crud_qrels 验证
print('\n=== crud_qrels 验证 ===')
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qrels', 'crud_qrels.json'), encoding='utf-8') as f:
    qd = json.load(f)
qrels = qd.get('qid_to_doc_id', {})
# query 是 crud_000 的 question，qid = crud_q000
qid = 'crud_q000'
rel_docs = qrels.get(qid, {})
print(f'  qid={qid} relevant docs={rel_docs}')
