"""B 轮1 阶段3：从本项目 KB17 导出 110 docs 原文 + 导入 LightRAG + 轮询等索引。"""
import requests, json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
LR = 'http://localhost:9621'
KB = 17

# 1. 登录
tok = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {tok}'}
print(f"[login] OK")

# 2. 拿 KB17 doc 列表（分页全拿）
docs = []
page = 1
while True:
    r = requests.get(B + '/api/documents', params={'kb_id': KB, 'page': page, 'page_size': 200}, headers=H, timeout=15)
    data = r.json()
    items = data.get('items') or data.get('documents') or data.get('data') or data.get('list') or []
    if not items:
        # 可能直接是 list
        if isinstance(data, list):
            items = data
    docs.extend(items)
    total = data.get('total', len(docs))
    print(f"[list] page={page} got={len(items)} cumulative={len(docs)} total_field={total} keys={list(data.keys())[:5]}")
    if len(items) < 200 or len(docs) >= total:
        break
    page += 1
    if page > 10:
        break

print(f"[list] KB{KB} docs total: {len(docs)}")
if docs:
    print(f"[list] first doc keys: {list(docs[0].keys())}")

# 3. 拿每个 doc 的 content（preview 端点）
texts = []
fail = 0
for i, d in enumerate(docs):
    file_id = d.get('file_id') or d.get('id') or d.get('doc_id')
    if not file_id:
        continue
    try:
        r = requests.get(B + f'/api/documents/{file_id}/preview', headers=H, timeout=20)
        if r.status_code == 200:
            body = r.json() if 'json' in r.headers.get('content-type', '') else {}
            content = (body.get('content') or body.get('text') or body.get('markdown') or
                       body.get('data') or body.get('preview') or body.get('html') or '')
            if not content and isinstance(body, str):
                content = body
            if not content:
                # 兼容：preview 可能直接返回字符串
                content = r.text if r.text and len(r.text) > 50 else ''
            if content:
                texts.append({'text': str(content)[:50000], 'metadata': {'doc_id': str(file_id), 'kb_id': KB, 'source': 'ragflow-kb17'}})
            else:
                fail += 1
                if fail <= 2:
                    print(f"[preview] doc {file_id} no content, body keys={list(body.keys()) if isinstance(body,dict) else type(body).__name__}, raw[:200]={r.text[:200]}")
        else:
            fail += 1
            if fail <= 2:
                print(f"[preview] doc {file_id} HTTP {r.status_code}")
    except Exception as e:
        fail += 1
        if fail <= 2:
            print(f"[preview] doc {file_id} err: {e}")
    if (i + 1) % 20 == 0:
        print(f"[preview] {i+1}/{len(docs)} done, texts={len(texts)}")

print(f"[preview] texts with content: {len(texts)}, fail: {fail}")
if not texts:
    print("[FATAL] no content extracted, abort")
    sys.exit(1)

# 保存导出结果
json.dump(texts, open('work/lightrag-vs/kb17_docs.json', 'w', encoding='utf-8'), ensure_ascii=False)
print(f"[save] work/lightrag-vs/kb17_docs.json ({len(texts)} docs)")

# 4. 导入 LightRAG (POST /documents/texts)
print(f"[import] posting {len(texts)} texts to LightRAG...")
r = requests.post(LR + '/documents/texts', json={'texts': texts}, timeout=60)
print(f"[import] HTTP {r.status_code}, resp[:300]: {r.text[:300]}")
if r.status_code not in (200, 201, 202):
    print(f"[FATAL] import failed: {r.text[:500]}")
    sys.exit(1)

resp = r.json()
# track_id 可能在多字段
track_id = resp.get('track_id') or resp.get('task_id') or resp.get('id') or (resp[0].get('track_id') if isinstance(resp, list) and resp else None)
print(f"[import] track_id: {track_id}, full resp keys: {list(resp.keys()) if isinstance(resp,dict) else type(resp).__name__}")

# 5. 轮询等索引完成（最多 25 分钟）
if track_id:
    for i in range(150):
        time.sleep(10)
        try:
            r = requests.get(LR + f'/documents/track_status/{track_id}', timeout=10)
            st = r.json()
            status = st.get('status') or st.get('processing_status') or st.get('state')
            processed = st.get('processed_count') or st.get('processed') or st.get('completed') or 0
            total = st.get('total_count') or st.get('total') or len(texts)
            print(f"[{i*10}s] status={status} processed={processed}/{total} pipeline_busy={st.get('pipeline_busy')}")
            if status in ('completed', 'done', 'success', 'finished'):
                print("[INDEX] DONE")
                break
            if status in ('failed', 'error'):
                print(f"[INDEX] FAILED: {st}")
                break
        except Exception as e:
            print(f"[poll] err: {e}")
    else:
        print("[INDEX] TIMEOUT 25min, check health pipeline_busy")
else:
    print("[import] no track_id, check LightRAG health pipeline_busy")

# 最终 health
r = requests.get(LR + '/health', timeout=5)
h = r.json()
print(f"[final] health status={h.get('status')} pipeline_busy={h.get('pipeline_busy')} pipeline_active={h.get('pipeline_active')}")
