"""测试 native_rerank_on 请求看具体响应"""
import requests, time, json

tok = requests.post('http://localhost:8003/api/auth/login',
    data={'username':'loadtester','password':'Loadtest#123'}, timeout=10).json()['access_token']

t0 = time.time()
r = requests.post('http://localhost:8003/api/milvus/query',
    json={'query':'Adobe Express是什么','limit':10,'knowledge_base_id':65,
          'retrieval_mode':'native','use_rerank':True},
    headers={'Authorization':'Bearer '+tok}, timeout=120)
print(f'status={r.status_code} elapsed={time.time()-t0:.1f}s')
j = r.json()
results = j.get('results', [])
print(f'results count={len(results)}')
if results:
    print(f'first keys={list(results[0].keys())}')
    c = results[0].get('content') or results[0].get('chunk_text','')
    print(f'first content={str(c)[:150]}')
else:
    print(f'detail={j.get("detail","")}')
    print(f'full={json.dumps(j, ensure_ascii=False)[:300]}')
