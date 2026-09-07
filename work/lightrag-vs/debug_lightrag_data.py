"""调试 LightRAG /query/data 返回结构"""
import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
LR = 'http://localhost:9621'
r = requests.post(f'{LR}/query/data',
    json={'query': '向量数据库的核心原理', 'mode': 'naive', 'chunk_top_k': 5},
    timeout=60)
j = r.json()
print('top-level keys:', list(j.keys()))
chunks = j.get('chunks', [])
print(f'chunks count: {len(chunks)}')
if chunks:
    print('first chunk keys:', list(chunks[0].keys()))
    print('first chunk:', json.dumps(chunks[0], ensure_ascii=False)[:400])
refs = j.get('references', [])
print(f'references count: {len(refs)}')
if refs:
    print('first ref:', json.dumps(refs[0], ensure_ascii=False)[:200])
