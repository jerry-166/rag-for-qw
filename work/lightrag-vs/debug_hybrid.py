"""调试 hybrid/search 为何返回 0"""
import requests, sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'
T = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {T}'}

# 测 hybrid/search
r = requests.post(f'{B}/api/hybrid/search',
    json={'query': '向量数据库的核心原理', 'limit': 10, 'knowledge_base_id': 17,
          'retrieval_mode': 'hybrid', 'use_rerank': True},
    headers=H, timeout=30)
print(f'hybrid/search status={r.status_code}')
print(f'hybrid/search body[:500]: {r.text[:500]}')

# 测 milvus/query native 对照
r2 = requests.post(f'{B}/api/milvus/query',
    json={'query': '向量数据库的核心原理', 'limit': 5, 'knowledge_base_id': 17,
          'retrieval_mode': 'native', 'use_rerank': False},
    headers=H, timeout=30)
j2 = r2.json()
print(f'\nmilvus/query native status={r2.status_code} results={len(j2.get("results",[]))}')

# 测 elasticsearch/search (keyword)
r3 = requests.post(f'{B}/api/elasticsearch/search',
    json={'query': '向量数据库的核心原理', 'limit': 5, 'knowledge_base_id': 17,
          'use_rerank': True},
    headers=H, timeout=30)
j3 = r3.json()
print(f'elasticsearch/search status={r3.status_code} results={len(j3.get("results",[]))}')
