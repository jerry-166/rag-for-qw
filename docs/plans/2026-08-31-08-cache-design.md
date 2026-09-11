# 设计文档 08：三层缓存架构 + Stage 4 遗留修复

> 状态：已与用户逐点确认 | 日期：2026-08-31
> 上游：`stage-4-report.md` §九遗留问题 + `2026-08-31-rag-benchmark-comparison.md` §八建议
> 分支：`feature/stage-cache`（新建，main 不污染）
> 动机备注：用户简历已写 Redis 缓存层，本迭代将代码追上简历叙述；同时解决压测暴露的 P0/P1 遗留，形成干净基线后再上缓存，保证 A/B 数据不被已知瓶颈污染。

## 0. 决策记录（本轮会话定案）

| # | 事项 | 决策 |
|---|---|---|
| 1 | 缓存范围 | L1 查询 embedding + L2 检索结果（**不做** L3 答案缓存/语义缓存——语义匹配交给已有 FAQ 闭环，它有审核闸门） |
| 2 | 失效策略 | KB 版本号 bump（精确失效）+ TTL 兜底 |
| 3 | 遗留修复范围 | 只修 P0+P1；import 批量化（P2）留下一迭代 |
| 4 | Redis | **引入**（原倾向不引入，因简历已投翻转为做）——内存 LRU / Redis / PG 三层 |
| 5 | 可观测 | 缓存中心页面（admin），命中率/明细/管理动作全可见 |

### 0.1 术语对齐（本次讨论中用户澄清过的概念）

- **L1 = 缓存 query 的向量**：精确匹配（同 query 同模型），省远程 embedding HTTP（~0.6-1.2s）；
- **L2 = 缓存检索结果 Top-K**：精确匹配，命中省 embedding+检索+rerank 全链路（rerank 开时 ~70s → 亚毫秒）；
- **版本号失效 ≠ 乐观锁**：是"改名字让旧缓存 key 永远失配"的失效手段，替代"更新时删除缓存"，无删除竞态；
- **缓存 key 的权限维度 = 生效过滤条件（归一化后）**，不是 user_id、不是分享名单——"谁能查"由权限闸门管（在缓存查找之前），"查到什么"才进 key。

## 1. Phase 0：遗留修复（先行，出干净基线）

### 1.1 P0-1 reranker 并发治理（c10.dll 崩溃 + 86% p50）

**现状**：`reranker.py:217` `run_in_executor(None, model.predict, pairs)` 用默认线程池，10 并发 × torch intra-op 12 线程 = 120 线程挤 12 核；且 Windows/torch 下并发 predict 偶发 APPCRASH（c10.dll 0xc0000005）。

**修法**：专用有界 executor 替代默认池，线程预算硬约束：

```python
# reranker.py 模块级
import torch, concurrent.futures
_RERANK_EXECUTOR = None  # 懒创建

def _get_executor():
    global _RERANK_EXECUTOR
    if _RERANK_EXECUTOR is None:
        workers = int(get_runtime("RERANK_MAX_CONCURRENCY", 1))
        torch.set_num_threads(int(get_runtime("RERANK_TORCH_THREADS", 8)))
        _RERANK_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="rerank")
    return _RERANK_EXECUTOR

# rerank() 内替换
scores = await loop.run_in_executor(_get_executor(), model.predict, pairs)
```

- 默认 `1 worker × 8 torch 线程`（最安全，先避崩溃）；稳定后可调 `RERANK_MAX_CONCURRENCY=4 × RERANK_TORCH_THREADS=3`（乘积 ≤ 12 物理核）压吞吐，两个参数进 runtime_config 白名单热调；
- 模型加载锁 `_load_lock` 已有，不动；
- 修正 `reranker.py:212-215` 那段"多线程并发调用安全"的错误注释（实测证伪，避免下个人再踩）。

### 1.2 P0-2 `milvus_client.query()` 整体移出事件循环

**现状**：`api/search.py` 三处 + `agent/claw_agent/tools/rag_tools.py:116` 在 async 路由里同步调 `query()`，其内部 `milvus_client.py:703` 同步 `embed_query` HTTP + 同步 pymilvus search，每请求 ~5-8s 同步段串行整个事件循环。

**修法**：`MilvusClient` 增 async 包装（业务代码只换一行）：

```python
async def aquery(self, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, self.query, **kwargs)
```

调用点替换：`api/search.py` 的 `_milvus_search` 与 `/milvus/query` 端点、`rag_tools.py` 检索调用。`get_collection_info` 等管理接口不动（低频）。

### 1.3 P1-1 `faq.promote` 埋点补 user_id

`faq_service.py:309` audit.log 补 `user_id=faq["created_by"]`（或调用链实际触发者，以表字段为准）。一行。

### 1.4 P1-2 `start_all.ps1` 本地 milvus 开关

- 加 `-StartMilvus` switch（**默认不拉**本地 milvus 容器，检索走 Zilliz）；
- 加 `-StartRedis` switch（**默认拉** redis 容器，Phase 1 依赖，内存预算 128MB 见 §3.3）；
- `start_all.sh` 同步；
- 停 milvus 逻辑对齐（stop 不碰容器，维持现状）。

### 1.5 Phase 0 验收

复用 `work/stage-4/loadtest-reattack/rerank_ab.py`（40@10 native rerank 开）重跑：
- 无崩溃（Windows 事件日志无 c10.dll APPCRASH）；
- p50 显著低于 72s 复验值（预期：串行化后 p50 ≈ 15-35s，最后请求排队 ~30s——如实记录，不硬预测）；
- 事件循环不再被同步段卡死：并发下其他端点（如 /healthz）响应正常。

## 2. Phase 1：缓存核心

### 2.1 架构总览

```
请求 → 权限闸门(403 拦截) → L2 检索结果缓存 ── 命中 → 直接返回 Top-K
                                  │ miss
                                  ▼
                          L1 embedding 缓存(PG) ── 命中 → 跳过远程 embed
                                  │ miss
                                  ▼
                          远程 embed → Zilliz/BM25 检索 → RRF → rerank
                                  │
                                  ▼
                          结果写回 L2（内存 LRU + Redis）
```

| 层 | 介质 | 内容 | 命中开销 | 失效 |
|---|---|---|---|---|
| 内存 LRU | 进程内 | L2 热点子集（默认 256 条/~64MB） | 亚毫秒 | LRU 逐出 + 版本 + TTL |
| Redis | docker 容器 | L2 主体（检索结果 JSON） | ~1ms | allkeys-lru + TTL + 版本 |
| PG | 已有实例 | L1 向量缓存 + BM25 分词缓存（已有） | ~1ms | 无需失效（纯函数） |

`CACHE_BACKEND=off|memory|redis`（runtime_config 白名单，默认 redis；redis 连接失败自动降级 memory 并打审计事件，不 crash——沿用预热失败降级先例）。

### 2.2 L1：查询 embedding 缓存（PG 持久层）

```sql
CREATE TABLE IF NOT EXISTS query_embedding_cache (
    query_hash TEXT PRIMARY KEY,          -- sha256(query_text + model)
    query_text TEXT NOT NULL,
    model TEXT NOT NULL,
    embedding JSONB NOT NULL,             -- float 数组
    hit_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_hit_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- 读写位置：`milvus_client.query()` 内部（Phase 0 后它整体跑在线程池里，同步 PG 访问合法）——embed_query 前先查，miss 则算完回填；
- key 含模型名：换 embedding 模型自动全量失配，无需清理；
- 容量控制：>10 万行时后台任务删 `last_hit_at` 最旧的（低优先级，量大再做）；
- `faq_service` 的 aembed_query 调用点二期接入（非本轮验收路径）。

### 2.3 L2：检索结果缓存（内存 + Redis 两级）

**写入点**：`api/search.py` 各检索端点，权限校验之后、真实检索之前查缓存；`rag_tools.py` 检索路同构接入（agent 全局检索路径）。

**value**：最终 results JSON（含 chunk 内容、score、rerank_score），序列化后存 Redis；内存 LRU 存同一份反序列化对象（免重复 json.loads）。

**读取顺序**：内存 LRU → Redis → 真实检索。写回双写。

**参数（runtime_config 白名单）**：

| 参数 | 默认 | 说明 |
|---|---|---|
| `CACHE_BACKEND` | redis | off/memory/redis |
| `CACHE_TTL_SECONDS` | 600 | + 0-120s 随机抖动防雪崩 |
| `CACHE_MEM_MAX_ENTRIES` | 256 | 内存 LRU 条目上限 |
| `CACHE_MEM_MAX_MB` | 64 | 内存 LRU 字节上限（估算） |
| `CACHE_EMPTY_TTL_SECONDS` | 60 | 空结果短 TTL（防穿透） |

**Redis 容器**：`docker run -d --name rag-redis -p 6379:6379 redis:7-alpine --maxmemory 128mb --maxmemory-policy allkeys-lru`。依赖：`redis-py`（同步客户端即可，调用点已在/将在线程池；连接池复用）。

### 2.4 key 构造规范（本设计的核心纪律）

```
key = "rag:l2:" + sha256(canonical_json)
canonical_json = {
  "q":    query_text,                     # 原文，不归一化大小写（中文场景归一化收益低）
  "f":    归一化生效过滤条件,               # 见下
  "m":    retrieval_mode,
  "k":    effective_limit,
  "r":    use_rerank,
  "v":    版本维度,                        # 见下
}
```

**归一化生效过滤条件**——直接复用已算好的 `_build_metadata_filter` / `_build_es_filters` 结果：

1. dict 按 key 排序、列表元素排序后序列化（`[17,23]` 与 `[23,17]` 同 key）；
2. **指定 KB 查询**：`{"knowledge_base_id": X}` → 版本维度 `{"kb": {"X": version_X}}`。分享名单**不进 key**——"KB 里能查到什么"只取决于内容，不取决于谁能访问；新增被分享者白捡缓存正是共建语义；
3. **Agent 全局检索**（kb_ids 路径）：版本维度 = 排序后的 `{kb_id: version}` 映射（一次 SELECT 拿全，代价可忽略）。可见集合变化（新被分享/被移出）→ key 自动变，自愈；成员 KB 内容更新 → 整组合失配（粒度粗一点，可接受，TTL 兜底）；
4. **无 KB 指定的全局查询**（api/search 默认路径）：过滤含 `user_id` → key 天然按用户隔离；版本维度用该用户全部 KB 的 max(version)（一次聚合查询）。

**铁律**：
- 权限闸门（`check_kb_permission`）必须发生在缓存查找**之前**——被移出分享的用户在 403 就被拦下，永远碰不到缓存；
- 缓存不做访问控制，只是闸门后面的加速表；
- 任何新增检索参数（未来加 filter 字段）必须同步进 canonical_json，否则就是正确性 bug。

### 2.5 版本号失效（写路径 bump 点）

`knowledge_base` 表加列：`ALTER TABLE ... ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 0;`

bump 触发点（db 层封装 `bump_kb_cache_version(kb_id)`，各写路径调用后打审计事件）：

| 写操作 | 位置 | bump 目标 |
|---|---|---|
| 文档导入完成 | import 流程 | 目标 KB |
| 文档/chunk 删除 | delete 流程 | 所属 KB |
| FAQ promote/demote/delete | faq_service | 所属 KB |
| FAQ 补全写回（直写/PR 合并） | faq_service | 所属 KB |
| KB 克隆 | clone 流程 | 目标 KB（新库天然 version=0，源头不变） |

旧条目不删——失配死数据由 Redis TTL/LRU 与内存 LRU 自然回收，无删除竞态（与 01-C"走正常 DB 写接口即自动失效"同哲学）。

### 2.6 新增模块

```
backend/services/cache.py        # CacheManager：key 构造、内存 LRU、Redis 客户端、
                                 # 计数器（hit/miss/evict per layer）、双写、降级
backend/api/cache.py             # 可观测端点（Phase 2）
```

`CacheManager` 接口：`get(key) -> (hit, value)` / `set(key, value, ttl)` / `stats()` / `entries(page)` / `invalidate_kb(kb_id)` / `clear(layer)`。审计事件：`cache.set`（不打每请求 hit/miss，压测下事件量翻倍；命中率从计数器读）、`cache.stats`（60s 周期快照，含各层增量）、`cache.version_bump`、`cache.invalidate`、`cache.degrade`（redis 故障降级）。

## 3. Phase 2：缓存可观测（页面 + API）

### 3.1 后端端点（admin-only，复刻 /api/audit/stats 的 403 先例）

```
GET  /api/cache/stats                    # 各层 hit/miss/evict 计数、条目数、内存估算、
                                         # 窗口命中率、Redis INFO 摘要（used_memory/keys）
GET  /api/cache/entries?layer=&kb_id=&q= # 分页明细：query 摘要/KB/模式/版本/命中数/
                                         # 大小/剩余TTL/所在层（mem/redis/both）
GET  /api/cache/entries/{key_hash}       # 单条完整内容：Top-K chunk 明细（标题/来源/
                                         # 分数）+ 命中时间线（内存侧记录最近 5 次）
POST /api/cache/invalidate {kb_id}       # bump cache_version（手动失效按钮）
POST /api/cache/clear {layer}            # 清空某层
```

### 3.2 前端页面（`js/pages/cache.js`）

- 总览卡片：L1（PG）/L2 内存 /L2 Redis 三块，各显示命中率、条目数、逐出数；
- 明细表：L2 条目列表（过滤 KB/模式/状态），行内 [查看]（抽屉浮层，遵守 UI 铁律：fixed 遮罩 + Esc 关闭，禁 confirm/alert）、[失效]；
- 剩余 TTL 倒计时条；失效条目标注原因（版本/TTL/逐出）；
- 趋势图：近 24h 命中率曲线（数据源 = audit_log 的 cache.stats 快照聚合，复用审计管道）;
- 管理动作用 `App.showLoading` 持续遮罩（长操作铁律）；改前端文件 bump index.html `?v=`。

### 3.3 内存预算（15.6GB 约束下的账）

| 组件 | 预算 | 说明 |
|---|---|---|
| redis 容器 | 128MB 硬顶 | maxmemory 配置，allkeys-lru 兜底 |
| 内存 LRU | ~64MB 软顶 | 条目数 + 字节双上限 |
| 后端进程增量 | <20MB | 缓存对象 + redis 客户端 |
| 合计 | ~210MB | 对照：本地 milvus 容器组 ~4GB+（纯负担），Redis 是真在用的 |

## 4. Phase 3：验收（A/B 实验 + 四个「真实」）

### 4.1 实验设计

1. **基线轮**（Phase 0 后、缓存 off）：复用 `rerank_ab.py` 参数（native 40@10 rerank 开）→ 干净基线；
2. **预热轮**（缓存 on）：同参数跑一遍，让 L1/L2 灌满；
3. **测量轮**：同参数再跑 → 命中率应 ~100%（重复 query 压测场景）；
4. **混合轮**：50% 重复 + 50% 新 query → 真实命中率；
5. **权限安全用例**（必须全过，一票否决）：
   - 用户 B 无 KB X 权限 → 查 KB X → 403（碰不到缓存）；
   - A、B 共享 KB X → 同查询 → B 命中 A 的缓存（计数器可验证）；
   - B 被移出分享 → 再查 → 403；
   - KB X 导入新文档 → 同查询 → miss（版本失效生效）；
   - Agent 全局检索：新被分享 KB → key 变化 → miss 重算。

### 4.2 验收清单

| # | 项 | 判据 |
|---|---|---|
| 1 | 缓存命中延迟 | L2 命中 p50 < 50ms（对照 miss 全链路） |
| 2 | 命中正确性 | 命中结果与实时检索结果逐字段一致（同 KB 版本下检索确定性） |
| 3 | 权限安全 | §4.1-5 用例全过 |
| 4 | 失效正确性 | 版本 bump 后旧 key 永不命中；审计有 version_bump 事件 |
| 5 | 降级韧性 | 停 redis 容器 → 服务不 crash，自动降级 memory，审计有 degrade 事件 |
| 6 | 可观测 | /api/cache/stats 数字与压测对账（hit+miss=请求数）；页面曲线可看 |
| 7 | Phase 0 修复 | §1.5 三项全过 |

### 4.3 四个「真实」预对账

- **真实提高性能**：A/B 数据说话——缓存命中的 p50 降幅 + 命中率，对照 Phase 0 干净基线（不与 8-21 旧数据混比）；
- **真实优化架构**：三层各有职责（内存挡热点/Redis 共享/PG 持久），`CACHE_BACKEND` 可热切换，与 BM25 缓存先例架构语言统一；
- **真实可拓展**：key 规范成文（§2.4），新检索参数进 key 有纪律；Redis 层为多实例部署预留；
- **真实合理**：承认精确缓存命中率依赖查询分布（压测高、开放查询低）；承认全局检索版本粒度粗（TTL 兜底）；面试叙述以实测数据为准。

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| reranker 串行化后并发 p50 仍 ~30s（排队） | 如实记录；验收看"无崩溃 + 事件循环健康"，吞吐提升靠缓存命中分流；worker 池扩容留热调参数 |
| Redis 又一个"本地容器吃内存"陷阱 | 128MB 硬顶 + 真在用（对照 milvus 纯负担）；内存紧张时 `CACHE_BACKEND=memory` 一键退 |
| 压测下审计事件量翻倍 | 不打逐请求 hit/miss，只用 60s 快照 + 计数器 |
| 缓存 value 体积大（Top-K 全文） | 限额序列化长度（>256KB 不入内存层只入 Redis）；条目含 chunk 全文本来就是 L2 的意义 |
| 与 Stage 5 UI 冻结冲突 | cache.js 是新页面非重构，遵守现有 UI 铁律即可，不动旧页面结构 |

## 6. 实施顺序与工作量

| 阶段 | 内容 | 预估 |
|---|---|---|
| Phase 0 | §1 四项修复 + 回归压测 | 0.5-1 天 |
| Phase 1 | L1 + L2 + 版本失效 + key 规范落地 | 1-1.5 天 |
| Phase 2 | 可观测 API + 页面 + 审计快照 | 0.5-1 天 |
| Phase 3 | A/B 实验 + 报告 `stage-cache-report.md` | 0.5 天 |

合计 ~3 天。每 Phase 完成向用户汇报（含数据）再进下一阶段；任何一验收项不达标 → 暂停带数据找用户（master plan §6 纪律）。
