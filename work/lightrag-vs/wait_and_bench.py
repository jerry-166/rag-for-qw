"""后台任务：等 LightRAG 索引完成（pipeline_busy 连续 false 30s）+ 跑 bench_lightrag.py + 存结果。"""
import requests, time, subprocess, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
LR = 'http://localhost:9621'
TRACK = 'insert_20260901_174454_20147b62'

print("[wait] 等 LightRAG 索引完成 (pipeline_busy 连续 false 30s)...", flush=True)
false_count = 0
for i in range(360):  # 60 min max
    time.sleep(10)
    try:
        h = requests.get(LR + '/health', timeout=5).json()
        busy = h.get('pipeline_busy')
        eq = h.get('embedding_queue_status', {})
        emb_done = eq.get('completed_total', 0)
        emb_sub = eq.get('submitted_total', 0)
        t = requests.get(LR + f'/documents/track_status/{TRACK}', timeout=5).json()
        summ = t.get('status_summary', {})
        processed = summ.get('DocStatus.PROCESSED', 0)
        failed = summ.get('DocStatus.FAILED', 0)
        print(f"[{i*10}s] busy={busy} emb={emb_done}/{emb_sub} processed={processed}/140 failed={failed}", flush=True)
        if busy is False:
            false_count += 1
            if false_count >= 3:  # 连续 3 次 false (30s) = 真完成
                print("[wait] 索引完成（pipeline_busy 连续 false 30s）", flush=True)
                break
        else:
            false_count = 0
        if failed > 0:
            print(f"[warn] {failed} docs failed, 继续（可能仍可跑 naive 压测）", flush=True)
    except Exception as e:
        print(f"[wait] err: {e}", flush=True)
else:
    print("[wait] TIMEOUT 60min，强制跑压测看能跑几组", flush=True)

# 跑压测
print("[bench] 跑 bench_lightrag.py...", flush=True)
try:
    result = subprocess.run(['backend/.venv/Scripts/python.exe', 'work/lightrag-vs/bench_lightrag.py'],
                            capture_output=True, text=True, timeout=1800, encoding='utf-8', errors='replace')
    print(result.stdout, flush=True)
    if result.stderr:
        print("STDERR:", result.stderr[:1000], flush=True)
    print("[done] bench 完成，结果在 work/lightrag-vs/result_round1.json", flush=True)
except Exception as e:
    print(f"[bench] err: {e}", flush=True)
