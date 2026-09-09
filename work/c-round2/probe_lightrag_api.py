"""探 LightRAG API：列出所有端点 + workspace 支持"""
import requests, json
LR = 'http://localhost:9621'

# 1. health
print('=== /health ===')
r = requests.get(f'{LR}/health', timeout=5)
print(json.dumps(r.json(), indent=2, ensure_ascii=False) if r.status_code == 200 else f'{r.status_code} {r.text[:200]}')

print('\n=== /openapi.json (paths) ===')
r = requests.get(f'{LR}/openapi.json', timeout=5)
if r.status_code == 200:
    spec = r.json()
    paths = spec.get('paths', {})
    for p, methods in sorted(paths.items()):
        for m in methods:
            if m in ('get', 'post', 'delete', 'put'):
                summary = methods[m].get('summary', '')
                print(f'  {m.upper():6} {p:40} {summary}')
else:
    print(f'{r.status_code}')

# 3. 查 /documents/texts 是否支持 workspace 参数
print('\n=== /documents/texts spec ===')
r = requests.get(f'{LR}/openapi.json', timeout=5)
if r.status_code == 200:
    spec = r.json()
    for p in ['/documents/texts', '/query', '/query/data']:
        if p in spec.get('paths', {}):
            for m, info in spec['paths'][p].items():
                if m == 'post':
                    body = info.get('requestBody', {})
                    schema = body.get('content', {}).get('application/json', {}).get('schema', {})
                    ref = schema.get('$ref', '')
                    if ref:
                        # 跟随 $ref
                        ref_name = ref.split('/')[-1]
                        comp = spec.get('components', {}).get('schemas', {}).get(ref_name, {})
                        props = comp.get('properties', {})
                        print(f'\n{p} body schema ({ref_name}):')
                        for prop, info2 in props.items():
                            print(f'  {prop}: {info2.get("type", "")} {info2.get("default", "")}')
