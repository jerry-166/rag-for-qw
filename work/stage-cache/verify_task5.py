# Task 5 验证：缓存 schema + db 层方法（文档 08）
# 运行: cd backend && .\.venv\Scripts\python.exe ..\work\stage-cache\verify_task5.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from services.database import db

fails = []

def check(name, cond, extra=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {extra}")
    if not cond:
        fails.append(name)

# 1. 挑一个真实 KB 测版本号
kb = db.fetchone("SELECT id FROM knowledge_base ORDER BY id LIMIT 1")
if kb is None:
    print("SKIP  库中无 KB，仅测 L1 路径")
else:
    kb_id = kb["id"]
    v0 = db.get_kb_cache_versions([kb_id]).get(str(kb_id))
    check("get_kb_cache_versions 返回版本", v0 is not None, f"v={v0}")

    v1 = db.bump_kb_cache_version(kb_id)
    check("bump 递增", v1 == (v0 or 0) + 1, f"{v0} -> {v1}")

    v2 = db.bump_kb_cache_version(kb_id)
    check("bump 再次递增", v2 == v1 + 1, f"{v1} -> {v2}")
    # 还原，避免污染后续验收基线
    db.execute("UPDATE knowledge_base SET cache_version = %s WHERE id = %s", (v0 or 0, kb_id))

    # 2. 不存在的 KB
    vers = db.get_kb_cache_versions([99999999])
    check("不存在 KB 返回空 dict", vers == {})

    # 3. 用户域 / 全局版本
    any_user = db.fetchone("SELECT id FROM users ORDER BY id LIMIT 1")
    if any_user:
        uv = db.get_user_cache_scope_version(any_user["id"])
        check("用户域版本为非负 int", isinstance(uv, int) and uv >= 0, f"v={uv}")
    gv = db.get_global_cache_version()
    check("全局版本为非负 int", isinstance(gv, int) and gv >= 0, f"v={gv}")

# 4. L1 embedding 缓存 roundtrip
qh = "verify_task5_" + "a" * 64
vec = [0.123, -0.456, 0.789]
db.put_query_embedding(qh, "验证查询", "test-model", vec)
got = db.get_query_embedding(qh)
check("L1 roundtrip 向量一致", got is not None and all(abs(a - b) < 1e-9 for a, b in zip(got, vec)), f"len={len(got) if got else 0}")
got2 = db.get_query_embedding(qh)
check("L1 二次读取命中", got2 == got)
row = db.fetchone("SELECT hit_count FROM query_embedding_cache WHERE query_hash = %s", (qh,))
check("hit_count 累计 = 2", row and row["hit_count"] == 2, f"hits={row['hit_count'] if row else None}")
miss = db.get_query_embedding("verify_task5_" + "b" * 64)
check("miss 返回 None", miss is None)
# 清理
db.execute("DELETE FROM query_embedding_cache WHERE query_hash = %s", (qh,))

# 5. 表结构存在性（cache_version 列）
cols = db.fetchall("SELECT column_name FROM information_schema.columns WHERE table_name='knowledge_base' AND column_name='cache_version'")
check("knowledge_base.cache_version 列存在", len(cols) == 1)

print()
if fails:
    print(f"结果: {len(fails)} 项 FAIL — {fails}")
    sys.exit(1)
print("结果: 全部 PASS")
