"""探 Cohere API：check-api-key + rerank，查 403 原因。"""
import httpx

KEY = 'bZuuYTt4BiDfDCufG50gSkztjN3aZuJ7kUicmAPK'
H = {'Authorization': f'Bearer {KEY}'}

print('=== 1. check-api-key (v1) ===')
try:
    r = httpx.get('https://api.cohere.com/v1/check-api-key', headers=H, timeout=15)
    print('status:', r.status_code)
    print('body:', r.text[:600])
except Exception as e:
    print('err:', e)

print('\n=== 2. check-api-key (v2, 新版) ===')
try:
    r = httpx.post('https://api.cohere.com/v2/check-api-key', headers=H, timeout=15)
    print('status:', r.status_code)
    print('body:', r.text[:600])
except Exception as e:
    print('err:', e)

print('\n=== 3. rerank-v3.5 ===')
try:
    r = httpx.post('https://api.cohere.com/v1/rerank',
        headers={**H, 'Content-Type': 'application/json', 'Accept': 'application/json'},
        json={'model': 'rerank-v3.5', 'query': '什么是向量数据库',
              'documents': ['向量数据库存储向量数据', '今天天气不错'],
              'top_n': 1}, timeout=15)
    print('status:', r.status_code)
    print('body:', r.text[:800])
    print('www-authenticate:', r.headers.get('www-authenticate'))
    print('x-cohere-request-id:', r.headers.get('x-cohere-request-id'))
except Exception as e:
    print('err:', e)

print('\n=== 4. rerank-english-v3.0 (降级模型) ===')
try:
    r = httpx.post('https://api.cohere.com/v1/rerank',
        headers={**H, 'Content-Type': 'application/json'},
        json={'model': 'rerank-english-v3.0', 'query': 'database',
              'documents': ['vector db', 'weather'], 'top_n': 1}, timeout=15)
    print('status:', r.status_code)
    print('body:', r.text[:800])
except Exception as e:
    print('err:', e)
