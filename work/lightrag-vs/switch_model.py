"""kill 429 失败的 generate + PUT DEFAULT_MODEL=deepseek-chat（runtime override）+ 确认。"""
import requests, subprocess, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 1. kill generate 9152（429 失败循环）
subprocess.run(['taskkill', '/PID', '9152', '/F'], capture_output=True)
print("[kill] generate 9152 stopped", flush=True)

# 2. admin 登录 + PUT DEFAULT_MODEL=deepseek-chat（gpt-4o 429 限流，换 deepseek）
tok = requests.post('http://localhost:8003/api/auth/login', data={'username':'admin','password':'admin'}, timeout=10).json()['access_token']
h = {'Authorization': f'Bearer {tok}'}
r = requests.put('http://localhost:8003/api/settings', json={'configs':[{'key':'DEFAULT_MODEL','value':'gpt-4o'}]}, headers=h, timeout=10)
print(f"[settings] PUT DEFAULT_MODEL=gpt-4o: {r.status_code} {r.text[:200]}", flush=True)

# 3. 确认
r = requests.get('http://localhost:8003/api/settings', headers=h, timeout=10)
import json
data = r.json()
for c in (data if isinstance(data, list) else data.get('configs', [])):
    if isinstance(c, dict) and c.get('key') == 'DEFAULT_MODEL':
        print(f"[confirm] DEFAULT_MODEL = {c.get('value')}", flush=True)
