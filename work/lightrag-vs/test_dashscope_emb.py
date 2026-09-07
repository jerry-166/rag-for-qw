"""测 qwen3.7-text-embedding-flash dimensions 参数（1024/1536/2048）。"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
key = os.environ.get('DASHSCOPE_API_KEY')
from openai import OpenAI
c = OpenAI(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', api_key=key)

for dim in [1024, 1536, 2048]:
    try:
        r = c.embeddings.create(model='qwen3.7-text-embedding-flash',
            input='测试维度', dimensions=dim)
        print(f'dim={dim}: OK len={len(r.data[0].embedding)}')
    except Exception as e:
        print(f'dim={dim}: ERR {str(e)[:150]}')

# 也测 text-embedding-v4（支持 dimensions）
print()
for dim in [1024, 1536]:
    try:
        r = c.embeddings.create(model='text-embedding-v4', input='测试', dimensions=dim)
        print(f'v4 dim={dim}: OK len={len(r.data[0].embedding)}')
    except Exception as e:
        print(f'v4 dim={dim}: ERR {str(e)[:120]}')
