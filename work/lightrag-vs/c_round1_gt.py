"""C 轮1 ground truth 准备：查 kb17_from_sessions 样本 + generate-gt 试 2 条。"""
import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'
TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}
DS = 'kb17_from_sessions'

# 1. 查样本
print('=== 1. 样本列表（前 3）===')
r = requests.get(B + f'/api/evaluation/dataset/{DS}/samples', headers=H, timeout=15)
d = r.json()
samples = d if isinstance(d, list) else d.get('samples', d.get('data', []))
print(f'样本数: {len(samples)}')
for s in samples[:3]:
    idx = s.get('idx', s.get('index', '?'))
    print(f'\n  idx={idx}')
    print(f'  question: {s.get("question", "")[:60]}')
    print(f'  answer:   {s.get("answer", "")[:60]}')
    print(f'  contexts: {len(s.get("contexts", []))} 条')
    if s.get('contexts'):
        print(f'    ctx[0]: {s["contexts"][0][:60]}')
    print(f'  ground_truth: {s.get("ground_truth", "")[:60]}')
    print(f'  status: {s.get("status", "")}')

# 2. generate-gt 试前 2 条
print('\n=== 2. generate-gt 前 2 条 ===')
for idx in [0, 1]:
    r = requests.post(B + f'/api/evaluation/dataset/{DS}/sample/{idx}/generate-gt',
        headers=H, timeout=90)
    print(f'\nidx={idx}: status={r.status_code}')
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:500])
    except Exception:
        print(r.text[:400])
