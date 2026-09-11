"""C 轮1 探查：查现有测试集 + FAQ KB17 存量 + session 提取。
定 ground truth 来源（FAQ / session / LLM 补量）。"""
import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
try:
    TOKEN = requests.post(B + '/api/auth/login',
        data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10).json()['access_token']
except Exception as e:
    print(f'[FATAL] 后端未起或登录失败: {e}'); sys.exit(1)
H = {'Authorization': f'Bearer {TOKEN}'}
print(f'[login] OK, token={TOKEN[:12]}...')

# 1. 现有测试集
print('\n=== 1. 现有测试集 ===')
r = requests.get(B + '/api/evaluation/dataset/list', headers=H, timeout=15)
print('status:', r.status_code)
try:
    d = r.json()
    if isinstance(d, list):
        print(f'测试集数: {len(d)}')
        for ds in d[:10]:
            name = ds.get('name', ds.get('dataset_name', '?'))
            n = ds.get('sample_count', ds.get('total', ds.get('count', '?')))
            print(f'  - {name}: {n} 条')
    else:
        print(json.dumps(d, ensure_ascii=False, indent=2)[:600])
except Exception as e:
    print('parse err:', e, r.text[:300])

# 2. FAQ KB17 存量
print('\n=== 2. FAQ KB17 ===')
r = requests.get(B + '/api/faq', params={'knowledge_base_id': 17},
    headers=H, timeout=15)
print('status:', r.status_code)
try:
    d = r.json()
    items = d if isinstance(d, list) else d.get('items', d.get('faqs', d.get('data', [])))
    print(f'FAQ count: {len(items) if isinstance(items, list) else "?"}')
    if isinstance(items, list):
        for f in items[:5]:
            q = f.get('question', '')[:50]
            st = f.get('status', f.get('state', '?'))
            pc = f.get('promote_count', f.get('hit_count', 0))
            print(f'  - [{st}] hit={pc} | {q}')
except Exception as e:
    print('parse err:', e, r.text[:400])

# 3. from-sessions 提取（max 50）
print('\n=== 3. from-sessions (kb17, max 50) ===')
r = requests.post(B + '/api/evaluation/dataset/from-sessions',
    json={'dataset_name': 'kb17_from_sessions', 'max_samples': 50,
          'knowledge_base_id': 17},
    headers=H, timeout=60)
print('status:', r.status_code)
try:
    d = r.json()
    print(json.dumps(d, ensure_ascii=False, indent=2)[:800])
except Exception as e:
    print('parse err:', e, r.text[:500])
