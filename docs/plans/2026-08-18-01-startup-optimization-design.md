# 设计文档 01：启动初始化优化（B 并发预热 + C 分词缓存落 PG）

> 状态：待审阅 | 日期：2026-08-18
> 关联会话：CodeBuddy `eb1c1bcb031e442590082746e4d39667`（C 方案细节来源）

## 1. 现状诊断

启动入口 `backend/app.py`（`lifespan`，app.py:90-144），当前阻塞点按耗时排序：

| 初始化点 | 位置 | 方式 | 问题 |
|---|---|---|---|
| BM25 语料加载 | app.py:110 → bm25_client.py:294-328 | **同步** `SELECT * FROM document_chunk` 全量入内存 | 随 chunk 数线性增长 |
| Milvus 连接 | app.py:100 → milvus_client.py:21 | 构造函数内**同步 connect**，30s 超时 | 网络差时阻塞启动 |
| PG 连接+建表 | database.py:867 模块级 `db = Database()` | **import 即连接**（隐式 eager） | import 链阶段就卡住，不可控 |
| BM25 首次分词 | bm25_client.py:347-381 `_get_or_build_model` | 首次搜索时**整桶 jieba 全量分词** | CPU 密集，阻塞请求协程，桶粒度失效（一个 chunk 变 → 整桶重分词） |
| Reranker + 3 Agent | app.py:143 `_preheat_agents` | 已是后台任务 | 无需改 |

关键认知（来自会话 eb1c1bcb）：**BM25 慢的根因不是 PG 读取，而是读完后的 jieba 全量分词**。PG 是权威数据源，分词结果是昂贵中间产物，应缓存进 PG 而非 pickle。

## 2. 目标

1. 服务启动后 <2s 可接收请求（不被 Milvus/BM25 阻塞）。
2. 依赖未就绪时请求带锁等待而非报错。
3. BM25 分词结果 chunk 粒度持久化到 PG，二次启动/搜索零分词开销，数据变更自动增量失效。

## 3. 设计

### 3.1 B 部分：启动并发化 + 分级预热

**lifespan 内只保留必须同步的部分**，其余移入并发预热：

```
启动路径（同步）：
  1. PG 连接 + create_tables()（从模块级 import 移到 lifespan 显式执行，仍同步——它是其他一切的前提）
  2. 创建 readiness 信号：app.state.readiness = {name: asyncio.Event()}

后台预热任务（asyncio.create_task，内部 gather 并发）：
  ├─ Milvus 连接（run_in_executor 包裹同步 connect）
  ├─ BM25 语料加载（run_in_executor 包裹 load_from_database，只读原文不分词）
  ├─ 搜索引擎客户端构建（ES/BM25 工厂）
  ├─ Reranker 模型加载（现有逻辑保留）
  └─ 3 个 Agent 预热（现有 _preheat_agents 逻辑并入）
每项完成 → 对应 Event.set()；失败 → Event.set() + 记录 error，请求路径返回 503 + 原因
```

**请求路径就绪门**：在各服务客户端的公开方法入口加 `_await_ready()`：

```python
async def _await_ready(self, timeout: float = 60.0):
    await asyncio.wait_for(self._ready_event.wait(), timeout)
    if self._init_error:
        raise RuntimeError(f"{self.name} 初始化失败: {self._init_error}")
```

- 命中已就绪 → 零开销（Event.is_set 快路径）。
- 未就绪 → 挂起等待，而非 500。
- 超时/初始化失败 → 明确的 503 错误信息。

**PG 模块级连接改造**：`database.py:867` 的 `db = Database()` 改为惰性——模块级只放 `db = DatabaseProxy()`（转发属性访问），真实连接在 lifespan 调用 `db.init()` 时建立。proxy 保证现有 `from services.database import db` 的全部调用点**零改动**。

### 3.2 C 部分：BM25 分词缓存落 PG（chunk 粒度）

#### 表结构（TEXT + LZ4 压缩，替代 JSONB——应对存储超倍风险）

```sql
ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS tokenized TEXT;
-- PG 14+：启用 LZ4 的 TOAST 压缩（分词串普遍超过 2KB TOAST 阈值，自动压缩）
ALTER TABLE document_chunk ALTER COLUMN tokenized SET COMPRESSION lz4;
```

`tokenized` 存 `" ".join(tokens)` 的空格连接文本（jieba 中文分词不含空格 token、英文 token 自身无空格，分隔安全）。`document_chunk` 同时是「权威原文」和「分词缓存」的单一事实来源，无缓存一致性问题。

**为什么不用 JSONB**：JSONB 数组每个 token 带引号/逗号开销，且 `cut_for_search` 搜索引擎模式本身产生重复词条，实测约为原文 UTF-8 的 2~2.5 倍存储。改用 TEXT 连接 + LZ4 TOAST 压缩后（分词串冗余度高，压缩率约 50-60%），每 chunk 分词存储 ≈ 原文的 0.8~1.2 倍，**存储超倍问题消除**（详见第 7.2 节）。

#### 三态语义

| 值 | 含义 | 动作 |
|---|---|---|
| `NULL` | 未分词（新 chunk 或被标脏） | 需要时分词并写回 |
| `''`（空串） | 已分词但为空（防御） | 视为已缓存，读回 `[]` |
| 非空文本 | 缓存命中 | `text.split(' ')` 直接使用 |

#### 增量失效（写路径自动置脏）

- `add_document_chunk`（幂等 upsert）：`ON CONFLICT DO UPDATE` 中加 `tokenized = NULL`——新增/修改自动失效。
- 删除 chunk/document：物理删除，缓存随之消失，无需处理。
- **无需任何旁路缓存删除逻辑**，走正常 DB 写接口即自动失效——优于现有 `_invalidate_model` 整桶失效。

#### 分词路径改造（bm25_client.py）

新增批量方法（避免 N+1）：

```python
def _get_tokenized_batch(self, corpus: Dict[int, dict]) -> Dict[int, list]:
    cached = db.get_tokenized_by_ids(list(corpus.keys()))  # 一次 IN 查询，TEXT split 还原
    missing = {i: c for i, c in corpus.items() if i not in cached}
    if missing:
        jieba = _get_jieba()
        new_tokens = {i: list(jieba.cut_for_search(c["content"])) for i, c in missing.items()}
        db.set_chunk_tokenized_batch(new_tokens)           # 批量写回，" ".join 存储
        cached.update(new_tokens)
    return cached
```

`_get_or_build_model`（bm25_client.py:347-381）中的分词循环替换为上述批量调用；BM25Okapi 模型本体仍按桶缓存于内存（构建本身是纯内存统计，毫秒级）。

`load_from_database`（bm25_client.py:294-328）保持只读原文进 `_corpus`，**不再触发任何分词**。

#### database.py 新增方法

- `set_chunk_tokenized_batch(mapping: Dict[int, list])`：批量 UPDATE（executemany），值写 `" ".join(tokens)`。
- `get_tokenized_by_ids(chunk_ids) -> Dict[int, list]`：`WHERE id IN (...) AND tokenized IS NOT NULL`，读回后 `split(' ')`，空串特判为 `[]`。
- `create_tables` 中加兼容迁移：`ADD COLUMN IF NOT EXISTS tokenized TEXT` + `SET COMPRESSION lz4`。

### 3.3 配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `STARTUP_PREHEAT` | `true` | 是否后台预热（false 则纯懒加载，便于对比测试） |
| `STARTUP_READY_TIMEOUT` | `60` | 请求路径等待就绪的超时秒数 |
| `BM25_CACHE_BUCKETS` | `16` | 内存中 BM25Okapi 模型的 LRU 桶数上限（第 7.1 节） |
| `BM25_CACHE_MAX_CHUNKS` | `100000` | 所有桶缓存 chunk 总量上限（第 7.1 节） |

均加入 `WRITABLE_CONFIGS`（runtime_config.py:36-358）。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `backend/app.py` | lifespan 重构：同步 PG init + 并发预热 gather；`_preheat_agents` 并入统一预热 |
| `backend/services/database.py` | 模块级 eager 连接 → DatabaseProxy 惰性 init；tokenized(TEXT+LZ4) 两个方法 + 迁移 |
| `backend/services/milvus_client.py` | 连接从构造函数剥离为 `async connect()` + readiness Event |
| `backend/services/bm25_client.py` | `_get_tokenized_batch` + `_get_or_build_model` 改造 + readiness Event + `_models` LRU 化（7.1） |
| `backend/services/elasticsearch_client.py` | readiness Event（connect/create_index 移入预热） |
| `backend/services/reranker.py` | 接入统一 readiness（已有 `_ensure_model_loaded`，包一层 Event 即可） |
| `backend/services/runtime_config.py` | 新增 4 个可写配置（预热 2 + LRU 2） |

## 5. 前后对比

| 维度 | 当前 | 整改后 |
|---|---|---|
| 启动可服务时间 | BM25 全量加载 + Milvus 连接串行完成才就绪 | <2s（仅 PG 建表） |
| 首个请求体验 | 等待启动完成 | 已预热则零等待；未预热则带锁等待，不报错 |
| BM25 首次搜索 | 整桶 jieba 全量分词（秒~十秒级，阻塞协程） | 命中 PG 缓存直接构建模型（毫秒级）；仅新增 chunk 分词 |
| chunk 变更后 | 整桶重分词 | 仅该 chunk 重新分词（写路径自动置脏） |
| 多实例一致性 | 各进程内存各自构建 | 分词缓存共享于 PG |

## 6. 验证方式

1. **冷启动计时**：`time uvicorn → 首个 200 响应`，对比整改前后（预期从 N 秒 → <2s）。
2. **热启动验证**：二次启动后首次 BM25 搜索，日志确认 `tokenized` 全命中、无 jieba 调用。
3. **增量失效**：修改一个 chunk 的 content → 确认其 `tokenized` 变 NULL、下次搜索仅重分词该 chunk。
4. **并发正确性**：预热未完成时并发打 10 个搜索请求 → 全部等待后正常返回，无竞态。
5. **降级**：Milvus 故意配错地址 → 启动不阻塞，搜索请求返回 503 带明确原因。
6. **存储对比**：迁移前后 `SELECT pg_total_relation_size('document_chunk')` 对比；抽样 100 条 chunk 分词「写入→读回」往返一致（join/split 无损）。
7. **内存验收**：预热后日志输出各桶 BM25Okapi 估算占用与总量；构造超限桶数验证 LRU 逐出后重建可用、无 OOM。

## 7. 风险应对策略（2026-08-19 用户评审补充：内存与存储两大风险）

### 7.1 风险一：BM25Okapi 内存占用过大 → LRU 容量淘汰

**问题量化**：BM25Okapi 内部持有 `doc_freqs`（每篇 chunk 一个 {token: 词频} dict）+ `idf` + `doc_len`，对中文语料内存占用约为原始文本的 3~5 倍；且当前 `_models` 按桶（user:kb）常驻、无上限——桶数随用户×知识库增长线性膨胀，最终 OOM。

**策略：LRU 淘汰 + 重建成本摊销（C 部分的自然红利）**

- `_models` 从普通 dict 改为 `OrderedDict`：命中 `move_to_end`；插入后检查双上限（`BM25_CACHE_BUCKETS` 桶数 / `BM25_CACHE_MAX_CHUNKS` 总 chunk 数），超限 `popitem(last=False)` 逐出最久未用的桶。
- **逐出代价可控的前提是 C 已落地**：重建 = 从 PG 批量读已缓存分词（毫秒级）+ BM25Okapi 纯内存统计构建（万级 chunk 亚秒级）——不再有 jieba 全量分词的大头。**LRU 必须排在 C 之后实施**，这正是 C 的核心价值之一。
- **内存观测**：每次建桶/逐出打日志（桶 key、chunk 数、token 总数、估算内存 = token 总数 × dict 开销系数）；预热完成后汇总输出。上线后按真实数据调两个上限参数。
- 兜底：若单桶本身超过 `BM25_CACHE_MAX_CHUNKS`（超大 KB），该桶不缓存模型、每次现算（记录 warn，提示拆分知识库）。

### 7.2 风险二：分词存储超倍 → TEXT 连接 + LZ4 压缩（已并入 3.2 设计）

**问题量化**：JSONB 数组方案下，`cut_for_search` 每 token 约 2~3 字节 + JSON 引号逗号约 3 字节开销，叠加搜索引擎模式重复词条，总存储约为原文 UTF-8 的 2~2.5 倍。

**策略**（已在 3.2 表结构落地）：
1. JSONB → **TEXT 空格连接**：省掉每 token 的引号/逗号 JSON 开销（约 -30~40% 体积）。
2. **TOAST LZ4 压缩**：分词串冗余度高（重复词条/常见词），LZ4 压缩率约 50-60%，且解压速度极快（GB/s 级），不构成读路径瓶颈。
3. 综合效果：每 chunk 分词存储 ≈ 原文的 0.8~1.2 倍，与原文同量级，超倍问题消除。
4. 备选项（不采用）：jieba `cut` 精确模式可再省 30~50% token 数，但改变分词行为影响 BM25 召回，仅作为后续实验项（A/B 对比召回指标后再议）。

### 7.3 其他备注

- **预热期间的请求延迟**：首个请求最坏等待 Milvus 连接（30s 超时时会失败返回 503），可接受。
- C 部分可独立先于 B 落地（纯后端改动，无启动流程风险）；实施顺序：C（含 7.2 存储）→ B → LRU（7.1）。
- **PG 版本确认**：LZ4 压缩需 PG 14+；若生产为低版本，退化为默认 pglz 压缩（压缩率更高、速度略慢），SQL 写法兼容即可。
