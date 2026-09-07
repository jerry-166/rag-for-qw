"""测 DashScope（阿里云 OpenAI 兼容）Qwen3.7 LLM + embedding 可用性。
base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

key = os.environ.get('DASHSCOPE_API_KEY', '')
if not key:
    # 也查 .env
    from pathlib import Path
    env_path = Path(__file__).parent.parent.parent / 'backend' / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            if line.startswith('DASHSCOPE_API_KEY='):
                key = line.split('=', 1)[1].strip()
                break
print(f'DASHSCOPE_API_KEY: {key[:12]}...' if key else '[FATAL] DASHSCOPE_API_KEY not found')

if not key:
    sys.exit(1)

from openai import OpenAI
c = OpenAI(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', api_key=key)

print('\n=== LLM 测试 ===')
for m in ['qwen3.7-flash', 'qwen3.7-flash-2026-07-15', 'qwen-flash', 'qwen-plus', 'qwen-turbo']:
    try:
        r = c.chat.completions.create(model=m,
            messages=[{'role': 'user', 'content': 'hi, 回复一个字'}], max_tokens=20)
        print(f'OK   {m}: {r.choices[0].message.content[:40]}')
    except Exception as e:
        print(f'ERR  {m}: {str(e)[:140]}')

print('\n=== Embedding 测试 ===')
for m in ['text-embedding-v3', 'qwen3.7-text-embedding-flash', 'text-embedding-v4']:
    try:
        r = c.embeddings.create(model=m, input='测试向量数据库文本')
        dim = len(r.data[0].embedding)
        print(f'OK   {m}: dim={dim}')
    except Exception as e:
        print(f'ERR  {m}: {str(e)[:140]}')
