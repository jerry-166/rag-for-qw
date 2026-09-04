import requests, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
tok = requests.post('http://localhost:8003/api/auth/login', data={'username':'admin','password':'admin'}, timeout=10).json()['access_token']
h = {'Authorization': f'Bearer {tok}'}
print(f"token OK: {tok[:15]}...")
paths = ['/api/documents?kb_id=17&page=1&page_size=3', '/api/documents?page=1&page_size=3', '/api/kb/17/documents', '/api/knowledge-bases/17/documents', '/api/documents/list?kb_id=17']
for p in paths:
    try:
        r = requests.get('http://localhost:8003'+p, headers=h, timeout=10)
        print(f"{p} -> {r.status_code} body[:250]={r.text[:250]}")
    except Exception as e:
        print(f"{p} ERR {e}")
r = requests.get('http://localhost:8003/openapi.json', timeout=10)
spec = r.json()
doc_paths = [p for p in spec.get('paths',{}) if 'document' in p.lower() or 'doc' in p.lower() or 'file' in p.lower()]
print(f"\ndoc/file paths in openapi: {doc_paths}")
