"""三层缓存管理器（文档 08）

L1: 查询 embedding 缓存（PG query_embedding_cache，持久、纯函数无需失效）
L2: 检索结果缓存（进程内存 LRU → Redis 两级读取，双写）

key 规范铁律（设计文档 §2.4，BUG-018 教训）：
  - key 材料 = 归一化后的生效过滤条件（复用 _build_metadata_filter 输出），
    不是 user_id / 分享名单——"谁能查"由权限闸门管（在缓存查找之前），
    "查到什么"才进 key；共享 KB 场景新成员命中旧缓存是共建语义（特性）；
  - 版本维度按过滤形态解析：单 KB/KB 列表→{kb_id:version} 排序映射；
    user 过滤→用户可见域 max(version)；admin 无过滤→全局 max(version)；
  - 版本解析失败 → 本次请求跳过缓存（fail-open 走真实检索）。
"""
import json
import hashlib
import random
import threading
import time
from collections import OrderedDict
from typing import Optional

from config import init_logger, get_runtime

logger = init_logger(__name__)

_MEM_LOCK = threading.Lock()  # rag_tools 在 worker 线程访问内存层


def _canonical_filter(f: dict) -> list:
    """过滤条件归一化：dict → 按 key 排序的 [[k, v], ...]，列表值排序。

    例：{"knowledge_base_ids": [23,17]} 与 {"knowledge_base_ids": [17,23]}
    归一化后相同 → 同一 key（Agent 全局检索的可见集合是无序来源）。
    """
    out = []
    for k in sorted((f or {}).keys()):
        v = f[k]
        if isinstance(v, (list, tuple, set)):
            out.append([k, sorted(v)])
        else:
            out.append([k, v])
    return out


class CacheManager:
    """L1/L2 缓存统一入口（进程单例 get_cache_manager()）。"""

    def __init__(self):
        # 内存 LRU：key -> {"value", "bytes", "expire_at", "hits", "meta"}
        self._mem: "OrderedDict[str, dict]" = OrderedDict()
        self._mem_bytes = 0
        self._redis = None
        self._redis_ok: Optional[bool] = None   # None=未探测
        self._degrade_logged = False
        self.counters = {
            "l1_hit": 0, "l1_miss": 0,
            "l2_mem_hit": 0, "l2_redis_hit": 0, "l2_miss": 0,
            "set": 0, "evict": 0, "version_bump": 0,
        }

    # ---------- 后端模式 ----------

    def _backend(self) -> str:
        return str(get_runtime("CACHE_BACKEND", "redis")).lower()

    def _redis_client(self):
        if self._redis is None:
            import redis as redis_lib
            self._redis = redis_lib.Redis.from_url(
                get_runtime("REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        return self._redis

    def _redis_available(self) -> bool:
        if self._redis_ok is None:
            try:
                self._redis_client().ping()
                self._redis_ok = True
            except Exception as e:
                self._redis_ok = False
                self._log_degrade(e)
        return self._redis_ok

    def _log_degrade(self, e):
        """Redis 故障降级日志（每轮故障只打一次 + 审计事件）。"""
        if not self._degrade_logged:
            self._degrade_logged = True
            logger.warning(f"[Cache] Redis 不可用，降级为纯内存模式: {e}")
            try:
                from services.audit import audit
                audit.log("cache.degrade", detail={"error": str(e)[:200]})
            except Exception:
                pass

    # ---------- L2 key 构造（§2.4 铁律） ----------

    def resolve_versions(self, filt: dict):
        """按过滤形态解析版本维度。失败返回 None（调用方跳过缓存）。"""
        from services.database import db
        try:
            kb_ids = (filt or {}).get("knowledge_base_ids")
            kb_id = (filt or {}).get("knowledge_base_id")
            if kb_ids:
                vers = db.get_kb_cache_versions(list(kb_ids))
                if not vers:
                    return None  # KB 不存在或查询失败 → 跳过缓存（fail-open）
                return {"kb": vers}
            if kb_id is not None:
                vers = db.get_kb_cache_versions([kb_id])
                if not vers:
                    return None
                return {"kb": vers}
            uid = (filt or {}).get("user_id")
            if uid is not None:
                return {"u": uid, "v": db.get_user_cache_scope_version(uid)}
            return {"g": db.get_global_cache_version()}
        except Exception as e:
            logger.warning(f"[Cache] 版本解析失败，本次跳过缓存: {e}")
            return None

    def build_search_key(self, query: str, filt: dict, mode: str = "",
                         limit: int = 5, use_rerank: bool = False,
                         extra: dict = None) -> Optional[str]:
        """L2 key：hash(query + 归一化过滤 + 模式 + limit + rerank + 版本 + extra)。
        返回 None 表示应跳过缓存（版本解析失败）。"""
        versions = self.resolve_versions(filt)
        if versions is None:
            return None
        payload = {
            "q": query, "f": _canonical_filter(filt), "m": mode or "",
            "k": int(limit), "r": bool(use_rerank), "v": versions,
            "x": extra or {},
        }
        return "rag:l2:" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    # ---------- L2 读写（内存 → Redis 两级读取，双写） ----------

    def get(self, key: Optional[str]):
        if not key or self._backend() == "off":
            return None
        now = time.time()
        with _MEM_LOCK:
            ent = self._mem.get(key)
            if ent is not None:
                if ent["expire_at"] > now:
                    self._mem.move_to_end(key)
                    ent["hits"].append(now)
                    ent["hits"] = ent["hits"][-5:]  # 命中时间线只留最近 5 次
                    self.counters["l2_mem_hit"] += 1
                    return ent["value"]
                # TTL 过期 → 淘汰
                self._mem_bytes -= ent["bytes"]
                del self._mem[key]
        if self._backend() == "redis":
            try:
                if self._redis_available():
                    raw = self._redis_client().get(key)
                    if raw is not None:
                        self.counters["l2_redis_hit"] += 1
                        value = json.loads(raw)
                        # Redis 命中回填内存层（热点提升）
                        if value and len(raw) <= 256 * 1024:
                            with _MEM_LOCK:
                                self._insert_mem(key, value, len(raw),
                                                 now + self._ttl(), None)
                        return value
            except Exception as e:
                self._redis_ok = None
                self._log_degrade(e)
        self.counters["l2_miss"] += 1
        return None

    def _ttl(self) -> int:
        """基础 TTL + 0-120s 随机抖动（防雪崩）。"""
        return int(get_runtime("CACHE_TTL_SECONDS", 600)) + random.randint(0, 120)

    def set(self, key: Optional[str], value, meta: dict = None):
        if not key or self._backend() == "off":
            return
        ttl = self._ttl()
        if not value:  # 空结果短 TTL（防穿透）
            ttl = min(ttl, int(get_runtime("CACHE_EMPTY_TTL_SECONDS", 60)))
        raw = json.dumps(value, ensure_ascii=False)
        self.counters["set"] += 1
        # 内存层：空结果与超大值（>256KB）不占内存，只进 Redis
        if value and len(raw) <= 256 * 1024:
            with _MEM_LOCK:
                self._insert_mem(key, value, len(raw), time.time() + ttl, meta)
        if self._backend() == "redis":
            try:
                if self._redis_available():
                    self._redis_client().setex(key, ttl, raw)
            except Exception as e:
                self._redis_ok = None
                self._log_degrade(e)

    def _insert_mem(self, key, value, nbytes, expire_at, meta):
        """插入内存 LRU 并按双上限（条目数/字节）逐出最旧。"""
        max_entries = int(get_runtime("CACHE_MEM_MAX_ENTRIES", 256))
        max_mb = int(get_runtime("CACHE_MEM_MAX_MB", 64))
        old = self._mem.pop(key, None)
        if old:
            self._mem_bytes -= old["bytes"]
        self._mem[key] = {"value": value, "bytes": nbytes,
                          "expire_at": expire_at, "hits": [], "meta": meta or {}}
        self._mem_bytes += nbytes
        while (len(self._mem) > max_entries or self._mem_bytes > max_mb * 1024 * 1024) \
                and len(self._mem) > 1:
            _, victim = self._mem.popitem(last=False)
            self._mem_bytes -= victim["bytes"]
            self.counters["evict"] += 1

    # ---------- L1 查询 embedding ----------

    def embed_cached(self, query_text: str, model_name: str, embed_fn):
        """L1：PG 命中免远程 embedding HTTP。embed_fn 是同步的 embed_query。
        任何异常 fail-open 到直算（缓存永不阻塞主路径）。"""
        try:
            from services.database import db
        except Exception:
            return embed_fn(query_text)
        qhash = hashlib.sha256(
            f"{query_text}\x00{model_name}".encode("utf-8")).hexdigest()
        try:
            cached = db.get_query_embedding(qhash)
            if cached is not None:
                self.counters["l1_hit"] += 1
                return cached
        except Exception as e:
            logger.debug(f"[Cache] L1 读失败（fail-open 直算）: {e}")
        self.counters["l1_miss"] += 1
        vec = embed_fn(query_text)
        try:
            db.put_query_embedding(qhash, query_text, model_name, vec)
        except Exception as e:
            logger.debug(f"[Cache] L1 写失败（不影响结果）: {e}")
        return vec

    # ---------- 管理动作（Phase 2 API 用） ----------

    def stats(self) -> dict:
        with _MEM_LOCK:
            mem_entries = len(self._mem)
            mem_bytes = self._mem_bytes
        out = {
            "backend": self._backend(),
            "redis_ok": self._redis_available() if self._backend() == "redis" else None,
            "counters": dict(self.counters),
            "mem_entries": mem_entries,
            "mem_bytes": mem_bytes,
        }
        l2_total = (self.counters["l2_mem_hit"] + self.counters["l2_redis_hit"]
                    + self.counters["l2_miss"])
        out["l2_hit_rate"] = round(
            (self.counters["l2_mem_hit"] + self.counters["l2_redis_hit"]) / l2_total, 4
        ) if l2_total else None
        l1_total = self.counters["l1_hit"] + self.counters["l1_miss"]
        out["l1_hit_rate"] = round(self.counters["l1_hit"] / l1_total, 4) if l1_total else None
        if self._backend() == "redis" and out["redis_ok"]:
            try:
                info = self._redis_client().info("memory")
                out["redis_used_memory"] = info.get("used_memory_human")
                out["redis_keys"] = self._redis_client().dbsize()
            except Exception:
                pass
        return out

    def entries(self, layer: str = "mem", limit: int = 50) -> list:
        """条目明细（mem / redis）。供 /api/cache/entries。"""
        now = time.time()
        if layer == "mem":
            with _MEM_LOCK:
                items = []
                for k, ent in reversed(self._mem.items()):
                    items.append({
                        "key": k, "bytes": ent["bytes"],
                        "ttl_left": max(0, int(ent["expire_at"] - now)),
                        "hits": len(ent["hits"]), "meta": ent["meta"],
                    })
                    if len(items) >= limit:
                        break
            return items
        if layer == "redis":
            try:
                if not self._redis_available():
                    return []
                out, cursor = [], 0
                while len(out) < limit:
                    cursor, keys = self._redis_client().scan(
                        cursor=cursor, match="rag:l2:*", count=50)
                    for k in keys:
                        out.append({"key": k, "ttl_left": max(0, self._redis_client().ttl(k)),
                                    "meta": {}})
                        if len(out) >= limit:
                            break
                    if cursor == 0:
                        break
                return out
            except Exception:
                return []
        return []

    def get_entry_detail(self, key: str):
        """单条完整内容（mem 优先，redis 兜底）。"""
        with _MEM_LOCK:
            ent = self._mem.get(key)
            if ent is not None:
                return {"value": ent["value"], "meta": ent["meta"],
                        "hit_timeline": ent["hits"], "bytes": ent["bytes"]}
        try:
            if self._backend() == "redis" and self._redis_available():
                raw = self._redis_client().get(key)
                if raw is not None:
                    return {"value": json.loads(raw), "meta": {},
                            "hit_timeline": [], "bytes": len(raw)}
        except Exception:
            pass
        return None

    def clear(self, layer: str):
        """清空某层：mem / redis / l1（l1=PG 表清空）。"""
        if layer == "mem":
            with _MEM_LOCK:
                self._mem.clear()
                self._mem_bytes = 0
        elif layer == "redis":
            try:
                if self._redis_available():
                    cursor, deleted = 0, 0
                    while True:
                        cursor, keys = self._redis_client().scan(
                            cursor=cursor, match="rag:l2:*", count=200)
                        if keys:
                            deleted += self._redis_client().delete(*keys)
                        if cursor == 0:
                            break
                logger.info(f"[Cache] Redis 层已清空（{deleted} 条）")
            except Exception as e:
                logger.warning(f"[Cache] Redis 清空失败: {e}")
        elif layer == "l1":
            from services.database import db
            db.execute("DELETE FROM query_embedding_cache")
            logger.info("[Cache] L1（PG）已清空")

    def record_version_bump(self):
        self.counters["version_bump"] += 1

    async def stats_snapshot_loop(self):
        """60s 周期审计快照（不打逐请求事件——压测下事件量翻倍）。"""
        import asyncio
        from services.audit import audit
        while True:
            try:
                await asyncio.sleep(60)
                audit.log("cache.stats", detail=self.stats())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"[Cache] stats 快照失败: {e}")


# ── 进程单例 ──────────────────────────────────────────────
_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    global _manager
    if _manager is None:
        _manager = CacheManager()
    return _manager


def bump_kb_cache(kb_id, reason: str, user_id=None):
    """写路径统一 bump 入口（文档 08 §2.5）：版本 +1 + 计数 + 审计。

    任何 KB 内容变更（split/import/delete/FAQ 写入）后调用；
    失败只记日志不影响主流程（旧缓存最多多活一个 TTL，有兜底）。
    """
    if kb_id is None:
        return
    try:
        from services.database import db
        from services.audit import audit
        new_v = db.bump_kb_cache_version(kb_id)
        if new_v >= 0:
            get_cache_manager().record_version_bump()
            audit.log("cache.version_bump", user_id=user_id, kb_id=kb_id,
                      detail={"reason": reason, "new_version": new_v})
    except Exception as e:
        logger.warning(f"[Cache] bump 失败(kb={kb_id}, reason={reason}): {e}")
