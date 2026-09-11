"""调试 graph 模式返回格式（看 chunk_id 字段名）"""
import os, sys, json, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

q = '在江苏省中医院副主任中医师徐顺娟提出的大暑养生建议中，她强调了养生的关键在于养护哪两个方面？'

r = requests.post(f'{B}/api/milvus/query',
    json={'query': q, 'limit': 10, 'knowledge_base_id': 65,
          'retrieval_mode': 'graph', 'use_rerank': True},
    headers=H, timeout=60)
print(f'graph: status={r.status_code}')
d = r.json()
results = d.get('results', [])
print(f'results count: {len(results)}')
for i, c in enumerate(results[:3]):
    print(f'\n--- result [{i}] ---')
    print(json.dumps(c, ensure_ascii=False, indent=2, default=str)[:800])
