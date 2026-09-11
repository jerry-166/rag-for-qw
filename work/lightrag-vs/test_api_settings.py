"""查后端运行时 settings（看 LITELLM_API_KEY 运行时值）。"""
import requests, sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'
T = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {T}'}

# 查 settings
for ep in ['/api/settings', '/api/config', '/api/settings/list']:
    try:
        r = requests.get(B + ep, headers=H, timeout=10)
        print(f'{ep}: {r.status_code}')
        if r.status_code == 200:
            text = r.text[:2000]
            # 找 LITELLM_API_KEY
            if 'LITELLM_API_KEY' in text or 'litellm_api_key' in text.lower():
                print('  含 LITELLM_API_KEY')
            print(text[:1200])
            break
    except Exception as e:
        print(f'{ep}: err {str(e)[:80]}')
