"""检查 CRUD-RAG split_merged.json 结构"""
import json, os, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

P = r'd:\workspace\CRUD_RAG\data\crud_split\split_merged.json'
print(f'file size: {os.path.getsize(P)/1024:.1f} KB')
with open(P, encoding='utf-8') as f:
    d = json.load(f)
print(f'top type: {type(d).__name__}')
if isinstance(d, dict):
    print(f'top keys: {list(d.keys())[:20]}')
    for k, v in list(d.items())[:5]:
        print(f'  {k}: type={type(v).__name__} len={len(v) if hasattr(v, "__len__") else "-"}')
        if isinstance(v, list) and v:
            print(f'    item0 type={type(v[0]).__name__}')
            if isinstance(v[0], dict):
                print(f'    item0 keys={list(v[0].keys())}')
                print(f'    item0 sample:')
                for kk, vv in list(v[0].items())[:10]:
                    s = str(vv)[:200]
                    print(f'      {kk}: {s}')
        elif isinstance(v, dict):
            print(f'    subkeys={list(v.keys())[:10]}')
elif isinstance(d, list):
    print(f'len: {len(d)}')
    print(f'item0 type: {type(d[0]).__name__}')
    if isinstance(d[0], dict):
        print(f'item0 keys: {list(d[0].keys())}')
        for k, v in list(d[0].items())[:15]:
            s = str(v)[:300]
            print(f'  {k}: {s}')
        print('\n--- item1 ---')
        if len(d) > 1 and isinstance(d[1], dict):
            for k, v in list(d[1].items())[:15]:
                s = str(v)[:300]
                print(f'  {k}: {s}')
