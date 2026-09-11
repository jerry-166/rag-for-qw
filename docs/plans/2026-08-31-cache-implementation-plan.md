# 三层缓存 + Stage 4 遗留修复 — 实施计划

> **执行方式**：主 agent 按任务派发子 agent 实现（subagent-driven），每任务完成后主 agent 审查 diff 并提交。设计依据：`2026-08-31-08-cache-design.md`（已定案）。
> **分支**：`feature/stage-cache`（已创建）。**提交信息用英文**（PowerShell 中文乱码坑）。
> **验证约定**：本项目无 pytest 基础设施，沿用惯例——验证脚本放 `work/stage-cache/`，每任务带可独立运行的验证步骤。
> **改前端文件后必须 bump index.html `?v=`**（缓存铁律）。

**Goal**: 修复 Stage 4 压测暴露的 P0/P1 遗留（reranker 并发治理、milvus query 阻塞事件循环），然后落地三层缓存（内存 LRU / Redis / PG）+ 缓存可观测页面。

**Architecture**: Phase 0 先修遗留出干净基线；Phase 1 落 L1（query embedding 缓存，PG）+ L2（检索结果缓存，内存→Redis 两级）+ KB 版本号失效；Phase 2 缓存中心 API + 页面；Phase 3 A/B 验收。

**Tech Stack**: FastAPI + psycopg2（既有）、redis-py（新增，`redis>=5.0.0`）、redis:7-alpine Docker 容器（128MB 硬顶）、原生 JS 前端。

---

## Phase 0：遗留修复（4 任务，文件互不相交，可并行派发）

### Task 1：reranker 有界 executor + torch 限线程

**Files**: Modify `backend/services/reranker.py`、`backend/services/runtime_config.py`

**背景**：`reranker.py:217` 用默认线程池跑 `CrossEncoder.predict`，10 并发 × torch intra-op 12 线程 = 120 线程挤 12 核（p50 86% 来源），且 Windows 下偶发 c10.dll APPCRASH。

**Step 1** `reranker.py` 模块级（`logger = init_logger(__name__)` 之后）加：

```python
# Stage 4 压测复验 §9.1/§9.3：默认线程池并发 predict 导致 torch intra-op 线程
# 超订阅（10 并发 × ~12 线程挤 12 物理核）+ Windows c10.dll 偶发崩溃
# （"predict 只读推理多线程安全"的旧假设已被实测证伪）。
# 治理：专用有界线程池 + torch.set_num_threads 硬预算。
import concurrent.futures

_RERANK_EXECUTOR = None
_EXECUTOR_LOCK = None  # threading.Lock，延迟创建


def _get_rerank_executor():
    """懒创建专用有界线程池（worker 数与 torch 线程数可热调）。"""
    global _RERANK_EXECUTOR, _EXECUTOR_LOCK
    import threading
    if _EXECUTOR_LOCK is None:
        _EXECUTOR_LOCK = threading.Lock()
    with _EXECUTOR_LOCK:
        if _RERANK_EXECUTOR is None:
            workers = int(get_runtime("RERANK_MAX_CONCURRENCY", 1))
            try:
                import torch
                torch.set_num_threads(int(get_runtime("RERANK_TORCH_THREADS", 8)))
            except ImportError:
                pass  # sentence_transformers 不可用时反正走不到 predict
            _RERANK_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="rerank")
            logger.info(
                f"[Reranker] 专用线程池就绪: workers={workers}, "
                f"torch_threads={get_runtime('RERANK_TORCH_THREADS', 8)}"
            )
    return _RERANK_EXECUTOR


def reset_rerank_executor():
    """热调参数后重建线程池（在途任务不等待，自然排空）。"""
    global _RERANK_EXECUTOR
    if _RERANK_EXECUTOR is not None:
        _RERANK_EXECUTOR.shutdown(wait=False)
        _RERANK_EXECUTOR = None
        logger.info("[Reranker] 线程池已重置，下次调用按新参数重建")
```

**Step 2** `rerank()` 方法内（约 216-217 行）替换：

```python
            # 旧代码（删除）：
            # loop = asyncio.get_running_loop()
            # scores = await loop.run_in_executor(None, model.predict, pairs)
            # 新代码：
            loop = asyncio.get_running_loop()
            scores = await loop.run_in_executor(_get_rerank_executor(), model.predict, pairs)
```

同时**删除/改写 212-215 行的错误注释**（"CrossEncoder.predict 为只读推理……多线程并发调用安全"），替换为：
```python
            # predict 放入专用有界线程池（RERANK_MAX_CONCURRENCY × RERANK_TORCH_THREADS
            # 乘积须 ≤ 物理核数，防超订阅与 c10.dll 并发崩溃——Stage 4 复验实测教训）
```

**Step 3** `runtime_config.py`：
- `GROUPS` 加 `"cache": "缓存配置",`（Phase 1 Task 10 会用，先占位亦可）。
- `WRITABLE_CONFIGS` 的 retrieval 组加：

```python
    "RERANK_MAX_CONCURRENCY": {
        "group": "retrieval",
        "type": "int", "min": 1, "max": 8,
        "label": "Rerank 并发数",
        "description": "rerank 专用线程池 worker 数（与 torch 线程数乘积≤物理核数，防超订阅）",
    },
    "RERANK_TORCH_THREADS": {
        "group": "retrieval",
        "type": "int", "min": 1, "max": 16,
        "label": "Rerank torch 线程数",
        "description": "单次 predict 的 torch intra-op 线程预算",
    },
```

- `_APPLY_HANDLERS` 加：
```python
    "RERANK_MAX_CONCURRENCY": lambda st: _reset_rerank_pool(),
    "RERANK_TORCH_THREADS": lambda st: _reset_rerank_pool(),
```
并在 `_reset_reranker` 函数附近加：
```python
def _reset_rerank_pool() -> None:
    """热调 rerank 线程预算后重建专用线程池。"""
    from services.reranker import reset_rerank_executor
    reset_rerank_executor()
```

**验证**：`backend\.venv\Scripts\python.exe -c "from services.reranker import _get_rerank_executor; e=_get_rerank_executor(); print('executor ok', e._max_workers)"`（在 backend 目录下跑）。

### Task 2：MilvusClient.aquery() + api/search.py 调用点替换

**Files**: Modify `backend/services/milvus_client.py`、`backend/api/search.py`

**背景**：`api/search.py` 的 async 路由同步调 `milvus_client.query()`（内含 `milvus_client.py:703` 同步 `embed_query` HTTP + 同步 pymilvus search），每请求 ~5-8s 串行整个事件循环。

**注意**：`agent/claw_agent/tools/rag_tools.py:116` 也是同步调用，但该处是同步 `@tool`（LangGraph 在 worker 线程执行，不阻塞事件循环），**不改**，只加一行注释说明。

**Step 1** `milvus_client.py`：确认文件顶部是否已 `import asyncio`（大概率没有，加上）。在 `query()` 方法定义之后加：

```python
    async def aquery(self, query_text, limit=5, metadata_filter=None, retrieval_mode="advanced"):
        """query() 的异步包装：整体移出事件循环（含同步 embed_query HTTP +
        同步 pymilvus search，每请求 ~5-8s 同步段——Stage 4 复验 §9.2）。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.query(
                query_text=query_text,
                limit=limit,
                metadata_filter=metadata_filter,
                retrieval_mode=retrieval_mode,
            ),
        )
```

**Step 2** `api/search.py` 两处调用替换：
- `_milvus_search()`（约 127 行）：`return milvus_client.query(` → `return await milvus_client.aquery(`
- `/milvus/query` 端点（约 188 行）：`raw_results = milvus_client.query(` → `raw_results = await milvus_client.aquery(`

**Step 3** `rag_tools.py` 116 行附近加注释（不改逻辑）：
```python
            # 注：此处保持同步 query()——本工具是同步 @tool，LangGraph 在 worker
            # 线程执行，不阻塞事件循环；L1 embedding 缓存（文档 08）同样生效于此。
```

**验证**：启动后端后 `curl -X POST http://127.0.0.1:8003/api/search/milvus/query ...`（带 token）跑一次确认 200；并发 2 个请求时 `/healthz` 不被卡住（`curl http://127.0.0.1:8003/healthz -m 2` 秒回）。

### Task 3：faq.promote 埋点补 user_id

**Files**: Modify `backend/services/faq_service.py:309`

**Step 1**: 阈值升格处的 audit.log 补 user_id（faq 表有 `submitter_id`/`owner_id` 列，阈值升格无请求上下文，取 `submitter_id`——答案贡献者）：

```python
            ok = db.promote_faq(faq_id, answer=distilled)
            if ok:
                audit.log("faq.promote", user_id=faq.get("submitter_id"),
                          resource_type="faq", resource_id=faq_id,
                          kb_id=faq["kb_id"],
                          detail={"via": "threshold", "hit_count": faq["hit_count"],
                                  "before": old_answer[:300], "after": distilled[:300]})
```

先确认 `db.get_faq` 返回的 dict 含 `submitter_id`（faq 表有该列，SELECT * 应返回；若不含则改用 `owner_id` 并在提交信息注明）。

**验证**：grep 确认无其他 faq.* 埋点漏 user_id：`rg "audit.log\(\"faq\." backend/services/faq_service.py` 逐个核对。

### Task 4：start_all.ps1/.sh 开关（milvus 默认不拉 / redis 默认拉）

**Files**: Modify `start_all.ps1`、`start_all.sh`

**Step 1** `start_all.ps1`：
- param 块加：
```powershell
    [switch]$StartMilvus,   # 显式开关：拉起本地 milvus 容器（检索默认走 Zilliz，本地容器在 15.6GB 机器上是纯内存负担）
    [switch]$NoRedis        # 显式关闭：不拉 redis 容器（缓存层依赖，默认拉起）
```
- `"start"` 分支 `Ensure-Milvus` 改为 `if ($StartMilvus) { Ensure-Milvus } else { Write-Host "[milvus] 跳过（默认不拉本地容器；需要时加 -StartMilvus）" -ForegroundColor DarkGray }`
- 新增 `Ensure-Redis` 函数（放在 Ensure-Milvus 后）：
```powershell
function Ensure-Redis {
    Write-Host "[redis] 检查 rag-redis 容器..." -ForegroundColor Cyan
    try {
        $running = docker ps --filter "name=rag-redis" --format "{{.Names}}" 2>$null
        if ($running) { Write-Host "[redis] rag-redis 运行中" -ForegroundColor Green; return }
        $existing = docker ps -a --filter "name=rag-redis" --format "{{.Names}}" 2>$null
        if ($existing) {
            docker start rag-redis | Out-Null
        } else {
            docker run -d --name rag-redis -p 6379:6379 redis:7-alpine --maxmemory 128mb --maxmemory-policy allkeys-lru | Out-Null
        }
        Write-Host "[redis] rag-redis 已启动（128MB 硬顶）" -ForegroundColor Green
    } catch {
        Write-Host "[redis] 启动失败（Docker 未运行？缓存将降级内存模式）: $($_.Exception.Message)" -ForegroundColor Red
    }
}
```
- `"start"` 分支在 `Start-Backend` 之前加：`if (-not $NoRedis) { Ensure-Redis }`
- `Show-Status` 里加 redis 状态显示（照 milvus 样式）。

**Step 2** `start_all.sh` 同逻辑：`--milvus` 开启才拉 milvus、默认拉 redis（`--no-redis` 关闭）、redis 容器命令同上。

**验证**：`powershell -File start_all.ps1 status` 输出含 redis 行；`start` 不再出现 milvus 启动字样。

---

## Phase 1：缓存核心（Task 5→6 串行；7/8/9 依赖 5+6 后可并行；10 收尾）

### Task 5：PG schema + db 层方法

**Files**: Modify `backend/services/database.py`（先通读该文件的 cursor/commit/单例惯例再动手）

**Step 1** `_create_tables` 中（faq 表建表语句附近）加：

```python
            # ── 文档 08：缓存相关 ──
            # L1 查询 embedding 缓存（持久层；embedding 是纯函数，无需失效逻辑）
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS query_embedding_cache (
                    query_hash TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    model TEXT NOT NULL,
                    embedding JSONB NOT NULL,
                    hit_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_hit_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # L2 版本号失效：KB 内容变更 → cache_version+1 → 旧缓存 key 自动失配
            self.cursor.execute('''
                ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 0
            ''')
```

**Step 2** `Database` 类新增方法（遵循该类既有 commit 惯例；全部包 try/except 返回安全值——缓存路径失败必须 fail-open 不影响主流程）：

```python
    # ---------- 文档 08：缓存版本号 ----------

    def bump_kb_cache_version(self, kb_id) -> int:
        """KB 内容变更后 bump 版本（旧缓存 key 自动失配）。返回新版本号。"""
        try:
            self.cursor.execute(
                "UPDATE knowledge_base SET cache_version = cache_version + 1 WHERE id = %s RETURNING cache_version",
                (kb_id,))
            row = self.cursor.fetchone()
            self.conn.commit()
            return row[0] if row else 0
        except Exception as e:
            try: self.conn.rollback()
            except Exception: pass
            logger.error(f"bump_kb_cache_version 失败(kb={kb_id}): {e}")
            return -1

    def get_kb_cache_versions(self, kb_ids) -> dict:
        """批量取 KB 版本号 → {kb_id: version}（L2 key 版本维度）。"""
        try:
            ids = [int(k) for k in kb_ids if k is not None]
            if not ids:
                return {}
            self.cursor.execute(
                "SELECT id, cache_version FROM knowledge_base WHERE id = ANY(%s)", (ids,))
            return {str(r[0]): r[1] for r in self.cursor.fetchall()}
        except Exception as e:
            logger.error(f"get_kb_cache_versions 失败: {e}")
            raise  # key 构造侧捕获后跳过缓存（fail-open）

    def get_user_cache_scope_version(self, user_id) -> int:
        """用户可见域（自有+被分享 KB）的最大版本号（无 KB 过滤的全局检索 key 用）。"""
        self.cursor.execute('''
            SELECT COALESCE(MAX(cache_version), 0) FROM knowledge_base
            WHERE user_id = %s OR id IN (
                SELECT knowledge_base_id FROM user_kb_permission WHERE user_id = %s)
        ''', (user_id, user_id))
        return self.cursor.fetchone()[0]

    def get_global_cache_version(self) -> int:
        """全局最大版本号（admin 无过滤检索 key 用）。"""
        self.cursor.execute("SELECT COALESCE(MAX(cache_version), 0) FROM knowledge_base")
        return self.cursor.fetchone()[0]

    # ---------- 文档 08：L1 查询 embedding 缓存 ----------

    def get_query_embedding(self, query_hash):
        """L1 命中返回向量 list，miss 返回 None。"""
        self.cursor.execute(
            "SELECT embedding FROM query_embedding_cache WHERE query_hash = %s", (query_hash,))
        row = self.cursor.fetchone()
        if row is None:
            return None
        vec = row[0] if isinstance(row[0], list) else json.loads(row[0])
        self.cursor.execute(
            "UPDATE query_embedding_cache SET hit_count = hit_count + 1, last_hit_at = NOW() WHERE query_hash = %s",
            (query_hash,))
        self.conn.commit()
        return vec

    def put_query_embedding(self, query_hash, query_text, model, embedding):
        """L1 写入（冲突时覆盖——同 hash 同内容，幂等）。"""
        self.cursor.execute('''
            INSERT INTO query_embedding_cache (query_hash, query_text, model, embedding)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (query_hash) DO UPDATE SET last_hit_at = NOW()
        ''', (query_hash, query_text, model, json.dumps(embedding)))
        self.conn.commit()
```

（`json` 未导入则补 import。）

**Step 3** 写一个 `work/stage-cache/verify_task5.py`：连库后依次调 bump/get_kb_cache_versions/get_user_cache_scope_version/get_global_cache_version/get_query_embedding/put_query_embedding，打印断言结果（如 bump 两次 version 递增；put 后 get 返回同向量）。

**验证**：跑 verify_task5.py 全部断言通过。

### Task 6：services/cache.py — CacheManager

**Files**: Create `backend/services/cache.py`

完整实现（可直接采用，注意保持与设计文档 §2.4 术语一致）：

```python
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
    """过滤条件归一化：dict → 按 key 排序的 [[k, v], ...]，列表值排序。"""
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
        """Redis 故障降级日志（每轮故障只打一次 + 审计）。"""
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
                return {"kb": db.get_kb_cache_versions(list(kb_ids))}
            if kb_id is not None:
                return {"kb": db.get_kb_cache_versions([kb_id])}
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

    # ---------- L2 读写（内存 → Redis 两级，双写） ----------

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
                        self._insert_mem(key, value, len(raw), now + self._ttl(), None)
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
        任何异常 fail-open 到直算。"""
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
            (self.counters["l2_mem_hit"] + self.counters["l2_redis_hit"]) / l2_total, 4) if l2_total else None
        l1_total = self.counters["l1_hit"] + self.counters["l1_miss"]
        out["l1_hit_rate"] = round(self.counters["l1_hit"] / l1_total, 4) if l1_total else None
        if self._backend() == "redis" and out["redis_ok"]:
            try:
                info = self._redis_client().info("memory")
                dbsize = self._redis_client().dbsize()
                out["redis_used_memory"] = info.get("used_memory_human")
                out["redis_keys"] = dbsize
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
                        ttl = self._redis_client().ttl(k)
                        out.append({"key": k, "ttl_left": max(0, ttl)})
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
            db.cursor.execute("DELETE FROM query_embedding_cache")
            db.conn.commit()

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
```

**Step 2** 写 `work/stage-cache/verify_task6.py`：不开服务直接测纯逻辑——key 归一化（`[17,23]` vs `[23,17]` 同 key；dict 乱序同 key）、TTL 过期淘汰、双上限逐出、`CACHE_BACKEND=off` 短路、embed_cached 的 fail-open（mock db 抛异常仍返回直算结果）。用 `os.environ` 注入 runtime 再 `get_cache_manager()`（注意单例——测多个场景用 `cache._manager = None` 重置或直接 new CacheManager）。

**验证**：verify_task6.py 全过。

### Task 7：L1 接入 milvus_client.query()

**Files**: Modify `backend/services/milvus_client.py`（`query()` 方法内，约 696-703 行）

**Step 1** 替换 embedding 生成段：

```python
        # 生成查询嵌入（文档 08 L1：PG 缓存命中免远程 HTTP 往返）
        from langchain_openai import OpenAIEmbeddings
        embedding_model = OpenAIEmbeddings(
            model=get_runtime("EMBEDDING_MODEL", settings.EMBEDDING_MODEL),
            api_key=get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY),
            base_url=get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL),
        )
        from services.cache import get_cache_manager
        model_name = get_runtime("EMBEDDING_MODEL", settings.EMBEDDING_MODEL)
        query_embedding = [get_cache_manager().embed_cached(
            query_text, model_name, embedding_model.embed_query)]
```

**验证**：同一 query 调两次 `milvus.query()`，第二次日志无 embedding HTTP 请求痕迹/明显变快；PG `SELECT count(*) FROM query_embedding_cache` 增 1、`hit_count` 增 1。

### Task 8：L2 接入检索端点（api/search.py ×3 + rag_tools.py）

**Files**: Modify `backend/api/search.py`、`backend/agent/claw_agent/tools/rag_tools.py`

**通用模式**（每个端点一致；插入位置 = 权限校验之后、真实检索之前）：

```python
        # ── 文档 08 L2：检索结果缓存（权限闸门之后、真实检索之前）──
        from services.cache import get_cache_manager
        cm = get_cache_manager()
        cache_key = cm.build_search_key(
            query=request.query, filt=metadata_filter,
            mode=request.retrieval_mode, limit=effective_limit,
            use_rerank=request.use_rerank)
        cached = cm.get(cache_key)
        if cached is not None:
            return {"status": "success", "query": request.query,
                    "results": cached, "cached": True}
```

检索成功返回前：
```python
        cm.set(cache_key, results, meta={
            "kb_id": request.knowledge_base_id, "mode": request.retrieval_mode,
            "limit": effective_limit, "rerank": request.use_rerank})
```

**注意**：`metadata_filter` 必须是**构建后的过滤条件**（`_build_metadata_filter` 的输出），不是 request 原始字段——这是 key 铁律（生效过滤条件进 key）。

**Step 1** `/milvus/query` 端点（`api/search.py` ~188 行）：`_check_kb_access` + `metadata_filter = _build_metadata_filter(...)` 之后插入 get 段；`return` 前插入 set 段。
**Step 2** `/elasticsearch/search` 端点：同样模式，filt 用 `_build_es_filters(request)`（注意 ES filters 不含 user_id——BM25/ES 的 user 隔离走 search_client.search 的 user_id 参数。为 key 隔离安全，把 `{"user_id": current_user["id"]}` 并进 filt 传给 build_search_key——**key 的过滤材料必须与检索实际生效范围一致**，ES 路实际按 user_id 隔离了（search(user_id=...)），所以 key 里必须有）。
**Step 3** `/hybrid/search` 端点：`_check_kb_access` 之后、`asyncio.gather` 之前插入；filt = milvus 路 metadata_filter 与 es filters 的并集语义（用 `_build_metadata_filter` 输出，它含 user_id/kb_id，是更完整的生效范围描述）。set 段在 reranked 之后。
**Step 4** `rag_tools.py` `rag_hybrid_search`：kb_filter 解析完成（~104 行）后插入 get 段（key 的 extra 带 `{"vv": use_vector, "kw": use_keyword, "rk": use_rerank, "rk_k": rerank_top_k}`——这些参数影响结果必须进 key）；命中则直接 `json.dumps({"results": cached, "total_count": len(cached)}, ensure_ascii=False)` 返回（保持工具返回格式）。结果组装完成后 set。该函数是同步函数，cache get/set 都是同步的，无阻塞问题。

**验证**：`work/stage-cache/verify_task8.py`——登录→同一 query 打 `/api/search/milvus/query` 两次，第二次响应含 `"cached": true` 且延迟骤降；改 `CACHE_BACKEND=off`（PUT /api/settings）后 `"cached"` 不再出现。

### Task 9：写路径 bump 接入

**Files**: Modify `backend/api/processing.py`、`backend/api/documents.py`、`backend/services/faq_service.py`

**统一模式**（每个 bump 点）：

```python
        from services.cache import get_cache_manager
        new_v = db.bump_kb_cache_version(kb_id)
        if new_v >= 0:
            get_cache_manager().record_version_bump()
            audit.log("cache.version_bump", user_id=..., kb_id=kb_id,
                      detail={"reason": "...", "new_version": new_v})
```

（audit 调用形态参照各文件已有埋点写法——processing.py 用 `audit.log_from_request(request, ...)`，faq_service 用 `audit.log(...)`。）

**bump 点清单**（kb_id 来源与插入位置均已核实）：

1. `processing.py` `split_document()`（~194 行 chunks 写 PG + BM25 索引后）：reason="split"，kb_id=`doc["knowledge_base_id"]`。**split 阶段 BM25 已可见新内容，必须 bump**。
2. `processing.py` `import_to_milvus()`（~697-701 行 `db.update_document(status="completed")` 成功后）：reason="import"，kb_id=`doc["knowledge_base_id"]`。注意两个幂等早退分支（~583-607 已 completed、~710-713）**不 bump**（内容未变）。
3. `documents.py` `delete_document()`（~218 行 `db.delete_document(file_id)` 成功后）：reason="doc_delete"，kb_id=`doc["knowledge_base_id"]`。
4. `faq_service.py`：promote 成功处（~307）、demote、delete FAQ、补全直写写回、`merge_pr` merged 分支——**先 grep `db.promote_faq|db.demote_faq|db.delete_faq|insert_faq_vector|resolve_faq_pr` 定位全部写点**，每个成功分支 bump（reason 分别为 "faq_promote"/"faq_demote"/"faq_delete"/"faq_writeback"/"faq_pr_merge"，kb_id 取 `faq["kb_id"]` 或 `pr["target_kb_id"]`）。
5. KB 删除/克隆：**不 bump**（删除后行已消失；克隆出的新 KB version=0 天然全新）。

**验证**：`work/stage-cache/verify_task9.py`——导入一篇小文档前后 `SELECT cache_version FROM knowledge_base WHERE id=X` 递增；对 X 做过的缓存查询，导入后再查响应无 `"cached": true`（版本失效生效）。

### Task 10：装配（runtime_config + lifespan + 依赖 + 容器）

**Files**: Modify `backend/services/runtime_config.py`、`backend/app.py`、`backend/requirements.txt`、`backend/pyproject.toml`（如有依赖节）

**Step 1** `requirements.txt` 加 `redis>=5.0.0`，并安装：`backend\.venv\Scripts\pip.exe install redis>=5.0.0`（网络问题用 `--index-url https://pypi.org/simple`）。

**Step 2** `runtime_config.py`：GROUPS 已有 "cache"（Task 1 加过）；WRITABLE_CONFIGS 加：

```python
    # ── 缓存配置（文档 08，立即生效） ──
    "CACHE_BACKEND": {
        "group": "cache", "type": "enum", "enum": ["off", "memory", "redis"],
        "label": "缓存后端",
        "description": "off=关闭 / memory=仅进程内存 / redis=内存+Redis 两级（故障自动降级 memory）",
    },
    "CACHE_TTL_SECONDS": {
        "group": "cache", "type": "int", "min": 30, "max": 86400,
        "label": "缓存 TTL（秒）",
        "description": "检索结果缓存基础过期时间（自动叠加 0-120s 随机抖动防雪崩）",
    },
    "CACHE_MEM_MAX_ENTRIES": {
        "group": "cache", "type": "int", "min": 1, "max": 10000,
        "label": "内存缓存条目上限",
        "description": "进程内存 LRU 条目数上限（立即生效）",
    },
    "CACHE_MEM_MAX_MB": {
        "group": "cache", "type": "int", "min": 1, "max": 512,
        "label": "内存缓存字节上限（MB）",
        "description": "进程内存 LRU 总字节上限（立即生效）",
    },
    "CACHE_EMPTY_TTL_SECONDS": {
        "group": "cache", "type": "int", "min": 0, "max": 3600,
        "label": "空结果 TTL（秒）",
        "description": "空结果短过期（防穿透），0=不缓存空结果",
    },
    "REDIS_URL": {
        "group": "cache", "type": "str",
        "label": "Redis 地址",
        "description": "redis://host:port/db，切换后重建缓存管理器连接",
    },
```

`_APPLY_HANDLERS` 加（REDIS_URL 变更后重置 Redis 客户端）：
```python
    "REDIS_URL": lambda st: _reset_cache_redis(),
```
```python
def _reset_cache_redis() -> None:
    """热改 REDIS_URL 后重置缓存 Redis 连接。"""
    from services.cache import get_cache_manager
    cm = get_cache_manager()
    cm._redis = None
    cm._redis_ok = None
    logger.info("[RuntimeConfig] 缓存 Redis 连接已重置")
```

**Step 3** `app.py` lifespan：`audit.start()` 之后加：

```python
    # ── 缓存管理器（文档 08）：启动 stats 快照任务 ──
    from services.cache import get_cache_manager
    _cache_snapshot_task = asyncio.create_task(
        get_cache_manager().stats_snapshot_loop())
    logger.info("[Cache] 缓存管理器已启动（stats 快照 60s 周期）")
```

`yield` 之后（`await audit.stop()` 前后）加：
```python
    _cache_snapshot_task.cancel()
```

**Step 4** 确认 Redis 容器已跑（Task 4 的 start_all 或手动）：`docker run -d --name rag-redis -p 6379:6379 redis:7-alpine --maxmemory 128mb --maxmemory-policy allkeys-lru`。

**验证**：启动后端，日志出现 `[Cache] 缓存管理器已启动`；60s 后 audit_log 表出现 `cache.stats` 事件。

---

## Phase 2：可观测（Task 11 → 12）

### Task 11：api/cache.py 端点

**Files**: Create `backend/api/cache.py`、Modify `backend/api/__init__.py`

**Step 1** `api/cache.py`（admin-only，复刻 audit.py 的 403 先例）：

```python
"""缓存中心 API（文档 08 §3.1）— 仅管理员"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from services.auth import get_current_user
from services.database import db
from config import init_logger

logger = init_logger(__name__)
router = APIRouter()


def _require_admin(current_user):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看缓存中心")


@router.get("/stats")
async def cache_stats(current_user=Depends(get_current_user)):
    """各层计数器/命中率/内存估算/Redis INFO 摘要 + L1 PG 侧统计。"""
    _require_admin(current_user)
    from services.cache import get_cache_manager
    out = get_cache_manager().stats()
    try:
        db.cursor.execute(
            "SELECT count(*), COALESCE(sum(hit_count),0) FROM query_embedding_cache")
        row = db.cursor.fetchone()
        out["l1_entries"], out["l1_total_hits"] = row[0], row[1]
    except Exception as e:
        out["l1_error"] = str(e)
    return {"status": "success", "stats": out}


@router.get("/entries")
async def cache_entries(layer: str = "mem", limit: int = 50, kb_id: Optional[int] = None,
                        q: str = None, current_user=Depends(get_current_user)):
    """条目明细（layer=mem/redis/l1）。kb_id/q 过滤仅对有 meta 的内存层生效。"""
    _require_admin(current_user)
    from services.cache import get_cache_manager
    cm = get_cache_manager()
    if layer == "l1":
        try:
            db.cursor.execute(
                "SELECT query_hash, left(query_text, 60) AS q, model, hit_count, last_hit_at "
                "FROM query_embedding_cache ORDER BY last_hit_at DESC LIMIT %s", (limit,))
            items = [{"query_hash": r[0], "query": r[1], "model": r[2],
                      "hits": r[3], "last_hit_at": str(r[4])} for r in db.cursor.fetchall()]
        except Exception as e:
            items = [{"error": str(e)}]
        return {"status": "success", "layer": "l1", "items": items}
    items = cm.entries(layer=layer, limit=limit)
    if kb_id is not None:
        items = [i for i in items if (i.get("meta") or {}).get("kb_id") == kb_id]
    if q:
        items = [i for i in items if q.lower() in str(i.get("meta", {}).get("kb_id", "")) + i["key"]]
    return {"status": "success", "layer": layer, "items": items}


@router.get("/entries/{key_hash}")
async def cache_entry_detail(key_hash: str, current_user=Depends(get_current_user)):
    """单条完整内容：Top-K chunk 明细 + 命中时间线。"""
    _require_admin(current_user)
    from services.cache import get_cache_manager
    detail = get_cache_manager().get_entry_detail(key_hash)
    if detail is None:
        raise HTTPException(status_code=404, detail="缓存条目不存在或已过期")
    return {"status": "success", "key": key_hash, **detail}


class InvalidateRequest(BaseModel):
    kb_id: int


@router.post("/invalidate")
async def cache_invalidate(body: InvalidateRequest, current_user=Depends(get_current_user)):
    """按 KB 失效（bump cache_version，等于内容变更的手动版）。"""
    _require_admin(current_user)
    kb = db.get_knowledge_base(body.kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    new_v = db.bump_kb_cache_version(body.kb_id)
    from services.audit import audit
    audit.log("cache.invalidate", user_id=current_user["id"], kb_id=body.kb_id,
              detail={"via": "api", "new_version": new_v})
    return {"status": "success", "kb_id": body.kb_id, "new_version": new_v}


class ClearRequest(BaseModel):
    layer: str  # mem | redis | l1


@router.post("/clear")
async def cache_clear(body: ClearRequest, current_user=Depends(get_current_user)):
    """清空某层。"""
    _require_admin(current_user)
    if body.layer not in ("mem", "redis", "l1"):
        raise HTTPException(status_code=400, detail="layer 须为 mem/redis/l1")
    from services.cache import get_cache_manager
    get_cache_manager().clear(body.layer)
    from services.audit import audit
    audit.log("cache.clear", user_id=current_user["id"],
              detail={"layer": body.layer})
    return {"status": "success", "layer": body.layer}
```

**Step 2** `api/__init__.py`：
```python
from .cache import router as cache_router
...
api_router.include_router(cache_router, prefix="/cache", tags=["cache"])
```

**验证**：admin token 打 `GET /api/cache/stats` 得 200 带 counters；普通用户得 403。

### Task 12：前端缓存中心页

**Files**: Create `frontend/js/pages/cache.js`、Modify `frontend/index.html`、`frontend/js/app.js`（页面注册方式先读 audit.js/index.html/app.js 现有模式再照抄）

**实现要求**（子 agent 必读 `frontend/js/pages/audit.js` 作为骨架模板 + 记忆中的 UI 铁律）：

1. **入口**：侧栏导航加"缓存中心"（仅 admin 可见，参照 audit 入口的权限控制方式）；
2. **总览卡片**：L1（PG）/ L2 内存 / L2 Redis 三块——各自命中率、条目数、逐出数；`/api/cache/stats` 轮询 10s 刷新；
3. **明细表**：layer 切换 tab（内存/Redis/L1），列：query 摘要/meta.kb_id/模式/命中数/大小/剩余 TTL；行操作 [查看]；
4. **查看抽屉**：浮层（fixed 全屏遮罩 + blur + z-index 60+，点遮罩/Esc 关闭——UI 铁律）展示该条目的 Top-K chunk 列表（content 截断 + score/rerank_score）+ 命中时间线；
5. **管理动作**：[按 KB 失效]（弹 `window.UI.prompt` 输 kb_id → POST invalidate）、[清空某层]（`window.UI.confirm` 确认后 POST clear，用 `App.showLoading/hideLoading` 持续遮罩）；
6. **禁用** `confirm/prompt/alert` 原生对话框；
7. **样式**：main.css 裸类名陷阱——所有布局容器必须 inline style 显式声明 flex/grid；表单控件复用显式强化对比度方案；
8. **收尾**：index.html 相关 `?v=` 全部 bump。

**验证**：浏览器登录 admin → 缓存中心页可见三卡片数据；先打两次同一检索 → 刷新页面命中率 > 0；点 [查看] 抽屉显示 chunk 内容；[清空内存层] 后条目归零。

---

## Phase 3：验收（主 agent 执行，脚本落 work/stage-cache/）

### Task 13：A/B 实验 + 报告

**前置**：本地 milvus 容器已停（`docker stop milvus-attu milvus-etcd milvus-minio milvus-standalone`，内存铁律）；litellm 栈保留。

1. **基线轮**：`CACHE_BACKEND=off`，复用 `work/stage-4/loadtest-reattack/rerank_ab.py` 参数（native 40@10 rerank 开）→ Phase 0 修复后的干净基线；
2. **预热轮 + 测量轮**：`CACHE_BACKEND=redis`，同参数两轮（重复 query 场景命中率应 ~100%）；
3. **混合轮**：50% 重复 + 50% 新 query 的脚本（改 rerank_ab.py 加 query 池）；
4. **权限安全用例**（一票否决，全部必须过）：无权用户查 KB → 403；共享 KB 两用户同查询 → 均命中（第二次 cached:true）；移出分享后 → 403；KB 导入新文档后同查询 → miss（版本失效）；Agent 全局检索被新分享 KB 后 → key 变化 miss；
5. **降级韧性**：`docker stop rag-redis` → 服务不 crash、检索继续、audit 有 `cache.degrade`；
6. **报告**：`docs/plans/stage-cache-report.md`，含四「真实」对账。

---

## 任务派发顺序总结

| 批次 | 任务 | 并行性 |
|---|---|---|
| 1 | Task 1-4（Phase 0） | 4 任务文件不相交，**并行** |
| 2 | Task 5（schema/db） | 单发 |
| 3 | Task 6（CacheManager） | 单发 |
| 4 | Task 7/8/9（接入） | 文件不相交，**并行**（依赖 5+6） |
| 5 | Task 10（装配） | 单发 |
| 6 | Task 11（API）→ Task 12（前端） | 11 完成后 12 |
| 7 | Task 13（验收） | 主 agent 执行 |
