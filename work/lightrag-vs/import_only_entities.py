"""补 import：重新登录（新 token）+ token 50min 自动刷新 + 只跑 import 140 docs（同步 entity_vectors 到 Milvus，不 generate）。"""
import requests, sys, time, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'

def login():
    return requests.post(B + '/api/auth/login', data={'username':'loadtester','password':'Loadtest#123'}, timeout=10).json()['access_token']

tok = login()
H = {'Authorization': f'Bearer {tok}'}
print("[login] OK (fresh token)", flush=True)

# 拿 KB17 file_id
docs = []
page = 1
while True:
    r = requests.get(B + '/api/documents', params={'kb_id':17,'page':page,'page_size':200}, headers=H, timeout=15)
    data = r.json()
    items = data.get('documents') or data.get('items') or []
    docs.extend(items)
    if len(items) < 200 or len(docs) >= data.get('total', len(docs)):
        break
    page += 1
    if page > 10: break
file_ids = [str(d.get('file_id') or d.get('id')) for d in docs if d.get('file_id') or d.get('id')]
print(f"[list] KB17 docs: {len(file_ids)}", flush=True)

# 只跑 import（同步 entity_vectors 到 Milvus）
imp_ok = 0; imp_fail = 0
t0 = time.time()
for i, fid in enumerate(file_ids):
    # token 50min 自动刷新（避免上次 60min 过期全 401）
    if time.time() - t0 > 3000:
        tok = login()
        H = {'Authorization': f'Bearer {tok}'}
        t0 = time.time()
        print(f"[refresh] token refreshed at doc {i}", flush=True)
    try:
        r = requests.post(B + f'/api/process/import/{fid}', headers=H, timeout=300)
        if r.status_code == 200:
            imp_ok += 1
        else:
            imp_fail += 1
            if imp_fail <= 5: print(f"  [imp] {fid} fail: {r.status_code} {r.text[:120]}", flush=True)
    except Exception as e:
        imp_fail += 1
        if imp_fail <= 5: print(f"  [imp] {fid} err: {str(e)[:100]}", flush=True)
    if (i+1) % 10 == 0: print(f"[import] {i+1}/{len(file_ids)} ok={imp_ok} fail={imp_fail}", flush=True)
print(f"[import] DONE: ok={imp_ok} fail={imp_fail}", flush=True)

# 查 entity
sys.path.insert(0, os.path.abspath('backend'))
from config import settings
import psycopg2
conn = psycopg2.connect(host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT, user=settings.POSTGRES_USER, password=settings.POSTGRES_PASSWORD, dbname=settings.POSTGRES_DB)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM entity WHERE kb_id = 17")
print(f"[final] KB17 PG entities={cur.fetchone()[0]}", flush=True)
cur.execute("SELECT count(*) FROM entity_relation WHERE kb_id = 17")
print(f"[final] KB17 entity_relations={cur.fetchone()[0]}", flush=True)
conn.close()
print("[IMPORT DONE]", flush=True)
