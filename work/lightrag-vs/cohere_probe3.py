"""测 Cohere rerank 各模型可用性（走代理 7897），选中文适用的。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import httpx

KEY = 'bZuuYTt4BiDfDCufG50gSkztjN3aZuJ7kUicmAPK'
H = {'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}

for model in ['rerank-multilingual-v3.0', 'rerank-v3.0', 'rerank-v3.5',
              'rerank-english-v3.0']:
    try:
        r = httpx.post('https://api.cohere.com/v1/rerank', headers=H,
            json={'model': model, 'query': '什么是向量数据库',
                  'documents': ['向量数据库存储向量数据用于语义检索',
                                '今天天气很好适合出门'],
                  'top_n': 1}, timeout=15)
        ok = 'OK' if r.status_code == 200 else 'FAIL'
        body = r.text[:120]
        print(f'{ok} {model}: {r.status_code} {body}')
    except Exception as e:
        print(f'FAIL {model}: err {e}')
