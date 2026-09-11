"""测试 native_rerank_on 的 msg（失败原因）"""
import requests, time

tok = requests.post('http://localhost:8003/api/auth/login',
    data={'username':'loadtester','password':'Loadtest#123'}, timeout=10).json()['access_token']

# 测 3 个 query
queries = ['Adobe Express是什么', '大暑节气养生', 'AIC Inc.营业']

for q in queries:
    t0 = time.time()
    try:
        r = requests.post('http://localhost:8003/api/milvus/query',
            json={'query': q, 'limit': 10, 'knowledge_base_id': 65,
                  'retrieval_mode': 'native', 'use_rerank': True},
            headers={'Authorization': 'Bearer '+tok}, timeout=60)
        elapsed = time.time() - t0
        j = r.json()
        results = j.get('results', [])
        contexts = [c.get('content') or c.get('chunk_text', '') for c in results
                    if c.get('content') or c.get('chunk_text', '')]
        print(f'q={q[:20]} status={r.status_code} elapsed={elapsed:.1f}s results={len(results)} contexts={len(contexts)}')
        if not contexts and results:
            print(f'  result keys={list(results[0].keys())}')
            print(f'  content={repr(results[0].get("content",""))[:100]}')
            print(f'  chunk_text={repr(results[0].get("chunk_text",""))[:100]}')
    except Exception as e:
        print(f'q={q[:20]} EXC: {type(e).__name__}: {str(e)[:100]}')
