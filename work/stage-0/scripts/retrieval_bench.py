# -*- coding: utf-8 -*-
"""检索质量抽样基线: 20 固定查询 x 3 模式, 调用 /api/milvus/query + /api/hybrid/search"""
import time, json, urllib.request, sys

BASE = "http://localhost:8003"
QUERIES = [
    "Claude Code 是什么",
    "如何安装 Claude Code CLI",
    "CLAUDE.md 文件的作用是什么",
    "子 agent 是怎么工作的",
    "工具权限系统如何配置",
    "MCP 协议在 Claude Code 中如何使用",
    "上下文窗口管理机制",
    "如何查看对话的历史记录",
    "/hooks 功能可以做什么",
    "斜杠命令有哪些",
    "如何用 Claude Code 进行代码重构",
    "API 费用如何计算",
    "模型上下文协议服务器配置",
    "如何调试前端代码",
    "git 工作流最佳实践",
    "如何写系统提示词",
    "内存管理和 token 优化",
    "多模态图片输入支持",
    "安全沙箱机制介绍",
    "团队协作中如何共享配置",
]

def login():
    import urllib.parse
    data = urllib.parse.urlencode({"username": "admin", "password": "admin123"}).encode()
    req = urllib.request.Request(BASE + "/api/auth/login", data=data)
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return r.get("access_token") or r.get("token")
    except Exception as e:
        print("login failed:", e)
        # try alt passwords
        for pw in ("admin", "123456", "password"):
            data = urllib.parse.urlencode({"username": "admin", "password": pw}).encode()
            req = urllib.request.Request(BASE + "/api/auth/login", data=data)
            try:
                r = json.loads(urllib.request.urlopen(req, timeout=10).read())
                return r.get("access_token") or r.get("token")
            except Exception as e2:
                print(f"  pw={pw} failed: {e2}")
    return None

def post(path, token, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=120)
    ms = (time.time() - t0) * 1000
    data = json.loads(resp.read())
    n = len(data.get("results", data.get("data", []))) if isinstance(data, dict) else -1
    return n, round(ms, 1)

token = open("work/stage-0/scripts/token.txt").read().strip()
print("token loaded")

out = []
for mode in ("native", "advanced", "hybrid_vec"):
    for q in QUERIES:
        if mode == "hybrid_vec":
            body = {"query": q, "limit": 10, "retrieval_mode": "hybrid", "use_rerank": True}
        else:
            body = {"query": q, "limit": 10, "retrieval_mode": mode, "use_rerank": True}
        try:
            n, ms = post("/api/milvus/query", token, body)
            rec = {"query": q, "mode": mode, "topk": n, "ms": ms}
        except Exception as e:
            rec = {"query": q, "mode": mode, "error": str(e)}
        print(rec, flush=True)
        out.append(rec)

# true hybrid endpoint (vector + keyword + RRF)
for q in QUERIES:
    body = {"query": q, "limit": 10, "use_rerank": True}
    try:
        n, ms = post("/api/hybrid/search", token, body)
        rec = {"query": q, "mode": "hybrid_endpoint", "topk": n, "ms": ms}
    except Exception as e:
        rec = {"query": q, "mode": "hybrid_endpoint", "error": str(e)}
    print(rec, flush=True)
    out.append(rec)

json.dump(out, open(r"D:\workspace\rag-for-qw\work\stage-0\retrieval_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
# summary
for m in set(r.get("mode") for r in out):
    rs = [r for r in out if r.get("mode") == m]
    ok = [r for r in rs if "ms" in r]
    if ok:
        ms = sorted(r["ms"] for r in ok)
        print(f"SUMMARY {m}: n={len(ok)}/{len(rs)} p50={ms[len(ms)//2]}ms max={ms[-1]}ms min={ms[0]}ms avg={round(sum(ms)/len(ms),1)}ms")
