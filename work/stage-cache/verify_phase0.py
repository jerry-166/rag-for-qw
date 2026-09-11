"""Phase 0 修复性能验证（对照 Stage 4 基线）

验证项：
  1. aquery 移出事件循环：并发检索时 /healthz 不被阻塞（旧代码会卡几秒）
  2. reranker 有界线程池：rerank 开的并发不崩溃（c10.dll）+ p50 对照 Stage 4 的 70s 基线

用法（backend 目录下，服务在 127.0.0.1:8003，litellm 在 4000）：
  .\.venv\Scripts\python.exe ..\work\stage-cache\verify_phase0.py --user loadtester --pass "Loadtest#123" --kb-id 17
"""
import argparse, json, time, sys, threading, urllib.request, urllib.error, urllib.parse
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = "http://127.0.0.1:8003"
fails = []


def check(name, cond, extra=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {extra}")
    if not cond:
        fails.append(name)


def login(user, pwd):
    data = urllib.parse.urlencode({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(f"{BASE}/api/auth/login", data=data, method="POST",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def search(token, query, kb_id, use_rerank):
    body = json.dumps({"query": query, "knowledge_base_id": kb_id, "use_rerank": use_rerank}).encode()
    req = urllib.request.Request(f"{BASE}/api/milvus/query", data=body, method="POST",
                                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            dt = time.time() - t0
            resp = json.loads(r.read())
            return dt, r.status, resp.get("cached", False), len(resp.get("results", []))
    except urllib.error.HTTPError as e:
        return time.time() - t0, e.code, False, 0
    except Exception as e:
        return time.time() - t0, -1, False, str(e)[:60]


def healthz():
    t0 = time.time()
    try:
        with urllib.request.urlopen(f"{BASE}/healthz", timeout=30) as r:
            return time.time() - t0, r.status
    except Exception as e:
        return time.time() - t0, -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--pass", dest="password", required=True)
    ap.add_argument("--kb-id", type=int, required=True)
    ap.add_argument("--query", default="RAG retrieval augmented generation")
    args = ap.parse_args()

    token = login(args.user, args.password)
    print(f"登录成功: {args.user}")

    # ── 验证 1：aquery 不阻塞事件循环 ──────────────────
    print("\n=== 验证 1：aquery 移出事件循环（并发检索 + healthz 探测）===")
    # 起 3 个并发检索（无 rerank，每个 ~0.4s）+ 同时探 healthz
    # 旧代码（同步 query 阻塞事件循环）：healthz 会被卡到 3 个检索串行跑完 ~1.2s
    # 新代码（aquery run_in_executor）：检索在线程池，事件循环空闲，healthz 秒回
    results_box = {}
    def do_search(i):
        results_box[f"search_{i}"] = search(token, args.query, args.kb_id, use_rerank=False)

    threads = [threading.Thread(target=do_search, args=(i,)) for i in range(3)]
    t0 = time.time()
    for t in threads:
        t.start()
    # 同时探 healthz（并发进行中时）
    hz_dt, hz_code = healthz()
    for t in threads:
        t.join()
    wall = time.time() - t0

    print(f"  3 并发检索 wall={wall:.2f}s")
    for i in range(3):
        r = results_box[f"search_{i}"]
        print(f"    search#{i}: {r[0]:.2f}s status={r[1]} cached={r[2]} nr={r[3]}")
    print(f"  并发期间 healthz: {hz_dt:.3f}s status={hz_code}")
    # aquery 生效：healthz < 1s（事件循环没被阻塞）
    # 旧代码会卡到检索串行跑完（>1s）
    check("healthz 在并发检索期间秒回（<1s，证明事件循环未阻塞）",
          hz_code == 200 and hz_dt < 1.0, f"({hz_dt:.3f}s)")
    # 3 并发 wall 应接近单次而非 3 倍（并发受益于线程池）
    single = min(r[0] for r in results_box.values() if r[1] == 200)
    check("3 并发检索 wall < 3×单次（并发未被串行化）",
          wall < single * 2.5, f"(wall={wall:.2f}s, single={single:.2f}s)")

    # ── 验证 2：reranker 有界线程池（不崩 + 延迟）──────────
    print("\n=== 验证 2：reranker 有界线程池（rerank 开，并发 6@3）===")
    print("  预热 reranker 模型（首次加载 ~5-8s）...")
    warm_dt, warm_code, _, _ = search(token, args.query, args.kb_id, use_rerank=True)
    print(f"  预热完成: {warm_dt:.2f}s status={warm_code}")

    # 关缓存避免干扰（off 模式纯测 reranker）
    adm = login("admin", "admin")
    body = json.dumps({"configs": [{"key": "CACHE_BACKEND", "value": "off"}]}).encode()
    req = urllib.request.Request(f"{BASE}/api/settings", data=body, method="PUT",
                                headers={"Content-Type": "application/json", "Authorization": f"Bearer {adm}"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
        print("  已切 CACHE_BACKEND=off（纯测 reranker，排除缓存干扰）")
    except Exception as e:
        print(f"  切 off 失败: {e}")

    rerank_box = {}
    def do_rerank(i):
        rerank_box[f"r_{i}"] = search(token, args.query, args.kb_id, use_rerank=True)

    threads = [threading.Thread(target=do_rerank, args=(i,)) for i in range(6)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0

    ok_results = [rerank_box[f"r_{i}"] for i in range(6)]
    oks = [r for r in ok_results if r[1] == 200]
    crashes = [r for r in ok_results if r[1] == -1]
    lats = sorted([r[0] for r in oks])
    p50 = lats[len(lats)//2] if lats else None
    p95 = lats[int(len(lats)*0.95)] if len(lats) > 1 else (lats[0] if lats else None)

    print(f"  6 并发 rerank wall={wall:.2f}s, 成功 {len(oks)}/6, 崩溃 {len(crashes)}/6")
    for i, r in enumerate(ok_results):
        print(f"    r#{i}: {r[0]:.2f}s status={r[1]} {r[3] if r[1]==-1 else ''}")
    if p50:
        print(f"  → p50={p50:.2f}s p95={p95:.2f}s")

    # 对照 Stage 4 基线：40@10 rerank 开 p50=70s（旧默认线程池超订阅 + c10.dll 崩溃）
    check("rerank 并发无崩溃（c10.dll APPCRASH 已治理）", len(crashes) == 0,
          f"({len(crashes)} 崩溃)" if crashes else "")
    check("rerank 并发全部成功", len(oks) == 6, f"({len(oks)}/6)")
    # 串行化后 p50 应远低于 70s（6@3 规模比 40@10 小，且无超订阅）
    # 不硬凑"提速 10x"，只验证"不崩 + p50 < 70s 基线"
    if p50:
        check(f"rerank p50 < Stage4 基线 70s（实测 {p50:.1f}s）", p50 < 70, f"(p50={p50:.1f}s)")

    # 恢复缓存配置
    body = json.dumps({"configs": [{"key": "CACHE_BACKEND", "value": "redis"}]}).encode()
    req = urllib.request.Request(f"{BASE}/api/settings", data=body, method="PUT",
                                headers={"Content-Type": "application/json", "Authorization": f"Bearer {adm}"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
        print("\n  已恢复 CACHE_BACKEND=redis")
    except Exception:
        pass

    print(f"\n{'='*50}")
    if fails:
        print(f"FAILED: {len(fails)} 项 — {fails}")
        sys.exit(1)
    print("ALL PASS — Phase 0 修复性能验证通过")


if __name__ == "__main__":
    main()
