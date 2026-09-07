"""探查 LightRAG /query 响应格式"""
import requests, json
r = requests.post("http://localhost:9621/query",
    json={"query": "向量数据库的核心原理", "mode": "naive", "top_k": 3},
    timeout=60)
print("status:", r.status_code)
data = r.json()
print("keys:", list(data.keys()) if isinstance(data, dict) else type(data))
print("sample:", json.dumps(data, ensure_ascii=False)[:800])
