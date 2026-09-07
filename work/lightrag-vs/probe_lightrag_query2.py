"""探查 LightRAG /query 响应格式 - 多 mode"""
import requests, json
for mode in ["naive", "hybrid", "mix", "bypass"]:
    try:
        r = requests.post("http://localhost:9621/query",
            json={"query": "向量数据库的核心原理", "mode": mode, "top_k": 5},
            timeout=60)
        data = r.json()
        resp = data.get("response","")[:100]
        refs = data.get("references",[])
        print(f"mode={mode}: status={r.status_code} resp={resp} refs={len(refs) if isinstance(refs,list) else refs}")
        if refs:
            print(f"  ref keys: {list(refs[0].keys()) if isinstance(refs,list) and refs else 'n/a'}")
    except Exception as e:
        print(f"mode={mode}: err {str(e)[:80]}")
