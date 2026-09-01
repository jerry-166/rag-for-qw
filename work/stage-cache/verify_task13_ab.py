"""Task 13 A/B 验收（双账号版）：admin 切 CACHE_BACKEND，loadtester 跑 KB17 检索

用法（backend 目录下，venv 已激活，服务在 127.0.0.1:8003）：
  .\.venv\Scripts\python.exe ..\work\stage-cache\verify_task13_ab.py \
    --admin-user admin --admin-pass admin \
    --user loadtester --pass "Loadtest#123" \
    --kb-id 17 --query "RAG 检索增强" --rounds 6

流程：
  1. admin 登录，loadtester 登录
  2. CACHE_BACKEND=off 基线：loadtester 跑 N 次同 query 检索（限速防 429）
  3. CACHE_BACKEND=memory：预热 2 次 + 跑 N 次
  4. CACHE_BACKEND=redis：预热 2 次 + 跑 N 次
  5. 对比三种 backend 的 p50/p95/命中率
"""
import argparse, json, time, sys, urllib.request, urllib.error, urllib.parse

# Windows 控制台默认 GBK 会因 emoji/中文崩溃，强制 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = "http://127.0.0.1:8003"


def api(path, method="GET", token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"_err": e.read().decode(errors="replace")}


def login(user, pwd):
    data = urllib.parse.urlencode({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(f"{BASE}/api/auth/login", data=data, method="POST",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def set_backend(admin_token, mode):
    # /api/settings PUT 批量格式：{"configs": [{"key":..,"value":..}]}
    code, resp = api("/api/settings", "PUT", admin_token,
                     {"configs": [{"key": "CACHE_BACKEND", "value": mode}]})
    return code == 200, resp


def search(token, query, kb_id, use_rerank=False):
    body = {"query": query, "knowledge_base_id": kb_id, "use_rerank": use_rerank}
    t0 = time.time()
    code, resp = api("/api/milvus/query", "POST", token, body)
    dt = time.time() - t0
    cached = resp.get("cached", False) if isinstance(resp, dict) else False
    n_results = len(resp.get("results", [])) if isinstance(resp, dict) else 0
    return dt, cached, code, n_results


def run_round(user_token, query, kb_id, n, label, rerank=False):
    print(f"\n=== {label}（{n} 次）===")
    latencies, hits = [], 0
    for i in range(n):
        dt, cached, code, nr = search(user_token, query, kb_id, rerank)
        if code != 200:
            print(f"  #{i+1} HTTP {code} (nr={nr})")
            time.sleep(2)
            continue
        latencies.append(dt)
        if cached:
            hits += 1
        print(f"  #{i+1} {dt:.3f}s {'cached' if cached else 'miss'} ({nr} results)")
        time.sleep(0.6)  # 限速防 429
    if not latencies:
        return {"label": label, "n": n, "p50": None, "p95": None, "hit_rate": 0, "hits": 0}
    latencies.sort()
    p50 = latencies[len(latencies)//2]
    p95 = latencies[min(len(latencies)-1, int(len(latencies)*0.95))]
    hr = hits / n if n else 0
    print(f"  → p50={p50:.3f}s p95={p95:.3f}s 命中率={hr*100:.0f}% ({hits}/{n})")
    return {"label": label, "n": n, "p50": p50, "p95": p95, "hit_rate": hr, "hits": hits, "latencies": latencies}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin-user", required=True)
    ap.add_argument("--admin-pass", required=True)
    ap.add_argument("--user", required=True, help="普通用户（跑检索）")
    ap.add_argument("--pass", dest="user_pass", required=True)
    ap.add_argument("--kb-id", type=int, required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--rerank", action="store_true")
    args = ap.parse_args()

    admin_token = login(args.admin_user, args.admin_pass)
    user_token = login(args.user, args.user_pass)
    print(f"登录成功：admin token={len(admin_token)}, {args.user} token={len(user_token)}")

    results = []
    for mode in ["off", "memory", "redis"]:
        ok, resp = set_backend(admin_token, mode)
        if not ok:
            print(f"[WARN] 切换 CACHE_BACKEND={mode} 失败: {str(resp)[:120]}")
            continue
        print(f"\n>>> 已切换 CACHE_BACKEND={mode}")
        time.sleep(1)
        # off 模式不预热
        if mode != "off":
            run_round(user_token, args.query, args.kb_id, 2, f"预热({mode})", args.rerank)
        r = run_round(user_token, args.query, args.kb_id, args.rounds, f"测量({mode})", args.rerank)
        results.append(r)

    # 汇总
    print("\n" + "="*60)
    print("A/B 对比汇总")
    print("="*60)
    print(f"{'backend':<12} {'p50':>10} {'p95':>10} {'命中率':>10}")
    for r in results:
        p50 = f"{r['p50']:.3f}s" if r['p50'] else "—"
        p95 = f"{r['p95']:.3f}s" if r['p95'] else "—"
        print(f"{r['label']:<24} {p50:>10} {p95:>10} {r['hit_rate']*100:>9.0f}%")

    if len(results) >= 2 and results[0]['p50'] and results[-1]['p50']:
        speedup = results[0]['p50'] / results[-1]['p50']
        print(f"\n缓存命中加速（off→最终）: {speedup:.1f}x")

    out = {"args": vars(args), "results": results}
    with open("verify_task13_ab_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n结果已落 verify_task13_ab_result.json")


if __name__ == "__main__":
    main()
