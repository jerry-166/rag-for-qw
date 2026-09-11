"""查 backend build + LightRAG pipeline 进度"""
import os, sys, requests, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
LR = 'http://localhost:9621'

# 后端 KB 65 + 66
t = requests.post(B+'/api/auth/login', data={'username':'loadtester','password':'Loadtest#123'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {t}'}

for kb_id, name in [(65, 'CRUD-RAG'), (66, 'NFCorpus')]:
    try:
        r = requests.get(f'{B}/api/documents?kb_id={kb_id}&page_size=1', headers=H, timeout=10)
        d = r.json()
        total = d.get('total', 0)
        if d.get('documents'):
            latest = d['documents'][0]
            print(f'KB {kb_id} ({name}): total={total} latest={latest["filename"]} status={latest["status"]}')
        else:
            print(f'KB {kb_id} ({name}): total={total}')
    except Exception as e:
        print(f'KB {kb_id} err: {e}')

# LightRAG /health + pipeline status
try:
    r = requests.get(f'{LR}/health', timeout=5)
    j = r.json()
    print(f'\nLightRAG: status={j.get("status")} busy={j.get("pipeline_busy")} active={j.get("pipeline_active")}')
except Exception as e:
    print(f'LightRAG err: {e}')

# 文件 mtime
for f in ['build_kb_ours.log', 'reset_lightrag_crud.log', 'lightrag_c2_crud.log', 'lightrag_c2_crud.err.log']:
    p = os.path.join(r'd:\workspace\rag-for-qw\work\c-round2', f)
    if os.path.exists(p):
        import time
        mtime = os.path.getmtime(p)
        size = os.path.getsize(p)
        print(f'  {f}: size={size} lastWrite={time.strftime("%H:%M:%S", time.localtime(mtime))}')
    else:
        print(f'  {f}: not found')
