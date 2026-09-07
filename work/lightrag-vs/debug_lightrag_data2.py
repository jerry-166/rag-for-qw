"""调试 LightRAG /query/data 返回结构 v2 - 看 data 字段"""
import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
LR = 'http://localhost:9621'
r = requests.post(f'{LR}/query/data',
    json={'query': '向量数据库的核心原理', 'mode': 'naive', 'chunk_top_k': 5},
    timeout=60)
j = r.json()
print('top-level keys:', list(j.keys()))
data = j.get('data', {})
print('data keys:', list(data.keys()) if isinstance(data, dict) else type(data).__name__)
if isinstance(data, dict):
    chunks = data.get('chunks', [])
    print(f'data.chunks count: {len(chunks)}')
    if chunks:
        print('first chunk keys:', list(chunks[0].keys()))
        print('first chunk:', json.dumps(chunks[0], ensure_ascii=False)[:400])
    refs = data.get('references', [])
    print(f'data.references count: {len(refs)}')
    if refs:
        print('first ref:', json.dumps(refs[0], ensure_ascii=False)[:200])
