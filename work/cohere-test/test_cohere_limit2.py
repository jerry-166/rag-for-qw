"""调 3 次 chat 看 trial remaining 变化（确认 20 calls 是否硬限制）。"""
import os, sys, httpx, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
env_path = Path(r"d:/workspace/rag-for-qw/backend/.env")
key = None
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line.startswith("COHERE_API_KEY="):
        key = line.split("=", 1)[1].strip()

H = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}

for i in range(3):
    r = httpx.post('https://api.cohere.com/v2/chat', headers=H,
        json={'model': 'command-a-plus-05-2026',
              'messages': [{'role': 'user', 'content': f'hi {i+1}'}]},
        timeout=30)
    trial_rem = r.headers.get('x-trial-endpoint-call-remaining')
    trial_lim = r.headers.get('x-trial-endpoint-call-limit')
    monthly = r.headers.get('x-endpoint-monthly-call-limit')
    print(f'[{i+1}] status={r.status_code} trial_remaining={trial_rem}/{trial_lim} monthly={monthly}')
    time.sleep(0.5)
