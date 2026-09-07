"""本项目 5 模式检索填测试集（不依赖 LLM judge）
复用 kb17_supplement 的 answer（native rerank关 的 agent answer）
每模式只换 contexts（调对应检索端点）

5 模式：
  1. native rerank关  → POST /api/milvus/query use_rerank=false retrieval_mode=native
  2. native rerank开  → POST /api/milvus/query use_rerank=true retrieval_mode=native
  3. advanced         → POST /api/milvus/query use_rerank=true retrieval_mode=advanced
  4. hybrid_vec       → POST /api/hybrid/search use_rerank=true retrieval_mode=hybrid
  5. keyword          → POST /api/elasticsearch/search use_rerank=true

产出 5 个测试集：
  kb17_ours_native_rerank_off
  kb17_ours_native_rerank_on
  kb17_ours_advanced
  kb17_ours_hybrid_vec
  kb17_ours_keyword
"""
import requests, json, os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
TESTSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets'))

TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

# 读 supplement 源（复用 question + ground_truth + answer）
src = json.load(open(os.path.join(TESTSET_DIR, 'kb17_supplement.json'), encoding='utf-8'))
src_samples = src.get('samples', [])
print(f"source samples: {len(src_samples)}")

MODES = [
    ("native_rerank_off", "milvus/query", {"retrieval_mode": "native", "use_rerank": False}),
    ("native_rerank_on",  "milvus/query", {"retrieval_mode": "native", "use_rerank": True}),
    ("advanced",         "milvus/query", {"retrieval_mode": "advanced", "use_rerank": True}),
    ("hybrid_vec",       "hybrid/search", {"retrieval_mode": "hybrid", "use_rerank": True}),
    ("keyword",          "elasticsearch/search", {"retrieval_mode": "native", "use_rerank": True}),
]

for mode_name, endpoint, extra in MODES:
    samples = []
    for i, s in enumerate(src_samples):
        q = s["question"]
        try:
            r = requests.post(f"{B}/api/{endpoint}",
                json={"query": q, "limit": 10, "knowledge_base_id": 17, **extra},
                headers=H, timeout=30)
            results = r.json().get("results", [])
            contexts = [c.get("content", c.get("chunk_text", ""))
                        for c in results
                        if c.get("content", c.get("chunk_text", ""))]
        except Exception as e:
            print(f"  [{mode_name} {i+1}] err: {str(e)[:60]}")
            contexts = []

        samples.append({
            "question": q,
            "answer": s.get("answer", ""),
            "contexts": contexts,
            "ground_truth": s["ground_truth"],
            "status": "approved",
            "metadata": {"kb_id": 17, "source": "ours", "mode": mode_name, "tags": ["技术"]}
        })
        print(f"[{mode_name} {i+1}/{len(src_samples)}] {q[:30]}: ctx={len(contexts)}")
        time.sleep(0.5)

    out_path = os.path.join(TESTSET_DIR, f"kb17_ours_{mode_name}.json")
    dataset = {
        "name": f"kb17_ours_{mode_name}",
        "created_at": time.strftime('%Y-%m-%dT%H:%M:%S'),
        "count": len(samples),
        "samples": samples,
    }
    json.dump(dataset, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    complete = sum(1 for s in samples if s["answer"] and s["contexts"])
    print(f"\n[done] {mode_name}: {len(samples)} samples, complete={complete}, saved {out_path}\n")
