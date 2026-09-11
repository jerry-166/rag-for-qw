"""调试 LightRAG references content 是否全 null"""
import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
LR = 'http://localhost:9621'
r = requests.post(f'{LR}/query',
    json={'query': '向量数据库的核心原理', 'mode': 'naive', 'top_k': 5},
    timeout=60)
j = r.json()
refs = j.get('references', [])
for i, ref in enumerate(refs):
    c = ref.get('content')
    print(f'ref[{i}] id={ref.get("reference_id")} file={ref.get("file_path")} content_type={type(c).__name__} content_len={len(c) if c else 0}')
