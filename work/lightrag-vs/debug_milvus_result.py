"""调试本项目 milvus/query 返回结构，看有没有 chunk_id/pg_chunk_id"""
import requests, sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'
T = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {T}'}
r = requests.post(f'{B}/api/milvus/query',
    json={'retrieval_mode': 'native', 'use_rerank': False, 'limit': 3,
          'knowledge_base_id': 17, 'query': '向量数据库的核心原理'},
    headers=H, timeout=30)
j = r.json()
results = j.get('results', [])
print(f'results count: {len(results)}')
if results:
    print('first result keys:', list(results[0].keys()))
    print('first result:', json.dumps(results[0], ensure_ascii=False)[:600])
