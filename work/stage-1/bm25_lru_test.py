# -*- coding: utf-8 -*-
"""01 §7.1 BM25 LRU 单元级验证（不依赖 PG/jieba，monkeypatch 掉分词与审计）。

断言：
1. 桶数上限：>上限的桶触发逐出，且最近最少使用先被逐出（LRU 顺序）；
2. 命中刷新：get 已缓存桶后该桶不被逐出；
3. 总 chunk 上限：超限逐出最久未用桶；
4. 单桶超限：不缓存（下次现算），oversized 集合记录；
5. 审计/日志有逐出事件。
"""
import sys, os, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))

# 隔离 PG / 审计 / 分词依赖
from unittest import mock

fake_audit = mock.MagicMock()
sys.modules["services.audit"] = mock.MagicMock(audit=fake_audit)

import services.bm25_client as bc

# jieba / 分词批量 → 固定分词（每个 chunk 3 个 token）
bc._get_jieba = lambda: mock.MagicMock(
    cut_for_search=lambda text: ["t", text[:2], "x"]
)

from services.bm25_client import BM25Client

client = BM25Client()

def fake_tokenized_batch(corpus):
    return {cid: ["t", str(cid), "x"] for cid in corpus}

client._get_tokenized_batch = fake_tokenized_batch

def make_bucket(key, n):
    client._corpus[key] = {
        i: {"id": i, "user_id": 1, "knowledge_base_id": 0,
            "document_id": 1, "chunk_index": i, "content": f"内容{i}测试", "metadata": {}}
        for i in range(n)
    }

from config import set_runtime

# ---- 用例 1：桶数上限 LRU 顺序 ----
set_runtime("BM25_CACHE_BUCKETS", 3)
set_runtime("BM25_CACHE_MAX_CHUNKS", 100000)
fake_audit.log.reset_mock()
for k in ["u1:1", "u1:2", "u1:3"]:
    make_bucket(k, 10)
    client._get_or_build_model(k, client._corpus[k])

# 命中 u1:1（刷新 LRU 位）
client._get_or_build_model("u1:1", client._corpus["u1:1"])

# 插入第 4 个桶 → 应逐出 u1:2（最久未用），保留 u1:3, u1:1
make_bucket("u1:4", 10)
client._get_or_build_model("u1:4", client._corpus["u1:4"])

assert "u1:2" not in client._models, f"LRU 逐出失败: keys={list(client._models)}"
assert "u1:1" in client._models, "命中刷新失败（u1:1 被误逐出）"
assert list(client._models.keys()) == ["u1:3", "u1:1", "u1:4"], list(client._models.keys())
print("[PASS] 用例1 桶数上限 + LRU 顺序 + 命中刷新")

evict_calls = [c for c in fake_audit.log.call_args_list
               if c.args and c.args[0] == "bm25.cache.lru_evict"]
assert evict_calls, "未产生 bm25.cache.lru_evict 审计事件"
print(f"[PASS] 用例2 逐出审计事件: {len(evict_calls)} 次, detail={evict_calls[0].kwargs.get('detail')}")

# ---- 用例 3：总 chunk 上限 ----
set_runtime("BM25_CACHE_BUCKETS", 10)
set_runtime("BM25_CACHE_MAX_CHUNKS", 25)
client2 = BM25Client()
client2._get_tokenized_batch = fake_tokenized_batch
for k in ["a:1", "a:2"]:
    make_bucket_ = k
    client2._corpus[k] = {i: {"id": i, "content": f"c{i}"} for i in range(10)}
    client2._get_or_build_model(k, client2._corpus[k])
assert sum(client2._model_sizes.values()) == 20
client2._corpus["a:3"] = {i: {"id": i, "content": f"c{i}"} for i in range(10)}
client2._get_or_build_model("a:3", client2._corpus["a:3"])
total = sum(client2._model_sizes.values())
assert total <= 25, f"总 chunk 上限未生效: {total}"
assert "a:1" not in client2._model_sizes, "应逐出最久未用桶 a:1"
print(f"[PASS] 用例3 总 chunk 上限: 当前缓存 {client2._model_sizes}")

# ---- 用例 4：单桶超限不缓存 ----
client3 = BM25Client()
client3._get_tokenized_batch = fake_tokenized_batch
set_runtime("BM25_CACHE_BUCKETS", 10)
set_runtime("BM25_CACHE_MAX_CHUNKS", 5)
fake_audit.log.reset_mock()
client3._corpus["big:1"] = {i: {"id": i, "content": f"c{i}"} for i in range(50)}
bm25a, ids_a = client3._get_or_build_model("big:1", client3._corpus["big:1"])
assert "big:1" not in client3._models, "单桶超限不应缓存"
assert "big:1" in client3._oversized
bm25b, ids_b = client3._get_or_build_model("big:1", client3._corpus["big:1"])
assert len(ids_a) == len(ids_b) == 50 and bm25b is not None, "超限桶现算仍可用"
warn_events = [c for c in fake_audit.log.call_args_list
               if c.args and c.args[0] == "bm25.cache.oversized_bucket"]
assert warn_events, "oversized 无审计事件"
print("[PASS] 用例4 单桶超限不缓存 + 现算可用 + warn/审计")

# ---- 用例 5：上限=0 禁用缓存 ----
set_runtime("BM25_CACHE_BUCKETS", 0)
client4 = BM25Client()
client4._get_tokenized_batch = fake_tokenized_batch
client4._corpus["z:1"] = {1: {"id": 1, "content": "c"}}
client4._get_or_build_model("z:1", client4._corpus["z:1"])
assert len(client4._models) == 0, "BM25_CACHE_BUCKETS=0 应禁用缓存"
print("[PASS] 用例5 桶上限=0 禁用缓存")

print("ALL PASS")
