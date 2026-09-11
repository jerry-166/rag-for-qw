import requests, sys
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
h = requests.get('http://localhost:9621/health', timeout=5).json()
print(f"pipeline_busy={h.get('pipeline_busy')} active={h.get('pipeline_active')} pending={h.get('pipeline_pending_enqueues')}")
eq = h.get('embedding_queue_status', {})
print(f"embedding: submitted={eq.get('submitted_total')} completed={eq.get('completed_total')} failed={eq.get('failed_total')} running={eq.get('running')}")
exq = h.get('llm_queue_status', {}).get('extract', {})
print(f"extract LLM: submitted={exq.get('submitted_total')} completed={exq.get('completed_total')} running={exq.get('running')}")
t = requests.get('http://localhost:9621/documents/track_status/insert_20260901_174454_20147b62', timeout=5).json()
print(f"track total_count={t.get('total_count')} status_summary={t.get('status_summary')}")
docs = t.get('documents', [])
c = Counter(d.get('status') for d in docs)
print(f"doc status counts: {dict(c)}")
for d in docs[:2]:
    print(f"  doc {d.get('file_path')}: status={d.get('status')} err={str(d.get('error_msg',''))[:80]}")
