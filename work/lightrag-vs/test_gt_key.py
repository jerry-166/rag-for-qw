"""查 .env LITELLM_API_KEY 字节 + 用它直测 DashScope chat。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / 'backend' / '.env'
key = None
for line in env_path.read_text(encoding='utf-8').splitlines():
    if line.startswith('LITELLM_API_KEY='):
        key = line.split('=', 1)[1]
        break
print('key repr:', repr(key), 'len:', len(key))

from openai import OpenAI
c = OpenAI(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', api_key=key)
try:
    r = c.chat.completions.create(model='qwen3.7-flash',
        messages=[{'role': 'user', 'content': 'hi'}], max_tokens=10)
    print('chat OK:', r.choices[0].message.content[:30])
except Exception as e:
    print('chat ERR:', str(e)[:250])
