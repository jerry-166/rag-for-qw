"""删 smoke test KB 62/63/64 + 测试 docs（清场）"""
import requests
B = 'http://localhost:8003'
TOKEN = requests.post(f'{B}/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

# 列出所有 KB
r = requests.get(f'{B}/api/knowledge-bases', headers=H, timeout=10)
kbs = r.json().get('knowledge_bases', [])
print(f'before: {len(kbs)} KBs')
for kb in kbs:
    name = kb.get('kb_name', '')
    if 'SmokeTest' in name:
        kid = kb['id']
        print(f'  delete KB {kid} ({name})')
        rd = requests.delete(f'{B}/api/knowledge-bases/{kid}', headers=H, timeout=15)
        print(f'    {rd.status_code} {rd.text[:100]}')

r = requests.get(f'{B}/api/knowledge-bases', headers=H, timeout=10)
after = r.json().get('knowledge_bases', [])
print(f'after: {len(after)} KBs')
for kb in after:
    print(f'  id={kb["id"]} name={kb.get("kb_name")}')

