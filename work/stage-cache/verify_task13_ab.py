"""Task 13 A/B 验收脚本：缓存开/关的延迟与命中率对比（文档 08 §4.1）

用法（在 backend 目录下，venv 已激活）：
  python ..\work\stage-cache\verify_task13_ab.py --user admin --pass <密码> --kb-id <KB> --query "查询文本" --rounds 8

流程：
  1. 登录拿 token
  2. CACHE_BACKEND=off 基线：跑 N 次同 query 检索（限速避免 429），记延迟 + cached 标志
  3. CACHE_BACKEND=memory（或 redis）：前 2 次预热，后 N 次测命中与延迟
  4. 输出对比表 + 落 JSON

注：完整 5 个权限安全用例需多用户+分享操作，见 stage-cache-report.md 手动用例清单。
"""
import argparse, json, time, sys, urllib.request, urllib.error

BASE = "http://127.0.0.1:8003"


def api(path, method="GET", token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode(errors="replace")}


def login(user, pwd):
    # OAuth2PasswordRequestForm：form-data
    import urllib.parse
    data = urllib.parse.urlencode({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(f"{BASE}/api/auth/login", data=data, method="POST",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def set_backend(token, mode):
    return api("/api/settings", "PUT", token, {"key": "CACHE_BACKEND", "value": mode})


def search(token, query, kb_id, use_rerank=False):
    body = {"query": query, "knowledge_base_id": kb_id, "use_rerank": use_rerank}
    t0 = time.time()
    r = api("/api/search/milvus/query", "POST", token, body)
    dt = time.time() - t0
    return dt, r.get("cached", False), r.get("_http_error"), r.get("results")


def run_round(token, query, kb_id, n, label, rerank=False):
    print(f"\n=== {label}（{n} 次）===")
    latencies, hits = [], 0
    for i in range(n):
        dt, cached, err, _ = search(token, query, kb_id, rerank)
        if err:
            print(f"  #{i+1} ERROR {err}")
            time.sleep(2)
            continue
        latencies.append(dt)
        if cached:
            hits += 1
        print(f"  #{i+1} {dt:.2f}s {'cached' if cached else 'miss'}")
        time.sleep(0.5)  # 限速防 429
    latencies.sort()
    p50 = latencies[len(latencies)//2] if latencies else None
    p95 = latencies[int(len(latencies)*0.95)] if len(latencies) > 1 else (latencies[0] if latencies else None)
    hit_rate = hits / n if n else 0
    print(f"  → p50={p50:.2f}s p95={p95:.2f}s 命中率={hit_rate*100:.0f}% ({hits}/{n})")
    return {"label": label, "n": n, "p50": p50, "p95": p95, "hit_rate": hit_rate, "hits": hits, "latencies": latencies}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--pass", dest="password", required=True)
    ap.add_argument("--kb-id", type=int, required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--rerank", action="store_true")
    args = ap.parse_args()

    token = login(args.user, args.password)
    print(f"登录成功，token len={len(token)}")

    results = []
    # 基线：off
    set_backend(token, "off")
    results.append(run_round(token, args.query, args.kb_id, args.rounds, "基线(CACHE_BACKEND=off)", args.rerank))

    # 缓存：memory（Redis 未起时降级，先 memory）
    set_backend(token, "memory")
    # 预热 2 次
    run_round(token, args.query, args.kb_id, 2, "预热(memory)", args.rerank)
    results.append(run_round(token, args.query, args.kb_id, args.rounds, "测量(CACHE_BACKEND=memory)", args.rerank))

    # 汇总
    print("\n========== A/B 对比 ==========")
    for r in results:
        print(f"{r['label']}: p50={r['p50']:.2f}s p95={r['p95']:.2f}s 命中率={r['hit_rate']*100:.0f}%")

    if len(results) >= 2:
        base, cached = results[0], results[1]
        if base["p50"] and cached["p50"]:
            speedup = base["p50"] / cached["p50"]
            print(f"\n缓存命中 p50 加速: {speedup:.1f}x（{base['p50']:.2f}s → {cached['p50']:.2f}s）")

    out = {"args": vars(args), "results": results}
    with open("verify_task13_ab_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n结果已落 verify_task13_ab_result.json")


if __name__ == "__main__":
    main()
