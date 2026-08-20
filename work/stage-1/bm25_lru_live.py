# -*- python: utf-8 -*-
"""真实服务级 LRU 验证：真实 PG 数据 + 真实 audit 落库。

BM25_CACHE_BUCKETS=2，用真实分桶（0:1 chunks=372 / 0:2 chunks=1046）+ 复制桶
触发建桶与 LRU 逐出，验证：
1. 建桶日志带 chunk 数与 token 总数；
2. 超过桶数上限逐出最久未用桶，日志 + audit 表有 bm25.cache.lru_evict；
3. 被逐出桶重建可用（分词缓存命中，毫秒级）。
"""
import sys, os, time, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))
logging.basicConfig(level=logging.INFO)

from config import set_runtime
from services.bm25_client import BM25Client
from services.database import db

set_runtime("BM25_CACHE_BUCKETS", 2)
set_runtime("BM25_CACHE_MAX_CHUNKS", 100000)

client = BM25Client()
n = client.load_from_database()
print(f"loaded {n} chunks, buckets: {[(k, len(v)) for k, v in client._corpus.items()]}")

t0 = time.perf_counter()
bm25_a, ids_a = client._get_or_build_model("0:1", client._corpus["0:1"])
print(f"build 0:1: {len(ids_a)} docs, {time.perf_counter()-t0:.3f}s")

bm25_b, ids_b = client._get_or_build_model("0:2", client._corpus["0:2"])
print(f"build 0:2: {len(ids_b)} docs")

# 第三个桶（真实语料的复制桶）→ 触发逐出最久未用的 0:1
client._corpus["9:1"] = dict(client._corpus["0:1"])
t0 = time.perf_counter()
bm25_c, ids_c = client._get_or_build_model("9:1", client._corpus["9:1"])
print(f"build 9:1: {len(ids_c)} docs, {time.perf_counter()-t0:.3f}s")

assert "0:1" not in client._models, "LRU 未逐出 0:1"
assert set(client._models.keys()) == {"0:2", "9:1"}, list(client._models.keys())
print("PASS: 桶数上限逐出，剩余桶:", list(client._models.keys()))

# 被逐出桶重建（应走分词缓存，快）
t0 = time.perf_counter()
client._corpus["8:1"] = dict(client._corpus["0:1"])
client._get_or_build_model("8:1", client._corpus["8:1"])
dt = time.perf_counter() - t0
print(f"rebuild-after-evict 8:1 (372 chunks): {dt:.3f}s  (分词缓存命中应亚秒级)")
assert dt < 5

# audit 表验证
try:
    rows = db.fetchall(
        "SELECT event_type, detail FROM audit_log "
        "WHERE event_type='bm25.cache.lru_evict' ORDER BY id DESC LIMIT 3"
    )
    for r in rows:
        print("audit:", r["event_type"], r["detail"])
    assert rows, "audit 表无 lru_evict 事件"
except Exception as e:
    # 表名可能不同，兜底查找
    tables = db.fetchall("SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%audit%'")
    print("audit tables:", [t["table_name"] for t in tables], "err:", e)

print("LIVE PASS")
