"""测 litellm 加 DashScope Qwen3.7 provider 是否生效（via litellm 4000）。"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from openai import OpenAI

# 等 litellm 起来
for _ in range(12):
    try:
        c = OpenAI(base_url='http://localhost:4000', api_key='sk-jerry166')
        r = c.models.list()
        break
    except Exception:
        time.sleep(5)
else:
    print('[FATAL] litellm 4000 不通'); sys.exit(1)

qwen = [m.id for m in r.data if 'qwen' in m.id.lower()]
print(f'litellm models: {len(r.data)}, qwen: {qwen}')

print('\n=== chat 测试 qwen3.7-flash via litellm ===')
try:
    r = c.chat.completions.create(model='qwen3.7-flash',
        messages=[{'role': 'user', 'content': 'hi, 回复一个字'}], max_tokens=20)
    print(f'OK qwen3.7-flash: {r.choices[0].message.content}')
except Exception as e:
    print(f'ERR qwen3.7-flash: {str(e)[:200]}')

print('\n=== embedding 测试 github_copilot（保持） ===')
try:
    r = c.embeddings.create(model='github_copilot/text-embedding-ada-002', input='测试')
    print(f'OK github_copilot: dim={len(r.data[0].embedding)}')
except Exception as e:
    print(f'ERR github_copilot: {str(e)[:200]}')
