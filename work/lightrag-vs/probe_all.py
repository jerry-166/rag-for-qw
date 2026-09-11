"""C 轮1 一站式探测：环境变量 + 各服务状态 + milvus/lightrag 检索能力 + 测试集现状。
避免 PowerShell 内联引号转义问题。
"""
import os, sys, json, time, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

print('=' * 60)
print('[1] 环境变量')
print('=' * 60)
for k in ['ZHIPU_API_KEY', 'DASHSCOPE_API_KEY', 'COHERE_API_KEY',
          'LITELLM_API_KEY', 'LITELLM_BASE_URL', 'BASE_URL',
          'EMBEDDING_MODEL', 'EMBEDDING_BASE_URL', 'DEFAULT_MODEL']:
    v = os.environ.get(k, '')
    masked = (v[:12] + '...') if v and len(v) > 15 else v
    print(f'  {k} = {masked}')

# 加 backend .env
backend_env = os.path.join(os.path.dirname(__file__), '..', '..', 'backend', '.env')
print(f'\n  backend/.env path: {backend_env} exists={os.path.exists(backend_env)}')
if os.path.exists(backend_env):
    with open(backend_env, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and ('KEY' in line or 'URL' in line or 'MODEL' in line or 'DIM' in line):
                k, _, v = line.partition('=')
                k = k.strip(); v = v.strip().strip('"').strip("'")
                masked = (v[:15] + '...') if len(v) > 18 else v
                print(f'  env: {k} = {masked}')

print('\n' + '=' * 60)
print('[2] 各服务健康')
print('=' * 60)
services = [
    ('backend 8003', 'http://localhost:8003/docs'),
    ('litellm 4000', 'http://localhost:4000/health'),
    ('lightrag 9621', 'http://localhost:9621/health'),
]
for name, url in services:
    try:
        r = requests.get(url, timeout=5)
        print(f'  {name}: {r.status_code}')
    except Exception as e:
        print(f'  {name}: DOWN ({str(e)[:60]})')

print('\n' + '=' * 60)
print('[3] 后端 settings')
print('=' * 60)
try:
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
    from config import settings, get_runtime
    print(f'  DEFAULT_MODEL: {settings.DEFAULT_MODEL}')
    print(f'  EMBEDDING_MODEL: {settings.EMBEDDING_MODEL}')
    print(f'  EMBEDDING_BASE_URL: {settings.EMBEDDING_BASE_URL}')
    print(f'  EMBEDDING_DIM: {settings.EMBEDDING_DIM}')
    print(f'  LITELLM_BASE_URL: {settings.LITELLM_BASE_URL}')
    print(f'  get_runtime(LITELLM_API_KEY)[:12]: {str(get_runtime("LITELLM_API_KEY"))[:12]}...')
    print(f'  get_runtime(EMBEDDING_API_KEY)[:12]: {str(get_runtime("EMBEDDING_API_KEY"))[:12]}...')
except Exception as e:
    print(f'  ERR import backend config: {e}')

print('\n' + '=' * 60)
print('[4] 本项目 milvus query native KB17')
print('=' * 60)
B = 'http://localhost:8003'
try:
    tok = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=5).json()['access_token']
    H = {'Authorization': f'Bearer {tok}'}
    for q in ['向量数据库的核心原理', 'BM25的打分公式', '重排序的作用']:
        r = requests.post(B + '/api/milvus/query',
            json={'retrieval_mode': 'native', 'use_rerank': False, 'limit': 5,
                  'knowledge_base_id': 17, 'query': q},
            headers=H, timeout=30)
        j = r.json()
        results = j.get('results', [])
        snippet = results[0].get('content', results[0].get('chunk_text', ''))[:60] if results else '<none>'
        score = results[0].get('score', 'NA') if results else 'NA'
        print(f'  [{q}] status={r.status_code} n={len(results)} top_score={score} snippet={snippet}')
        time.sleep(0.3)
except Exception as e:
    print(f'  ERR: {e}')

print('\n' + '=' * 60)
print('[5] LightRAG query naive')
print('=' * 60)
try:
    r = requests.post('http://localhost:9621/query',
        json={'query': '向量数据库的核心原理', 'mode': 'naive', 'top_k': 5},
        timeout=60)
    j = r.json()
    answer = j.get('response', '')
    refs = j.get('references', [])
    print(f'  status={r.status_code} answer_len={len(answer)} refs={len(refs)}')
    if answer:
        print(f'  answer snippet: {answer[:100]}')
    if refs:
        print(f'  first ref content[:80]: {refs[0].get("content","")[:80]}')
except Exception as e:
    print(f'  ERR: {e}')

print('\n' + '=' * 60)
print('[6] 测试集现状')
print('=' * 60)
TESTSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets'))
targets = ['kb17_supplement', 'kb17_lightrag_naive', 'kb17_lightrag_hybrid',
           'kb17_ours_native_rerank_off', 'kb17_ours_native_rerank_on',
           'kb17_ours_advanced', 'kb17_ours_hybrid_vec', 'kb17_ours_keyword']
for name in targets:
    p = os.path.join(TESTSET_DIR, f'{name}.json')
    if not os.path.exists(p):
        print(f'  {name}: MISSING')
        continue
    d = json.load(open(p, encoding='utf-8'))
    samples = d.get('samples', [])
    complete = sum(1 for s in samples if s.get('answer') and s.get('contexts'))
    has_gt = sum(1 for s in samples if s.get('ground_truth'))
    # 实质 gt = ground_truth 不含 "不足以回答"
    substantive = sum(1 for s in samples if s.get('ground_truth') and '不足以回答' not in s.get('ground_truth', ''))
    print(f'  {name}: total={len(samples)} complete(answer+ctx)={complete} has_gt={has_gt} substantive_gt={substantive}')

print('\n[done]')
