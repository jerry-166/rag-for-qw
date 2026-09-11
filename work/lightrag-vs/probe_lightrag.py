import requests, sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
spec = requests.get('http://localhost:9621/openapi.json', timeout=10).json()
for s in ['InsertTextsRequest', 'InsertTextRequest']:
    print(f"=== {s} ===")
    print(json.dumps(spec.get('components',{}).get('schemas',{}).get(s, {}), indent=2, ensure_ascii=False)[:2500])
    print()
