"""E2E 验证辅助：登录 + 常用 API 调用。用法：python e2e.py <cmd> [args...]"""
import json, sys, urllib.request

BASE = "http://127.0.0.1:8003"

def req(method, path, token=None, body=None, raw=None, ctype="application/json"):
    url = BASE + path
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    elif raw is not None:
        data = raw
    r = urllib.request.Request(url, data=data, method=method)
    if body is not None or raw is not None:
        r.add_header("Content-Type", ctype)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, None

def login(u, p):
    import urllib.parse
    data = urllib.parse.urlencode({"username": u, "password": p}).encode()
    s, d = req("POST", "/api/auth/login", raw=data, ctype="application/x-www-form-urlencoded")
    assert s == 200, d
    return d["access_token"], d["user_id"]

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "hybrid":
        tok, _ = login("tester", "test123456")
        for q in ["RRF融合排序是怎么工作的", "Milvus向量数据库的数据组织结构", "私有知识库FAQ蒸馏阈值是多少"]:
            s, d = req("POST", "/api/hybrid/search", tok, {"query": q, "knowledge_base_id": 6, "limit": 3, "use_rerank": False})
            rs = d.get("results", []) if isinstance(d, dict) else []
            print(f"[{s}] {q} -> {len(rs)} 条; top: {rs[0].get('content','')[:60] if rs else d}")
