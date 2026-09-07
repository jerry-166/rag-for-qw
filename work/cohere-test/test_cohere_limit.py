"""查 Cohere 限额（v2 check-api-key + chat response headers rate limit）。"""
import os, sys, httpx
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
env_path = Path(r"d:/workspace/rag-for-qw/backend/.env")
key = None
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line.startswith("COHERE_API_KEY="):
        key = line.split("=", 1)[1].strip()
print(f'key: {key[:12]}...')

H = {'Authorization': f'Bearer {key}'}

# v2 check-api-key
print('\n=== v2 check-api-key ===')
try:
    r = httpx.post('https://api.cohere.com/v2/check-api-key', headers=H, timeout=15)
    print(f'status: {r.status_code}')
    print(f'body: {r.text[:300]}')
except Exception as e:
    print(f'err: {str(e)[:150]}')

# chat + 看 rate limit headers
print('\n=== chat response headers（rate limit）===')
try:
    r = httpx.post('https://api.cohere.com/v2/chat',
        headers={**H, 'Content-Type': 'application/json'},
        json={'model': 'command-a-plus-05-2026',
              'messages': [{'role': 'user', 'content': 'hi'}]},
        timeout=30)
    print(f'status: {r.status_code}')
    for h, v in r.headers.items():
        if any(k in h.lower() for k in ['limit', 'rate', 'quota', 'remaining', 'reset', 'billing']):
            print(f'  {h}: {v}')
    if r.status_code != 200:
        print(f'body: {r.text[:300]}')
except Exception as e:
    print(f'err: {str(e)[:150]}')
