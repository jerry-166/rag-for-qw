"""Fill LightRAG 测试集：读 kb17_supplement question → 调 LightRAG /query(naive/hybrid) → 拿 answer+contexts → 写 kb17_lightrag.json
每条样本生成 2 个 LightRAG answer（naive + hybrid），分别存为两个测试集：
  kb17_lightrag_naive（LightRAG naive 模式）
  kb17_lightrag_hybrid（LightRAG hybrid 模式）
共享同一套 question + ground_truth（来自 supplement）
"""
import requests, json, os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LR = 'http://localhost:9621'
TESTSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets'))

# 读 supplement 源
src_path = os.path.join(TESTSET_DIR, 'kb17_supplement.json')
src = json.load(open(src_path, encoding='utf-8'))
src_samples = src.get('samples', [])
print(f"source samples: {len(src_samples)}")

def query_lightrag(q, mode, top_k=10):
    """调 LightRAG /query，返回 (answer, contexts)"""
    try:
        r = requests.post(f"{LR}/query",
            json={"query": q, "mode": mode, "top_k": top_k},
            timeout=120)
        data = r.json()
        answer = data.get("response", "")
        refs = data.get("references", [])
        contexts = [ref.get("content", "") for ref in refs if ref.get("content")]
        return answer, contexts
    except Exception as e:
        print(f"  err: {str(e)[:80]}")
        return "", []

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
        time.sleep(1)

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
