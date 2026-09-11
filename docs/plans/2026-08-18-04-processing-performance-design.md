# 设计文档 04：文档处理性能优化

> 状态：待审阅 | 日期：2026-08-18
> 定位：不动并发架构（协程 + Semaphore + gather 方向正确），消除 5 个内伤点；与文档 03 的适配器重构协同落地

## 1. 现状诊断

当前并发模型：LLM 生成走「外层 BATCH_SIZE=16 分批 + Semaphore(8) + gather + 批内 abatch」（document_processor.py:295-304, 183）；Embedding 走「256 条/批 + Semaphore(8) + 批内 64 条小批」（document_processor.py:396-432）。架构本身合理，但有 5 个内伤：

| # | 瓶颈 | 位置 | 影响 |
|---|---|---|---|
| 1 | **并发参数硬编码** `batch_size=16, max_concurrency=8` | document_processor.py:518、processing.py:244-245 | 设置页改 `BATCH_SIZE`/`MAX_CONCURRENCY` **不生效** |
| 2 | **摘要嵌入与子问题嵌入串行 await** | document_processor.py:447-456 | 两者无依赖，白白串行等待 |
| 3 | **O(n²) 填充** `summary_embeddings[valid_datas.index(d)]` | document_processor.py:462 | 大文档下 list.index 循环放大 |
| 4 | **同步阻塞调用** | Milvus `import_data`（processing.py:402-414 已用 executor 包裹，OK）；BM25 首次搜索整桶分词在请求协程内同步 CPU 执行（bm25_client.py:365-376） | 阻塞事件循环 |
| 5 | **死代码** `process_document_async` | document_processor.py:491-546 | 旧串行流程且把**路径当内容**传给 split（498 行），误导维护 |

## 2. 目标

- 修复参数热生效，消除串行点与算法复杂度问题。
- 大文档（数百 chunk）处理总耗时降低 20-40%（主要为嵌入阶段并行 + LLM 阶段参数可调）。
- 删除死代码，消除误导。

## 3. 设计

### 3.1 参数热生效（瓶颈 1）

所有调用处改为运行时读取：

```python
from config import get_runtime
batch_size = get_runtime("BATCH_SIZE", settings.BATCH_SIZE)
max_concurrency = get_runtime("MAX_CONCURRENCY", settings.MAX_CONCURRENCY)
```

涉及点：`document_processor.py:518`、`processing.py:244-245`，以及 `batch_embed_texts` 的 `EMBEDDING_BATCH_SIZE`/`EMBEDDING_BATCH_FACTOR`（document_processor.py:396-432，确认其已热读，若无则一并修）。

验收：设置页把 `MAX_CONCURRENCY` 从 8 改为 4，日志中并发度随之变化，无需重启。

### 3.2 摘要/子问题嵌入并行（瓶颈 2）

document_processor.py:447-456 的两段 await 改为：

```python
summary_embeddings, question_embeddings = await asyncio.gather(
    self._embed_summaries(valid_summary_chunks),
    self._embed_questions(valid_question_chunks),
)
```

注意：gather 后两个分支共享同一个 Semaphore(8) 限流，避免瞬时并发翻倍打爆 embedding API——Semaphore 实例提升为方法间共享（或按 `MAX_CONCURRENCY` 新建一个共享实例），限流语义不变，只是两类请求可以**交错**占坑而非串行排队。

### 3.3 O(n²) 修复（瓶颈 3）

document_processor.py:462 一带的 `valid_datas.index(d)` 改为 enumerate 建索引映射：

```python
index_of = {id(d): i for i, d in enumerate(valid_datas)}
# 或更稳妥：在生成阶段直接携带序号，避免对象身份依赖
```

实施时优先「携带序号」方案：`_embed_summaries` 返回 `list[tuple[int, vector]]`，填充按序号落位，彻底去掉 index 查找。

### 3.4 BM25 分词出协程（瓶颈 4）

- 分词缓存落 PG 后（文档 01-C），绝大多数搜索无分词。
- 残余的「新 chunk 首次分词」为 CPU 密集同步操作，包 `run_in_executor` 避免阻塞事件循环：

```python
new_tokens = await asyncio.get_running_loop().run_in_executor(
    None, self._tokenize_sync, missing_contents
)
```

### 3.5 死代码清理（瓶颈 5）

删除 `process_document_async`（document_processor.py:491-546）。删除前全库 grep 确认无引用（探索报告显示为旧流程，调用方已迁到 processing.py 的四阶段流水线）。

### 3.6 观测性（为大批量测试铺路）

pipeline 已有各阶段耗时 timeline（pipeline.js:1124-1130），后端补齐：

- 各阶段（split / generate / embed / import）在日志和 API 响应中输出：chunk 数、LLM 调用次数、embedding 批次数、墙钟耗时。
- generate 阶段输出 LLM 调用的 token 用量汇总（LangChain callback 已可得）。
- 修复 `pipeline.js:1128` timeline 中 `embed: 'N/A'` 恒占位问题（后端补返回字段）。

这些指标是整改前后对比的证据链，也是简历上的量化素材。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `backend/services/document_processor.py` | 参数热读；gather 并行嵌入 + 共享 Semaphore；序号映射；删死代码 |
| `backend/api/processing.py` | 244-245 参数热读；阶段耗时/token 指标返回 |
| `backend/services/bm25_client.py` | 首次分词 run_in_executor（依赖文档 01-C 的批量分词） |
| `frontend/js/pages/pipeline.js` | timeline embed 字段接入真实数据 |

## 5. 前后对比

| 维度 | 当前 | 整改后 |
|---|---|---|
| 并发参数 | 硬编码，改了不生效 | 设置页热生效 |
| 嵌入阶段 | 摘要→子问题串行 | gather 交错并行，共享限流 |
| 结果填充 | O(n²) index 查找 | O(n) 序号映射 |
| BM25 搜索 | 首次阻塞事件循环 | 缓存命中零分词 + 新分词出协程 |
| 死代码 | 1 个误导性旧流程 | 删除 |
| 可观测 | 阶段耗时不全（embed N/A） | 四阶段耗时 + token 用量齐全 |

## 6. 验证方式

1. **基准对比**：取同一篇大文档（≥200 chunk），记录整改前后四阶段耗时与总耗时（pipeline timeline + 后端日志），目标总耗时降 20-40%。
2. **参数热生效**：运行时改 MAX_CONCURRENCY，观察日志并发度变化。
3. **正确性回归**：并行嵌入后的向量与串行版本逐条一致（顺序对齐、无错位）；抽查 10 条 chunk 的 summary/subquestion 向量余弦相似度 = 1。
4. **限流不超标**：gather 并行下 embedding API 的瞬时并发 ≤ MAX_CONCURRENCY（日志打点验证）。

## 7. 风险与备注

- **共享 Semaphore 的公平性**：两类嵌入交错后，极端情况下一类长期占满坑位；可接受（总量受限），如需严格五五开再上分组信号量，本期不做（YAGNI）。
- **与文档 03 的先后**：文档 03 会把生成逻辑迁入 EnhancerPipeline，本文档的「参数热读」直接在新管道里落实，避免改两遍；**建议 04 的参数/死代码部分先做，嵌入并行随 03 一起落地**。
- embedding API 的速率限制（腾讯混元 side）需确认账户 QPS 上限，MAX_CONCURRENCY 默认 8 是否顶到限流，大批量测试时观察 429。
