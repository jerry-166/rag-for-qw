"""测 milvus query min_score=0（判断向量空间匹配 or 索引空）。"""
import requests, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'
T = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {T}'}

# set RETRIEVAL_MIN_SCORE=0
r = requests.put(B + '/api/settings', json={'RETRIEVAL_MIN_SCORE': 0}, headers=H, timeout=10)
print('set min_score=0:', r.status_code, r.text[:80])

# query
r = requests.post(B + '/api/milvus/query',
    json={'retrieval_mode': 'native', 'use_rerank': False, 'limit': 5,
          'knowledge_base_id': 17, 'query': '向量数据库的核心原理'},
    headers=H, timeout=30)
print('query status:', r.status_code)
results = r.json().get('results', [])
print(f'results: {len(results)}')
for c in results[:3]:
    print(' ', c.get('content', '')[:60], 'score:', c.get('score', '?'))
