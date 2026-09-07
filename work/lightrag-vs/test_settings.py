"""查 settings + get_runtime 实际值（401 根因：settings 读 .env 还是旧值？）。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.chdir(r'D:\workspace\rag-for-qw\backend')
sys.path.insert(0, '.')
from config import settings, get_runtime
print('settings.LITELLM_API_KEY:', repr(settings.LITELLM_API_KEY))
print('get_runtime LITELLM_API_KEY:', repr(get_runtime('LITELLM_API_KEY', settings.LITELLM_API_KEY)))
print('settings.LITELLM_BASE_URL:', settings.LITELLM_BASE_URL)
print('settings.DEFAULT_MODEL:', settings.DEFAULT_MODEL)
print('os.environ LITELLM_API_KEY:', repr(os.environ.get('LITELLM_API_KEY', 'NOT_SET')))
print('os.environ DASHSCOPE_API_KEY:', repr(os.environ.get('DASHSCOPE_API_KEY', 'NOT_SET')[:20]))
