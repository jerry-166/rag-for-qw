"""列出所有 KB"""
import requests, json
B = 'http://localhost:8003'
TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

r = requests.get(f'{B}/api/knowledge-bases', headers=H, timeout=10)
print(f'status={r.status_code}')
print(f'raw: {r.text[:2000]}')
