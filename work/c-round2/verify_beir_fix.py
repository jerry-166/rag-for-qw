"""验证 BEIR 脚本修复后能正确提取 graph 模式的 chunk_id"""
import os, sys, json, requests, psycopg2
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'

TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

q = '在江苏省中医院副主任中医师徐顺娟提出的大暑养生建议中，她强调了养生的关键在于养护哪两个方面？'
print(f'query: {q[:60]}...')

# graph 模式
r = requests.post(f'{B}/api/milvus/query',
    json={'query': q, 'limit': 10, 'knowledge_base_id': 65,
          'retrieval_mode': 'graph', 'use_rerank': True},
    headers=H, timeout=60)
results = r.json().get('results', [])
print(f'\ngraph results: {len(results)}')

# 用修复后的逻辑提取 chunk_id
ids = []
for c in results:
    cid = c.get('chunk_id') or c.get('id')
    if cid is None:
        cid = c.get('metadata', {}).get('chunk_id')
    if cid is not None:
        ids.append(str(cid))
print(f'extracted chunk_ids: {ids}')

# 反查 filename
conn = psycopg2.connect(PG_DSN)
cur = conn.cursor()
for cid in ids[:3]:
    cur.execute("SELECT metadata->>'source' FROM document_chunk WHERE id=%s", (cid,))
    row = cur.fetchone()
    print(f'  chunk_id={cid} → source={row[0] if row else "?"}')
cur.close()
conn.close()

# relevant doc: crud_000 → chunk_ids [10057, 10058]
print(f'\nrelevant chunk_ids: 10057, 10058 (crud_000)')
print(f'graph hit relevant: {any(c in ["10057", "10058"] for c in ids)}')
