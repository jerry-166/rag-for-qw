"""加载 kb17_docs.json + 转 texts/file_sources + 导入 LightRAG + 轮询等索引。"""
import requests, json, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
LR = 'http://localhost:9621'

texts_obj = json.load(open('work/lightrag-vs/kb17_docs.json', encoding='utf-8'))
texts = [t['text'] if isinstance(t, dict) else str(t) for t in texts_obj]
file_sources = [str(t.get('metadata', {}).get('doc_id', f'kb17_doc_{i}')) if isinstance(t, dict) else f'kb17_doc_{i}' for i, t in enumerate(texts_obj)]
print(f"[load] {len(texts)} texts, {len(file_sources)} file_sources, sample text[:60]={texts[0][:60]!r}, source[0]={file_sources[0]}")

print(f"[import] posting to LightRAG /documents/texts...")
r = requests.post(LR + '/documents/texts', json={'texts': texts, 'file_sources': file_sources}, timeout=120)
print(f"[import] HTTP {r.status_code}, resp[:300]={r.text[:300]}")
if r.status_code not in (200, 201, 202):
    print(f"[FATAL] import failed: {r.text[:500]}")
    sys.exit(1)

resp = r.json()
track_id = resp.get('track_id') or resp.get('task_id') or (resp[0].get('track_id') if isinstance(resp, list) and resp else None)
print(f"[import] track_id={track_id}, resp keys={list(resp.keys()) if isinstance(resp,dict) else type(resp).__name__}")

if track_id:
    for i in range(360):  # 最多 60 分钟
        time.sleep(10)
        try:
            r = requests.get(LR + f'/documents/track_status/{track_id}', timeout=10)
            st = r.json()
            status = st.get('status') or st.get('processing_status') or st.get('state')
            processed = st.get('processed_count') or st.get('processed') or st.get('completed') or 0
            total = st.get('total_count') or st.get('total') or len(texts)
            print(f"[{i*10}s] status={status} processed={processed}/{total} busy={st.get('pipeline_busy')}")
            if status in ('completed', 'done', 'success', 'finished'):
                print("[INDEX] DONE")
                break
            if status in ('failed', 'error'):
                print(f"[INDEX] FAILED: {st}")
                break
        except Exception as e:
            print(f"[poll] err: {e}")
    else:
        print("[INDEX] TIMEOUT 60min, check health pipeline_busy")

r = requests.get(LR + '/health', timeout=5)
h = r.json()
print(f"[final] health pipeline_busy={h.get('pipeline_busy')} pipeline_active={h.get('pipeline_active')}")
