"""复验前置校验：loadtester 登录、KB17/18 存在、文档规模、单发检索时延（含 rerank）。"""
import requests, json, time

B = 'http://localhost:8003'
r = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10)
print('login:', r.status_code)
tok = r.json()['access_token']
H = {'Authorization': f'Bearer {tok}'}

kbs = requests.get(B + '/api/knowledge-bases', headers=H, timeout=10).json()
items = kbs.get('knowledge_bases', [])
kb17 = next((k for k in items if k.get('id') == 17), None)
kb18 = next((k for k in items if k.get('id') == 18), None)
print('KB17:', {k: kb17.get(k) for k in ('id', 'kb_name', 'is_owner')} if kb17 else 'MISSING')
print('KB18:', {k: kb18.get(k) for k in ('id', 'kb_name', 'is_owner')} if kb18 else 'MISSING')

for kb in (17, 18):
    d = requests.get(B + f'/api/documents?kb_id={kb}&page=1&page_size=1', headers=H, timeout=10).json()
    print(f'KB{kb} docs total =', d.get('total', d if isinstance(d, int) else '?'))

# 单发检索：native + rerank（复验 reranker 修复的最小证据：应秒级返回，不再是 22s+）
for mode in ('native', 'hybrid'):
    t0 = time.perf_counter()
    r = requests.post(B + '/api/milvus/query', headers=H, timeout=120,
                      json={'query': '向量数据库的核心原理', 'retrieval_mode': mode,
                            'use_rerank': True, 'knowledge_base_id': 17, 'limit': 10})
    dt = time.perf_counter() - t0
    n = len(r.json().get('results', [])) if r.status_code == 200 else -1
    print(f'single {mode}+rerank: code={r.status_code} results={n} {dt:.2f}s')

# 关键词（BM25 多桶重构路径）
t0 = time.perf_counter()
r = requests.post(B + '/api/elasticsearch/search', headers=H, timeout=60,
                  json={'query': '向量数据库', 'use_rerank': True, 'knowledge_base_id': 17, 'limit': 10})
dt = time.perf_counter() - t0
n = len(r.json().get('results', [])) if r.status_code == 200 else -1
print(f'single keyword(BM25)+rerank: code={r.status_code} results={n} {dt:.2f}s')
print('PREFLIGHT DONE')
