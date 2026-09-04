"""探 Cohere 403 根因：CDN/区域/代理 + litellm 转发可能。"""
import os, httpx

KEY = 'bZuuYTt4BiDfDCufG50gSkztjN3aZuJ7kUicmAPK'

print('=== env proxies ===')
print('HTTPS_PROXY:', os.environ.get('HTTPS_PROXY'))
print('HTTP_PROXY:', os.environ.get('HTTP_PROXY'))
print('ALL_PROXY:', os.environ.get('ALL_PROXY'))
print('NO_PROXY:', os.environ.get('NO_PROXY'))

print('\n=== api.cohere.com response headers ===')
try:
    r = httpx.get('https://api.cohere.com/v1/check-api-key',
        headers={'Authorization': f'Bearer {KEY}'}, timeout=15)
    print('status:', r.status_code)
    for k in ['server', 'cf-ray', 'cf-cache-status', 'content-type',
              'x-mw-api-key-state', 'via']:
        print(f'  {k}: {r.headers.get(k)}')
    print('  body[:200]:', r.text[:200])
except Exception as e:
    print('err:', e)

print('\n=== litellm rerank (localhost:4000, sk-jerry166) ===')
try:
    r = httpx.post('http://localhost:4000/rerank',
        json={'model': 'cohere/rerank-v3.5', 'query': 'test',
              'documents': ['a', 'b'], 'top_n': 1},
        headers={'Authorization': 'Bearer sk-jerry166'}, timeout=15)
    print('status:', r.status_code)
    print('body[:400]:', r.text[:400])
except Exception as e:
    print('err:', e)

print('\n=== litellm /v1/rerank ===')
try:
    r = httpx.post('http://localhost:4000/v1/rerank',
        json={'model': 'cohere/rerank-v3.5', 'query': 'test',
              'documents': ['a', 'b'], 'top_n': 1},
        headers={'Authorization': 'Bearer sk-jerry166'}, timeout=15)
    print('status:', r.status_code)
    print('body[:400]:', r.text[:400])
except Exception as e:
    print('err:', e)

print('\n=== litellm /v1/models (查 cohere 有无) ===')
try:
    r = httpx.get('http://localhost:4000/v1/models',
        headers={'Authorization': 'Bearer sk-jerry166'}, timeout=15)
    print('status:', r.status_code)
    import json
    data = r.json()
    cohere_models = [m['id'] for m in data.get('data', []) if 'cohere' in m.get('id', '').lower() or 'rerank' in m.get('id', '').lower()]
    print('cohere/rerank models:', cohere_models[:20])
except Exception as e:
    print('err:', e)
