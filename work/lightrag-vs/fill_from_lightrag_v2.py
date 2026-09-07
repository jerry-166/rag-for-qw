"""Fill LightRAG 测试集 v2：
- /query 拿 answer
- /query/data 拿 chunks（content 字段）
因为 /query 的 references.content 是 null，必须用 /query/data 才能拿到 chunk content。
"""
import requests, json, os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LR = 'http://localhost:9621'
TESTSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets'))

src = json.load(open(os.path.join(TESTSET_DIR, 'kb17_supplement.json'), encoding='utf-8'))
src_samples = src.get('samples', [])
print(f"source samples: {len(src_samples)}")

def query_lightrag(q, mode, top_k=10):
    """调 LightRAG /query 拿 answer + /query/data 拿 chunks"""
    # answer
    try:
        r = requests.post(f"{LR}/query",
            json={"query": q, "mode": mode, "top_k": top_k},
            timeout=120)
        answer = r.json().get("response", "")
    except Exception as e:
        print(f"  /query err: {str(e)[:80]}")
        answer = ""

    # chunks
    try:
        r2 = requests.post(f"{LR}/query/data",
            json={"query": q, "mode": mode, "chunk_top_k": top_k},
            timeout=120)
        data = r2.json().get("data", {})
        chunks = data.get("chunks", [])
        contexts = [c.get("content", "") for c in chunks if c.get("content")]
    except Exception as e:
        print(f"  /query/data err: {str(e)[:80]}")
        contexts = []

    return answer, contexts

for mode in ["naive", "hybrid"]:
    samples = []
    for i, s in enumerate(src_samples):
        q = s["question"]
        answer, contexts = query_lightrag(q, mode)
        samples.append({
            "question": q,
            "answer": answer,
            "contexts": contexts,
            "ground_truth": s["ground_truth"],
            "status": "approved",
            "metadata": {"kb_id": 17, "source": "lightrag", "mode": mode, "tags": ["技术"]}
        })
        print(f"[{mode} {i+1}/{len(src_samples)}] {q[:30]}: ans={len(answer)}c ctx={len(contexts)}")
        time.sleep(0.5)

    out_path = os.path.join(TESTSET_DIR, f"kb17_lightrag_{mode}.json")
    dataset = {
        "name": f"kb17_lightrag_{mode}",
        "created_at": time.strftime('%Y-%m-%dT%H:%M:%S'),
        "count": len(samples),
        "samples": samples,
    }
    json.dump(dataset, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    complete = sum(1 for s in samples if s["answer"] and s["contexts"])
    print(f"\n[done] {mode}: {len(samples)} samples, complete={complete}, saved {out_path}\n")
