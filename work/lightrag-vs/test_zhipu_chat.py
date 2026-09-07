"""测智谱 GLM-4-Flash（用 settings 配置，查 400 modelCode 原因）。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.chdir(r'D:\workspace\rag-for-qw\backend')
sys.path.insert(0, '.')
from config import settings, get_runtime
base = get_runtime('LITELLM_BASE_URL', settings.LITELLM_BASE_URL)
key = get_runtime('LITELLM_API_KEY', settings.LITELLM_API_KEY)
model = get_runtime('DEFAULT_MODEL', settings.DEFAULT_MODEL)
print(f'base_url: {base}')
print(f'api_key: {key[:20]}...')
print(f'model: {model}')

from openai import OpenAI
c = OpenAI(base_url=base, api_key=key)
try:
    r = c.chat.completions.create(model=model, messages=[{'role':'user','content':'hi'}], max_tokens=10)
    print(f'chat OK: {r.choices[0].message.content[:30]}')
except Exception as e:
    print(f'chat ERR: {str(e)[:250]}')
