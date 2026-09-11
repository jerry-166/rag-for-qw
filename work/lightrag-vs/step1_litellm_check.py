"""Step 1: 验证 litellm up + qwen3.7-flash chat + text-embedding-v4 dim=1536 可用"""
import requests, json, sys

BASE = "http://localhost:4000"
KEY = "sk-jerry166"
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

# 1. models 列表
try:
    r = requests.get(f"{BASE}/v1/models", headers=H, timeout=15)
    r.raise_for_status()
    names = [m["id"] for m in r.json().get("data", [])]
    print(f"[models] count={len(names)}")
    qwen = [n for n in names if "qwen" in n.lower()]
    v4 = [n for n in names if "v4" in n.lower() or "embedding" in n.lower()]
    print(f"  qwen models: {qwen}")
    print(f"  embedding models: {v4}")
except Exception as e:
    print(f"[models] FAIL: {e}")
    sys.exit(1)

# 2. chat qwen3.7-flash
try:
    r = requests.post(f"{BASE}/v1/chat/completions", headers=H, timeout=30,
        json={"model": "qwen3.7-flash", "messages": [{"role": "user", "content": "说'你好'两个字"}], "max_tokens": 20})
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]["content"]
    print(f"[chat qwen3.7-flash] OK: {msg[:50]}")
except Exception as e:
    print(f"[chat qwen3.7-flash] FAIL: {str(e)[:200]}")
    if hasattr(r, 'text'):
        print(f"  resp: {r.text[:300]}")

# 3. embedding text-embedding-v4 dim=1536
try:
    r = requests.post(f"{BASE}/v1/embeddings", headers=H, timeout=30,
        json={"model": "text-embedding-v4", "input": ["测试向量维度"]})
    r.raise_for_status()
    data = r.json()
    dim = len(data["data"][0]["embedding"])
    print(f"[embedding text-embedding-v4] OK: dim={dim}")
    assert dim == 1024, f"期望 1024, 实际 {dim}"
    print("[step1] ALL PASS")
except Exception as e:
    print(f"[embedding text-embedding-v4] FAIL: {str(e)[:200]}")
    if hasattr(r, 'text'):
        print(f"  resp: {r.text[:500]}")
    sys.exit(1)
