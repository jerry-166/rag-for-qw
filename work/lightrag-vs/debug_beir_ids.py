"""调试 hybrid_vec/keyword/lightrag 返回的 doc_id 格式"""
import requests, sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'
LR = 'http://localhost:9621'
T = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {T}'}
q = '向量数据库的核心原理'

# hybrid_vec
r = requests.post(f'{B}/api/hybrid/search', json={'query': q, 'limit': 5, 'knowledge_base_id': 17, 'retrieval_mode': 'hybrid', 'use_rerank': True}, headers=H, timeout=30)
results = r.json().get('results', [])
print(f'hybrid_vec results: {len(results)}')
if results:
    print('  first keys:', list(results[0].keys()))
    print('  first chunk_id:', results[0].get('chunk_id'), 'id:', results[0].get('id'))

# keyword (es)
r2 = requests.post(f'{B}/api/elasticsearch/search', json={'query': q, 'limit': 5, 'knowledge_base_id': 17, 'use_rerank': True}, headers=H, timeout=30)
results2 = r2.json().get('results', [])
print(f'\nkeyword results: {len(results2)}')
if results2:
    print('  first keys:', list(results2[0].keys()))
    print('  first chunk_id:', results2[0].get('chunk_id'), 'id:', results2[0].get('id'))

# lightrag
r3 = requests.post(f'{LR}/query/data', json={'query': q, 'mode': 'naive', 'chunk_top_k': 5}, timeout=60)
data = r3.json().get('data', {})
chunks = data.get('chunks', [])
print(f'\nlightrag chunks: {len(chunks)}')
if chunks:
    print('  first keys:', list(chunks[0].keys()))
    print('  first file_path:', chunks[0].get('file_path'), 'chunk_id:', chunks[0].get('chunk_id'))
