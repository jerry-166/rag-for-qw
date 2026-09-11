"""C 轮1 批量补 ground_truth：generate-gt + PATCH 保存 + approve kb17_from_sessions 全部样本。
gpt-4o（litellm）已恢复，逐条调 LLM 基于 contexts 生成 gt 草稿。
"""
import requests, json, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}
DS = 'kb17_from_sessions'

# 查样本数
r = requests.get(B + f'/api/evaluation/dataset/{DS}/samples', headers=H, timeout=15)
d = r.json()
samples = d if isinstance(d, list) else d.get('samples', d.get('data', []))
n = len(samples)
print(f'[start] 样本数: {n}', flush=True)

ok = 0
low_quality = 0  # "上下文不足以回答" 计数
for i in range(n):
    # 1. generate-gt（带重试，gpt-4o 偶发 rate limit）
    gt = None
    for attempt in range(2):
        try:
            r = requests.post(B + f'/api/evaluation/dataset/{DS}/sample/{i}/generate-gt',
                headers=H, timeout=120)
            if r.status_code == 200:
                gt = r.json().get('ground_truth', '')
                break
            elif r.status_code == 429:
                print(f'[{i}] 429 rate limit, retry {attempt+1}...', flush=True)
                time.sleep(5)
            else:
                print(f'[{i}] generate-gt FAIL {r.status_code}: {r.text[:60]}', flush=True)
                break
        except Exception as e:
            print(f'[{i}] err: {str(e)[:60]}', flush=True)
            time.sleep(3)

    if not gt:
        continue

    if '上下文不足以回答' in gt or '不足以回答' in gt:
        low_quality += 1

    # 2. PATCH 保存 ground_truth
    r = requests.patch(B + f'/api/evaluation/dataset/{DS}/sample/{i}',
        json={'ground_truth': gt}, headers=H, timeout=15)
    if r.status_code != 200:
        print(f'[{i}] PATCH FAIL {r.status_code}', flush=True)
        continue

    # 3. approve
    r = requests.post(B + f'/api/evaluation/dataset/{DS}/sample/{i}/approve',
        headers=H, timeout=15)
    if r.status_code == 200:
        ok += 1
        print(f'[{i+1}/{n}] OK gt={gt[:50]}', flush=True)
    else:
        print(f'[{i}] approve FAIL {r.status_code}', flush=True)

    time.sleep(1)  # 避 gpt-4o rate limit

print(f'\n[done] approved {ok}/{n}, low_quality(不足以回答)={low_quality}', flush=True)
json.dump({'approved': ok, 'total': n, 'low_quality': low_quality},
    open('work/lightrag-vs/result_c_batch_gt.json', 'w'), ensure_ascii=False)
print('saved result_c_batch_gt.json', flush=True)
