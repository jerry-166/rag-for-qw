"""对 KB17 140 docs 调 generate（抽 entity 写 PG）+ import（同步 entity_vectors 到 Milvus）。
修了 processing.py noop 条件后，KB17 enhancers=["entity"] 会真正抽实体。"""
import requests, json, time, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
B = 'http://localhost:8003'
tok = requests.post(B + '/api/auth/login', data={'username':'loadtester','password':'Loadtest#123'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {tok}'}

# 拿 KB17 file_id 列表
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

# 1. generate（抽 entity 写 PG entity/entity_relation）
print(f"[generate] 开始对 {len(file_ids)} docs 抽实体...", flush=True)
gen_ok = 0; gen_fail = 0
for i, fid in enumerate(file_ids):
    try:
        r = requests.post(B + f'/api/process/generate/{fid}', headers=H, timeout=600)
        if r.status_code == 200:
            gen_ok += 1
        else:
            gen_fail += 1
            if gen_fail <= 5: print(f"  [gen] {fid} fail: {r.status_code} {r.text[:150]}", flush=True)
    except Exception as e:
        gen_fail += 1
        if gen_fail <= 5: print(f"  [gen] {fid} err: {e}", flush=True)
    if (i+1) % 10 == 0: print(f"[generate] {i+1}/{len(file_ids)} ok={gen_ok} fail={gen_fail}", flush=True)
print(f"[generate] DONE: ok={gen_ok} fail={gen_fail}", flush=True)

# 2. import（同步 entity_vectors 到 Milvus）
print(f"[import] 开始对 {len(file_ids)} docs 同步 entity_vectors...", flush=True)
imp_ok = 0; imp_fail = 0
for i, fid in enumerate(file_ids):
    try:
        r = requests.post(B + f'/api/process/import/{fid}', headers=H, timeout=600)
        if r.status_code == 200:
            imp_ok += 1
        else:
            imp_fail += 1
            if imp_fail <= 5: print(f"  [imp] {fid} fail: {r.status_code} {r.text[:150]}", flush=True)
    except Exception as e:
        imp_fail += 1
        if imp_fail <= 5: print(f"  [imp] {fid} err: {e}", flush=True)
    if (i+1) % 10 == 0: print(f"[import] {i+1}/{len(file_ids)} ok={imp_ok} fail={imp_fail}", flush=True)
print(f"[import] DONE: ok={imp_ok} fail={imp_fail}", flush=True)

# 3. 查 PG entity 数
sys.path.insert(0, os.path.abspath('backend'))
from config import settings
import psycopg2
conn = psycopg2.connect(host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT, user=settings.POSTGRES_USER, password=settings.POSTGRES_PASSWORD, dbname=settings.POSTGRES_DB)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM entity WHERE kb_id = 17")
ent = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM entity_relation WHERE kb_id = 17")
rel = cur.fetchone()[0]
print(f"[final] KB17 PG entities={ent} entity_relations={rel}", flush=True)
conn.close()
print("[ALL DONE]", flush=True)
