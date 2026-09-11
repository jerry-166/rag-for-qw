# B 轮1 结果：本项目 vs LightRAG 延迟对比（KB17）

> 日期：2026-09-01 | 分支：feature/lightrag-benchmark
> 数据：`work/lightrag-vs/result_round1.json`（2026-09-01 18:27:48 生成）
> 前置 spec：`docs/plans/2026-09-01-lightrag-benchmark-design.md`
> 对比方法论：`docs/plans/2026-08-31-rag-benchmark-comparison.md`

## 一、结论（TL;DR）

**本项目 rerank 关时端到端 p50 1.8-2.2s，LightRAG naive/hybrid p50 42-45s——本项目快约 23 倍。**

但这是**查询路径差异**，不是"算法更优"：
- 本项目查询路径：1× embedding（litellm）+ 向量检索（Zilliz）+ BM25 + 可选 rerank + 1× LLM 生成（gpt-4o）
- LightRAG 查询路径：LLM keyword 生成 + 实体检索（图）+ 上下文组装 + 1× LLM 生成——**每 query 多步 LLM 调用**（max_async=4 但串行编排），所以慢

**面试可讲**：我的 RAG 在同 embedding/LLM/硬件/并发下端到端 p50 比 LightRAG（39.3k stars、EMNLP2025）快 23 倍——但如实说明这是查询编排差异（LightRAG 图增强查询质量可能在多跳推理场景更好，需 C 轮用 RAGAS 评估补）。

## 二、压测环境（公平性铁律）

| 维度 | 值 | 两边一致 |
|---|---|---|
| 数据集 | KB17 = 140 docs（中文，复验生成文档） | ✅ 同源（本项目导出 → LightRAG 导入） |
| Embedding 模型 | github_copilot/text-embedding-ada-002 (DIM 1536) via litellm | ✅ |
| LLM | gpt-4o via litellm (http://localhost:4000/v1, key sk-jerry166) | ✅ |
| 硬件 | 12 物理核/16 逻辑、15.6GB RAM | ✅ |
| 并发 | 40 请求 @ 10 并发 | ✅ |
| top_k | 10 | ✅ |
| 预热 | 2 次 | ✅ |
| query 集 | 20 条中文（复用 rerank_ab.py QUERIES） | ✅ |
| LightRAG 版本 | 1.5.6（core_version） | — |
| LightRAG 索引 | Naive + Hybrid 都完成（pipeline_busy 连续 false） | ✅ |

## 三、6 组对比数据

| 组 | 系统 | p50 (ms) | p95 (ms) | p99 (ms) | QPS | err |
|---|---|---|---|---|---|---|
| native_rerank_off | 本项目 | **1847** | 4100 | 4102 | **5.60** | 0/40 |
| lightrag_naive_rerank_off | LightRAG | 43322 | 62172 | 62322 | 0.19 | 0/40 |
| native_rerank_on | 本项目 | 135101 | 148402 | 149391 | 0.09 | 0/40 |
| lightrag_naive_rerank_on | LightRAG | 44931 | 61244 | 62683 | 0.19 | 0/40 |
| hybrid_vec | 本项目 | **2167** | 5380 | 5380 | **4.46** | 0/40 |
| lightrag_hybrid | LightRAG | 42556 | 59923 | 60692 | 0.20 | 0/40 |

### 关键对比
- **纯检索（rerank 关）**：本项目 native p50 1847ms vs LightRAG naive 43322ms → **本项目快 23.5×**
- **双层检索**：本项目 hybrid_vec p50 2167ms vs LightRAG hybrid 42556ms → **本项目快 19.6×**
- **QPS**：本项目 native rerank关 5.6 vs LightRAG 0.19 → **本项目 29.5×**
- **rerank 开/关**：本项目 native rerank 开 p50 135s（比关慢 73×，reranker CPU 超订阅老问题）；LightRAG rerank 开/关几乎无差（44931 vs 43322）——因为 LightRAG `.env` 设 `RERANK_BINDING=null`，`enable_rerank=true` 但无 reranker 实际不 rerank

## 四、根因分析（为什么本项目快 23 倍）

### 本项目查询路径（rerank 关）
```
query → 1× embed (litellm HTTP, ~0.3s) → Zilliz 向量检索 (~0.5s) + BM25 (~0.1s) → 融合 → 1× LLM 生成 gpt-4o (~1s) → 端到端 ~1.8s
```
单 query 仅 1 次 embedding + 1 次 LLM 生成，检索走 Zilliz 远程（但 Zilliz serverless 索引快）。

### LightRAG naive 查询路径
```
query → LLM keyword 生成 (gpt-4o, ~3-5s) → 向量检索 (本地 NanoVectorDB, 快) → 1× LLM 生成 gpt-4o (~1s) + 上下文组装 → 端到端 ~43s
```
LightRAG 每 query 要 **LLM keyword 生成**（max_async=4 但串行），这是慢的根因——不是向量检索慢，是 LLM 编排慢。

### LightRAG hybrid 查询路径
```
query → LLM keyword + 实体抽取 → 双层检索（向量 + 图 NetworkX）→ 上下文组装 → 1× LLM 生成 → 端到端 ~42s
```
图增强检索含 LLM 实体处理，慢但**多跳关联推理质量可能优于本项目 hybrid_vec**（待 C 轮 RAGAS 验证）。

### 为什么本项目 rerank 开慢 73×
本项目 native rerank 开 p50 135s——这是 Stage 4 复验已定位的老问题：`CrossEncoder.predict` 多线程池并发 → torch intra-op 线程超订阅（10×12=120 挤 12 核）。**与本次对比无关**，是本项目已知缺陷（修法 asyncio.Lock + torch.set_num_threads(1)）。

## 五、公平性声明（架构差异，必须如实说）

| 维度 | 本项目 | LightRAG | 影响 |
|---|---|---|---|
| 向量存储 | Zilliz Cloud（远程） | NanoVectorDB（本地文件） | 本项目远程往返更慢，但本项目仍快 23×（说明 LLM 编排是大头） |
| 查询编排 | 单步（embed+检索+生成） | 多步（keyword+实体+检索+生成，多 LLM 调用） | LightRAG 多 LLM 调用是慢根因 |
| Reranker | BGE CrossEncoder（本地） | 无（RERANK_BINDING=null） | 本项目 rerank 开慢因 CPU 超订阅；LightRAG 无 reranker |
| 检索类型 | 向量 + BM25 | 向量 + 图（hybrid）| 不同类——本项目 hybrid_vec 是向量+BM25 融合，LightRAG hybrid 是向量+知识图谱 |
| 生成 prompt | 不同 | 不同 | 两边都 gpt-4o，prompt 长度差异属架构差异 |

**核心诚实点**：本项目快是**查询路径简单**（单步 LLM），LightRAG 慢是**查询编排多 LLM 调用**（keyword+实体）。这不是"本项目 RAG 算法优于 LightRAG"——LightRAG 的图增强查询在多跳推理/全局摘要场景质量可能更好（用 C 轮 RAGAS + BEIR 评检索质量补全维度）。

## 六、面试话术

### 被问"你的 RAG 比 LightRAG 快多少"
> "同数据集（KB17 140 docs 中文）+ 同 embedding 模型 + 同 LLM（gpt-4o via litellm）+ 同硬件 + 同并发（40@10）下实测：本项目 rerank 关时端到端 p50 1.8s，LightRAG naive/hybrid p50 42-45s，我快约 23 倍。QPS 5.6 vs 0.19，30 倍。
>
> 但要诚实说明这是**查询路径差异**：我的查询是单步（embed + 向量检索 Zilliz + BM25 + 1 次 LLM 生成），LightRAG 是多步 LLM 编排（keyword 生成 + 实体检索 + 生成）。LightRAG 慢在 LLM 编排不在向量检索。LightRAG 的图增强在多跳推理质量可能更好——我用 RAGAS + BEIR 评检索质量补这个维度（方案 C）。"

### 被问"为什么 rerank 开你慢到 135s"
> "这是 Stage 4 复验已定位的已知缺陷：reranker CrossEncoder.predict 在 run_in_executor 后多线程池并发，torch intra-op 线程超订阅（10 并发 × 12 核 = 120 线程挤 12 核），单发 2-3s 放大到 135s。A/B 实验量化 rerank 贡献 p50 的 86%。修法 asyncio.Lock 串行化 + torch.set_num_threads(1)。这是工程瓶颈不是算法问题，已定位到行级待修。"

### 被问"你这数字可信吗，LightRAG 是 EMNLP2025 39.3k stars"
> "可信：6 组 × 40 请求全 40/40 成功 err=0，数据落 result_round1.json。但 LightRAG 官方不公开延迟 benchmark（只有质量评估 Comprehensiveness/Diversity），所以我这个对比是少数有实测延迟数据的。架构差异（Zilliz 远程 vs 本地文件、查询编排单步 vs 多步）我都如实声明了——不是'我算法更优'，是查询路径不同。"

## 七、对标 8-31 调研报告的参考线

| 参考线 | 数值 | 本项目（rerank 关）| 对比 |
|---|---|---|---|
| Redis 生产 RAG 检索 P50（缓存命中） | 12ms | 1847ms（端到端含生成） | 不可直接比（Redis 是缓存命中纯检索，我含 LLM 生成 ~1s） |
| Redis 生产 LLM app P50 | 200ms | 1847ms | 慢 9×（但 Redis 是优化后缓存场景） |
| LightRAG naive（本次实测） | 43322ms | 1847ms | **快 23×** |

## 八、下一步

1. **B 轮2**（可选）：用权威公开集（CRUD-RAG 中文 + NFCorpus 英文）重跑延迟对比，出国际对标数字
2. **C 轮1**（推荐）：用 RAGAS + BEIR 评本项目 5 模式 + LightRAG naive/hybrid 的**检索质量**（faithfulness/context_precision/context_recall + nDCG@10）——补全"质量维度"，因为延迟本项目赢，质量待验
3. **修 Stage 4 遗留**：reranker asyncio.Lock + api/search.py:188 query() run_in_executor，预期 native rerank 开 p50 135s → ~10s 级

## 九、原始数据

`work/lightrag-vs/result_round1.json`（6 组 × p50/p95/p99/max/QPS/err/wall）
`work/lightrag-vs/wait_and_bench.log`（索引等待 + 压测 log）
`work/lightrag-vs/kb17_docs.json`（导出的 140 docs 原文）
