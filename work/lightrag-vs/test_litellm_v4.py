"""测 litellm 加 text-embedding-v4 (dim=1536) + qwen3.7-flash chat。"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from openai import OpenAI

for _ in range(12):
    try:
        c = OpenAI(base_url='http://localhost:4000', api_key='sk-jerry166')
        r = c.models.list()
        break
    except Exception:
        time.sleep(5)
else:
    print('[FATAL] litellm 4000 不通'); sys.exit(1)

v4 = [m.id for m in r.data if 'text-embedding-v4' in m.id]
qwen = [m.id for m in r.data if 'qwen' in m.id.lower()]
print(f'litellm models: {len(r.data)}, v4: {v4}, qwen: {qwen}')

print('\n=== chat qwen3.7-flash via litellm ===')
try:
    r = c.chat.completions.create(model='qwen3.7-flash',
        messages=[{'role': 'user', 'content': 'hi, 回复一个字'}], max_tokens=20)
    print(f'OK: {r.choices[0].message.content}')
except Exception as e:
    print(f'ERR: {str(e)[:200]}')

print('\n=== embedding text-embedding-v4 dim=1536 via litellm ===')
try:
    r = c.embeddings.create(model='text-embedding-v4', input='测试维度', dimensions=1536)
    print(f'OK dim={len(r.data[0].embedding)}')
except Exception as e:
    print(f'ERR: {str(e)[:200]}')
