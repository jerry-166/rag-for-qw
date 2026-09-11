"""测试 graph 检索的 ranking 内容 + 和 qrel 对比"""
import requests, time, json

tok = requests.post('http://localhost:8003/api/auth/login',
    data={'username':'loadtester','password':'Loadtest#123'}, timeout=10).json()['access_token']

# 测 2 个 query
queries = ['Adobe Express是什么', '大暑节气养生关键']

# 加载 qrel
with open('d:/workspace/rag-for-qw/work/c-round2/qrels/crud_qrels.json', encoding='utf-8') as f:
    qrels = json.load(f).get('qid_to_doc_id', {})

# 加载 testset 找 qid
with open('d:/workspace/rag-for-qw/backend/evaluation/testsets/crud_rag_300.json', encoding='utf-8') as f:
    ts = json.load(f)
samples = ts.get('samples', [])

for q in queries:
    # 找 qid
    qid = None
    for s in samples:
        if s['question'] == q:
            qid = s.get('metadata', {}).get('qid', '')
            break
    
    t0 = time.time()
    r = requests.post('http://localhost:8003/api/milvus/query',
        json={'query': q, 'limit': 10, 'knowledge_base_id': 65,
              'retrieval_mode': 'graph', 'use_rerank': True},
        headers={'Authorization': 'Bearer '+tok}, timeout=120)
    elapsed = time.time() - t0
    j = r.json()
    results = j.get('results', [])
    print(f'\nq={q[:30]} qid={qid} status={r.status_code} elapsed={elapsed:.1f}s results={len(results)}')
    
    # qrel 的 relevant doc
    rel = qrels.get(qid, {})
    print(f'  qrel relevant: {list(rel.keys())[:5]}')
    
    # ranking 的 doc_id
    for i, c in enumerate(results[:5]):
        cid = c.get('chunk_id') or c.get('id') or c.get('metadata', {}).get('chunk_id')
        print(f'  [{i}] chunk_id={cid} type={c.get("type","")} keys={list(c.keys())}')
