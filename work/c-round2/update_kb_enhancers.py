"""PUT /api/knowledge-bases/65 改 enhancers=['entity']
让 graph 模式真正工作（之前 enhancers=[] 导致 graph 降级 native）
"""
import requests
B = 'http://localhost:8003'
TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

KB_ID = 65
r = requests.put(f'{B}/api/knowledge-bases/{KB_ID}',
    json={'enhancers': ['entity']},
    headers=H, timeout=15)
print(f'PUT /api/knowledge-bases/{KB_ID} enhancers=[entity]: status={r.status_code}')
print(f'  body: {r.text[:300]}')

# 验证
r2 = requests.get(f'{B}/api/knowledge-bases', headers=H, timeout=10)
for kb in r2.json().get('knowledge_bases', []):
    if kb['id'] == KB_ID:
        print(f'  verified: name={kb.get("kb_name")} enhancers={kb.get("enhancers")}')
        break
