# Task 6 验证：CacheManager 纯逻辑（key 归一化 / TTL / 双上限 / off / fail-open）
# 运行: cd backend && .\.venv\Scripts\python.exe ..\work\stage-cache\verify_task6.py
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from config import set_runtime
set_runtime("CACHE_BACKEND", "memory")  # 纯内存模式，不依赖 redis

from services.database import db
from services.cache import CacheManager, _canonical_filter

fails = []
def check(name, cond, extra=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {extra}")
    if not cond:
        fails.append(name)

kb_row = db.fetchone("SELECT id FROM knowledge_base ORDER BY id LIMIT 1")
kb2_row = db.fetchone("SELECT id FROM knowledge_base ORDER BY id DESC LIMIT 1")
if kb_row is None:
    print("SKIP: 库中无 KB"); sys.exit(0)
kb, kb2 = kb_row["id"], kb2_row["id"]
orig_versions = db.get_kb_cache_versions([kb, kb2])

# ── 1. key 归一化 ──
cm = CacheManager()
k_a = cm.build_search_key("查询", {"knowledge_base_ids": [kb, kb2]}, "native", 5, True)
k_b = cm.build_search_key("查询", {"knowledge_base_ids": [kb2, kb]}, "native", 5, True)
check("KB 列表顺序无关 → 同 key", k_a == k_b and k_a is not None)

k_c = cm.build_search_key("查询", {"knowledge_base_ids": [kb, kb2]}, "native", 5, True)
k_d = cm.build_search_key("查询", {"knowledge_base_ids": [kb, kb2], "user_id": 1}, "native", 5, True)
check("过滤条件不同 → 不同 key", k_c != k_d)

k_e = cm.build_search_key("查询", {"knowledge_base_id": kb}, "native", 5, True)
k_f = cm.build_search_key("查询", {"knowledge_base_id": kb}, "advanced", 5, True)
k_g = cm.build_search_key("查询", {"knowledge_base_id": kb}, "native", 10, True)
k_h = cm.build_search_key("查询", {"knowledge_base_id": kb}, "native", 5, False)
check("mode/limit/rerank 任一不同 → 不同 key", k_e != k_f and k_e != k_g and k_e != k_h)

check("不存在 KB → key 为 None（跳过缓存）",
      cm.build_search_key("q", {"knowledge_base_id": 99999999}) is None)

# ── 2. 版本变化 → key 失配（版本号失效核心机制）──
db.bump_kb_cache_version(kb)
k_after = cm.build_search_key("查询", {"knowledge_base_id": kb}, "native", 5, True)
check("bump 后同查询 key 改变", k_e != k_after)
# 还原版本
db.execute("UPDATE knowledge_base SET cache_version = %s WHERE id = %s",
           (orig_versions.get(str(kb), 0), kb))

# ── 3. 内存 LRU 读写 + TTL 过期 ──
cm2 = CacheManager()
key = "rag:l2:test_ttl"
cm2._insert_mem(key, [{"content": "x"}], 100, time.time() + 60, {"kb_id": 1})
got = cm2.get(key)
check("内存命中返回 value", got == [{"content": "x"}])
check("l2_mem_hit 计数", cm2.counters["l2_mem_hit"] == 1)

cm2._insert_mem(key, [{"content": "x"}], 100, time.time() - 1, {"kb_id": 1})
got2 = cm2.get(key)
check("TTL 过期 → miss", got2 is None and cm2.counters["l2_miss"] == 1)

# ── 4. 双上限逐出 ──
set_runtime("CACHE_MEM_MAX_ENTRIES", "3")
cm3 = CacheManager()
for i in range(5):
    cm3.set(f"rag:l2:evict_{i}", [{"i": i}], meta={})
check("条目上限逐出到 3 条", len(cm3._mem) == 3 and cm3.counters["evict"] == 2,
      f"entries={len(cm3._mem)} evict={cm3.counters['evict']}")
set_runtime("CACHE_MEM_MAX_ENTRIES", "256")

# ── 5. off 模式短路 ──
set_runtime("CACHE_BACKEND", "off")
cm4 = CacheManager()
cm4._insert_mem("rag:l2:off_test", ["v"], 10, time.time() + 60, None)
check("off 模式 get 短路", cm4.get("rag:l2:off_test") is None)
before = cm4.counters["set"]
cm4.set("rag:l2:off_test", ["v"])
check("off 模式 set 短路", cm4.counters["set"] == before)
set_runtime("CACHE_BACKEND", "memory")

# ── 6. embed_cached fail-open（db 挂了仍直算）──
cm5 = CacheManager()
def _boom(*a, **kw):
    raise RuntimeError("db down")
_real_db = db._ensure()  # db 是 __slots__ 懒加载代理，须 patch 真实实例
_orig_get, _orig_put = _real_db.get_query_embedding, _real_db.put_query_embedding
_real_db.get_query_embedding, _real_db.put_query_embedding = _boom, _boom
try:
    result = cm5.embed_cached("测试查询", "test-model", lambda q: [1.5, 2.5])
    check("L1 db 故障 fail-open 直算", result == [1.5, 2.5])
finally:
    _real_db.get_query_embedding, _real_db.put_query_embedding = _orig_get, _orig_put

result2 = cm5.embed_cached("测试查询2", "test-model", lambda q: [3.0])
check("L1 正常路径写后读", cm5.embed_cached("测试查询2", "test-model", lambda q: [9.9]) == [3.0])
check("l1 计数", cm5.counters["l1_miss"] >= 1 and cm5.counters["l1_hit"] >= 1)
# 清理 L1 测试数据
db.execute("DELETE FROM query_embedding_cache WHERE query_text = %s", ("测试查询2",))

# ── 7. 空结果不占内存 ──
cm6 = CacheManager()
cm6.set("rag:l2:empty_test", [], meta={})
check("空结果不进内存层", len(cm6._mem) == 0 and cm6.counters["set"] == 1)

# ── 8. _canonical_filter 纯函数 ──
check("canonical 排序", _canonical_filter({"b": 1, "a": [3, 1]}) == [["a", [1, 3]], ["b", 1]])

print()
if fails:
    print(f"结果: {len(fails)} 项 FAIL — {fails}"); sys.exit(1)
print("结果: 全部 PASS")
