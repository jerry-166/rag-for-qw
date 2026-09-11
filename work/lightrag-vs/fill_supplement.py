"""Fill 本项目 kb17_supplement 测试集（调 /api/evaluation/fill，用 claw agent 填 answer+contexts）
注意：supplement 样本已有 contexts（milvus 检索的），fill 会用 agent 重新生成 answer。
但 agent 也会重新检索 contexts——我们只想要 answer，所以这里用原生 agent fill（它会覆盖 contexts）。
实际上 supplement 的 contexts 已是 native 检索结果，与 agent fill 的 contexts 一致（都走 native）。
"""
import requests, json, os, time

B = 'http://localhost:8003'
TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

print("filling kb17_supplement via API...")
r = requests.post(B + '/api/evaluation/fill/kb17_supplement?knowledge_base_id=17&agent_type=claw',
    headers=H, timeout=600)
print(f"status={r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"before: {d.get('before')}")
    print(f"after: {d.get('after')}")
    print(f"filled: {d.get('filled')}")
else:
    print(f"err: {r.text[:300]}")
