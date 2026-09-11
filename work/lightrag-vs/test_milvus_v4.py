"""测 milvus query（text-embedding-v4 embedding 查询 + 旧 github_copilot 索引）。
看检索结果是否相关（向量空间是否兼容）。
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
    results = r.json().get('results', [])
    print(f'\n=== {q} (status {r.status_code}, {len(results)} 条) ===')
    for c in results[:3]:
        text = c.get('content', c.get('chunk_text', ''))
        print(' ', text[:70])
