"""测 milvus query native KB17（text-embedding-v4 索引重建后）。
看检索结果 score + 是否 dim 报错。
"""
import requests, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'
T = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {T}'}

for q in ['向量数据库的核心原理', 'BM25的打分公式', '重排序的作用']:
    r = requests.post(B + '/api/milvus/query',
        json={'retrieval_mode': 'native', 'use_rerank': False, 'limit': 5,
              'knowledge_base_id': 17, 'query': q},
        headers=H, timeout=30)
    data = r.json()
    results = data.get('results', [])
    print(f'\n=== {q} (status {r.status_code}, {len(results)} 条) ===')
    if not results:
        print(f'  full response: {str(data)[:300]}')
    for c in results[:3]:
        text = c.get('content', c.get('chunk_text', ''))
        score = c.get('score', c.get('similarity'))
        print(f'  score={score} text={text[:60]}')
