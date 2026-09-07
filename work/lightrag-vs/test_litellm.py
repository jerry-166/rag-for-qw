"""列 litellm 可用模型 + 测非 gpt-4o 模型（找替代）。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import httpx
from openai import OpenAI

H = {'Authorization': 'Bearer sk-jerry166'}
r = httpx.get('http://localhost:4000/v1/models', headers=H, timeout=10)
models = sorted([m['id'] for m in r.json().get('data', [])])
print(f'litellm models ({len(models)}):')
for m in models:
    print(f'  - {m}')

print('\n=== 测试候选模型 ===')
c = OpenAI(base_url='http://localhost:4000', api_key='sk-jerry166')
# 测非 gpt-4o 的候选
candidates = [m for m in models if m != 'gpt-4o' and
              any(k in m.lower() for k in ['gpt-4o-mini', 'gpt-4', 'gpt-3.5', 'claude', 'gemini', 'qwen', 'deepseek'])]
print(f'候选: {candidates[:10]}')
for m in candidates[:6]:
    try:
        r = c.chat.completions.create(model=m,
            messages=[{'role': 'user', 'content': 'hi'}], max_tokens=5)
        print(f'OK   {m}: {r.choices[0].message.content[:30]}')
    except Exception as e:
        print(f'ERR  {m}: {str(e)[:120]}')
