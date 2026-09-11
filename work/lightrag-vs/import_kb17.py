"""将 kb17_docs.json 导入 LightRAG。
POST /documents/texts 批量导入，texts 是 list[str]，file_sources 是 list[str]。
轮询 /health 的 pipeline_busy 直到 false。
"""
import json
import time
import requests

LR = "http://localhost:9621"
INPUT = "kb17_docs.json"

# 加载文档
with open(INPUT, "r", encoding="utf-8") as f:
    docs = json.load(f)
print(f"加载 {len(docs)} 篇文档")

# LightRAG /documents/texts 端点接受 {texts: ["text1", "text2", ...], file_sources: ["src1", "src2", ...]}
# 分批导入，每批 5 篇（避免单次请求太大）
BATCH = 5
total_start = time.time()

for i in range(0, len(docs), BATCH):
    batch = docs[i:i + BATCH]
    texts = [d["text"] for d in batch]
    file_sources = [d.get("metadata", {}).get("filename", f"doc_{i+j}") for j, d in enumerate(batch)]
    
    body = {"texts": texts, "file_sources": file_sources}
    try:
        r = requests.post(f"{LR}/documents/texts", json=body, timeout=120)
        if r.status_code in (200, 202):
            print(f"  Batch {i//BATCH + 1}/{(len(docs)+BATCH-1)//BATCH}: {len(batch)} docs, status={r.status_code}")
        else:
            print(f"  Batch {i//BATCH + 1}: FAILED status={r.status_code}, body={r.text[:300]}")
    except Exception as e:
        print(f"  Batch {i//BATCH + 1}: EXCEPTION {e}")

print(f"\n导入请求发送完成，耗时 {time.time() - total_start:.1f}s")

# 轮询 health 直到 pipeline_busy=false
print("\n开始轮询 pipeline 状态...")
for attempt in range(1000):
    time.sleep(10)
    try:
        r = requests.get(f"{LR}/health", timeout=30)
        data = r.json()
        busy = data.get("pipeline_busy", None)
        active = data.get("pipeline_active", None)
        print(f"  [{attempt+1}] pipeline_busy={busy}, pipeline_active={active}")
        if busy is False and active is False:
            print("  Pipeline 空闲！索引完成。")
            break
    except Exception as e:
        print(f"  [{attempt+1}] health check error: {e}")
else:
    print("  超时（1000 次 × 10s），pipeline 仍在忙")

print(f"\n总耗时 {time.time() - total_start:.1f}s")
