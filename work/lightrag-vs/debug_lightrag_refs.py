"""调试 LightRAG /query 返回结构，看 references 字段实际格式"""
import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
LR = 'http://localhost:9621'
r = requests.post(f'{LR}/query',
    json={'query': '向量数据库的核心原理', 'mode': 'naive', 'top_k': 5},
    timeout=60)
j = r.json()
print('top-level keys:', list(j.keys()))
print('response[:200]:', j.get('response', '')[:200])
refs = j.get('references', [])
print(f'\nreferences count: {len(refs)}')
if refs:
    print('first ref type:', type(refs[0]).__name__)
    print('first ref keys:', list(refs[0].keys()) if isinstance(refs[0], dict) else 'N/A')
    print('first ref:', json.dumps(refs[0], ensure_ascii=False)[:500])
