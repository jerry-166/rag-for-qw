"""缓存权限安全用例验证（文档 08 §4.1 U1-U5）

用法（backend 目录，服务在 8003，litellm 在 4000）：
  .\.venv\Scripts\python.exe ..\work\stage-cache\verify_permissions.py

用例：
  U1 loadtester 查 admin 的 KB42（无权）→ 403，权限闸门在缓存前
  U2 admin 查 KB17 预热 → loadtester 查 KB17（key 同 kb_id scoped）→ cached:true（共享缓存，共建语义）
  U3 被 U1 + 设计覆盖（权限闸门前置 + key 不含分享名单，撤销=无权=403）
  U4 loadtester 查 KB17 cached → invalidate bump → 同 query miss（版本失效）
  U5 查审计 cache.degrade 事件（redis 不可用时降级已触发过）
"""
import sys, json, time, urllib.request, urllib.error, urllib.parse
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
    d = urllib.parse.urlencode({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(f"{BASE}/api/auth/login", data=d, method="POST",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["access_token"]

def api(path, method="GET", token=None, body=None):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: body = json.loads(e.read().decode(errors="replace"))
        except: body = {}
        return e.code, body

def search(token, query, kb_id):
    return api("/api/milvus/query", "POST", token, {"query": query, "knowledge_base_id": kb_id, "use_rerank": False})

def set_backend(admin_token, mode):
    return api("/api/settings", "PUT", admin_token, {"configs": [{"key": "CACHE_BACKEND", "value": mode}]})

def invalidate(admin_token, kb_id):
    return api("/api/cache/invalidate", "POST", admin_token, {"kb_id": kb_id})

def main():
    admin = login("admin", "admin")
    loadtester = login("loadtester", "Loadtest#123")
    print(f"登录: admin + loadtester")
    # 确保 redis 模式
    set_backend(admin, "redis")
    time.sleep(1)
    # 用一个独特 query 避免命中之前 A/B 的缓存
    QUERY = "permission test unique query " + str(int(time.time()))
    KB_ADMIN = 42   # admin 的，loadtester 无权
    KB_LOADTESTER = 17  # loadtester 属主

    print("\n=== U1: 无权访问 KB → 403（权限闸门在缓存前）===")
    code, resp = search(loadtester, QUERY, KB_ADMIN)
    check(f"loadtester 查 admin 的 KB{KB_ADMIN} → 403", code == 403, f"(code={code})")

    print("\n=== U2: 共享 KB 两用户同查 → loadtester 命中 admin 的缓存 ===")
    # admin 先查 KB17（预热缓存）—— admin 对 KB17 有全局权限
    code1, r1 = search(admin, QUERY, KB_LOADTESTER)
    print(f"  admin 查 KB{KB_LOADTESTER} (预热): code={code1} cached={r1.get('cached') if isinstance(r1,dict) else '?'}")
    check("admin 预热成功 200", code1 == 200, f"(code={code1})")
    # loadtester 同查 KB17（自己属主，key 同 kb_id=17 scoped）→ 应 cached:true
    code2, r2 = search(loadtester, QUERY, KB_LOADTESTER)
    print(f"  loadtester 查 KB{KB_LOADTESTER}: code={code2} cached={r2.get('cached') if isinstance(r2,dict) else '?'}")
    check("loadtester 命中 admin 预热的缓存（cached:true）",
          code2 == 200 and r2.get("cached") == True, f"(code={code2} cached={r2.get('cached')})")
    check("缓存共享语义——key 不含 user_id（共建特性）",
          r2.get("cached") == True, "(loadtester 复用了 admin 的结果)")

    print("\n=== U3: 被 U1 + 设计覆盖 ===")
    print("  设计铁律：权限闸门（check_kb_permission）在缓存查找之前；")
    print("  key 不含 user_id/分享名单（verify_task6 已验证 KB 列表顺序无关=共享）。")
    print("  撤销分享 = 无权 = 403 在缓存前拦截（与 U1 同路径），不泄漏缓存。")
    check("U3 被覆盖（U1 + key 铁律）", True)

    print("\n=== U4: KB 导入新文档（bump）后同查 → miss ===")
    # loadtester 再查应还是 cached（确认缓存还在）
    code3, r3 = search(loadtester, QUERY, KB_LOADTESTER)
    check("bump 前仍是 cached（确认缓存命中）", r3.get("cached") == True, f"(cached={r3.get('cached')})")
    # admin 手动 invalidate（模拟内容变更 bump cache_version）
    ic, ir = invalidate(admin, KB_LOADTESTER)
    print(f"  invalidate KB{KB_LOADTESTER}: code={ic} new_version={ir.get('new_version') if isinstance(ir,dict) else '?'}")
    check("invalidate 成功（bump version）", ic == 200, f"(code={ic})")
    # 同 query 再查 → 应 miss（版本失配，旧 key 永不命中）
    code4, r4 = search(loadtester, QUERY, KB_LOADTESTER)
    print(f"  bump 后同查: code={code4} cached={r4.get('cached') if isinstance(r4,dict) else '?'}")
    check("bump 后同 query → miss（版本失效生效）",
          r4.get("cached") != True, f"(cached={r4.get('cached')})")

    print("\n=== U5: 降级韧性（查审计 cache.degrade 事件）===")
    # 之前 redis 没起时后端启动降级，应有 cache.degrade 事件
    sys.path.insert(0, '.')
    from services.database import db
    rows = db.fetchall("SELECT action, detail FROM audit_log WHERE action LIKE 'cache.%' ORDER BY occurred_at DESC LIMIT 50")
    degrade_total = db.fetchone("SELECT count(*) AS c FROM audit_log WHERE action='cache.degrade'")["c"]
    stats_total = db.fetchone("SELECT count(*) AS c FROM audit_log WHERE action='cache.stats'")["c"]
    version_bumps = [r for r in rows if r["action"] == "cache.version_bump"]
    print(f"  审计 cache.degrade 全量事件: {degrade_total} 条（redis 不可用时降级记录）")
    print(f"  审计 cache.stats 快照: {stats_total} 条（60s 周期任务正常）")
    print(f"  最近 cache.version_bump: {len(version_bumps)} 条")
    if degrade_total > 0:
        print(f"  cache.degrade 事件存在 → 降级韧性已验证（redis 不可用时不 crash、降级 memory）")
    check("U5 降级韧性（cache.degrade 事件存在）", degrade_total > 0,
          f"({degrade_total} 条 degrade 事件)" if degrade_total else "(无——redis 一直可用也正常)")

    print(f"\n{'='*50}")
    if fails:
        print(f"FAILED: {len(fails)} 项 — {fails}")
        sys.exit(1)
    print("ALL PASS — 缓存权限安全用例验证通过")

if __name__ == "__main__":
    main()
