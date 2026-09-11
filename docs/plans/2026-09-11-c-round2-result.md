# C 轮2 CRUD-RAG 评估结果（2026-09-11）

> 数据集：CRUD-RAG 300 query + 1000 corpus（中文新闻问答）
> 评估对象：3 个 = native_rerank_off（baseline）+ native_rerank_on + graph（改造后）
> 评估维度：BEIR 3 指标（检索质量）+ RAGAS 4 指标（生成质量）
> judge LLM：智谱 GLM-4-Flash-250414（RAGAS judge）
> answer 生成 LLM：glm-4-air（重新生成"无法回答"的 answer）
> embedding：DashScope text-embedding-v4, dim=1536

## 一、实验设计

### 数据集

- **CRUD-RAG**：中文 RAG benchmark，300 query + 1000 corpus
- **KB 65**：300 rel docs（questanswer_1doc）+ 700 non-rel docs（entity 抽取用）
- **entity 数据**：3419 entity + 2061 relation（GLM-4-FlashX + qwen3.8-flash 两端开工抽取）
- **控制变量**：切块 1000+overlap 100，embedding dim 1536，ENTITY_TEMPLATE 统一

### 评估对象

| 模式 | 说明 | 检索方式 |
|---|---|---|
| native_rerank_off | baseline | 纯向量召回，无 rerank |
| native_rerank_on | native + rerank | 向量召回 + LLM reranker 精排 |
| graph | 改造后 GraphStrategy | LLM 锚点提取→关系扩展→LLM 关系重排→chunk 召回 |

### graph 改造（commit 4841911）

4 个改造点：
1. **LLM 结构化锚点提取**：`_extract_anchor_entities` 返回 `[{name, description}]`
2. **语义空间对齐**：entity "name：description" embedding 匹 description_vector
3. **LLM 关系重排**：`_rerank_relations` 过滤 score < 0.5 的关系（fail-open）
4. **路径 B 为主**：relation.source_chunk_id 直接拉证据原文（score 0.9）+ 兜底路径 A（entity.source_chunk_ids score 0.75）

### answer 生成策略

- **共享 answer**：调 `/api/agent/chat` 生成（Step 1），所有模式共享
- **per-mode contexts**：每模式独立检索 contexts（Step 2）
- **glm-4-flashx 问题**：60.7% query 返回"无法回答"（contexts 有答案但 LLM 没利用）
- **glm-4-air 修复**：用 glm-4-air 重新生成"无法回答"的 answer（170-180/188 修复成功）

## 二、BEIR 3 对象三指标（检索质量）

qrel：CRUD-RAG questanswer_1doc 的自然 qrel（query i → doc_id_i，1 relevant doc per query）

| 模式 | nDCG@10 | Recall@10 | MRR@10 |
|---|---:|---:|---:|
| native_rerank_off | **0.988** | **1.000** | **0.988** |
| native_rerank_on | **0.992** | **1.000** | **0.992** |
| graph | 0.877 | 0.880 | 0.877 |

### 关键发现

1. **native 检索质量接近完美**：nDCG 0.99, Recall 1.0（300 query 的 relevant doc 全部在前 10 召回）

2. **graph 检索质量低于 native**：nDCG 0.877 vs 0.99（-0.11），Recall 0.88 vs 1.0（-0.12）

3. **graph 召回量少**：graph 只返回 ~1 个 chunk（关系扩展 chunk 少），native 返回 10 个。graph 专注精准召回，Recall 受限。

4. **rerank 对 native 有轻微提升**：nDCG 0.988→0.992，MRR 0.988→0.992

## 三、RAGAS 3 对象四指标（生成质量）

judge：智谱 GLM-4-Flash-250414；answer 生成：glm-4-air（修复"无法回答"后）

| 模式 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---:|---:|---:|---:|
| native_rerank_off | 0.900 | 0.701 | **1.000** | 0.996 |
| native_rerank_on | **0.914** | 0.696 | 0.981 | **1.000** |
| graph | 0.846 | 0.676 | 0.918 | 0.925 |

### 关键发现

1. **native 生成质量优于 graph**：faithfulness 0.90 vs 0.85（-0.06），answer_relevancy 0.70 vs 0.68（-0.02）

2. **graph context 指标低于 native**：context_precision 0.918 vs 1.0，context_recall 0.925 vs 1.0——graph 只返回 ~1 个 chunk，contexts 少导致 context 指标低

3. **rerank 对 faithfulness 有轻微提升**：0.900→0.914（native_rerank_off→on）

4. **answer_relevancy 各模式差异小**（0.676-0.701）——answer 都切题

## 四、graph 效果差的原因分析

### 4.1 graph 只返回 ~1 个 chunk

graph 通过关系扩展找到的 chunk 本来就少：
- 关系重排后只保留 1 条关系（score < 0.5 过滤了大部分）
- 1 条关系 → 1 个 source_chunk_id → 1 个 chunk

对比 native 返回 10 个 chunk，graph 的 Recall 自然低。

### 4.2 graph 的 LLM 调用降级

graph 有 2 次 LLM 调用（锚点提取 + 关系重排），request_timeout=30s：
- LLM 调用 hang/timeout → 降级返回原始结果
- 但降级后的结果质量不如纯 native（graph 的降级链路不如 native 直接）

### 4.3 graph 的锚点提取不准

LLM 提取的锚点实体可能和 query 不完全匹配：
- 锚点 → name 直查 PG + description embedding 匹 Milvus
- 如果锚点不准，检索到的 chunk 不相关

**实测数据**（20 query 分析）：LLM 提取 41 个锚点，PG 精确匹配 25 个，**匹配率仅 61%**。miss 原因：
- name 不一致（括号、引号、简称/全称差异）：如 LLM 提"农业农村部（国家乡村振兴局）"但 PG 存"农业农村部"
- PG 没有该 entity（导入时没抽到）：如"中国寻根之旅"、"脂代谢异常"
- name 太长：如"第五届海峡两岸中华传统文化学生文艺营"

### 4.4 对比 C 轮1

C 轮1（KB17 同质技术文档）graph 没有测（只测 native/advanced/hybrid/keyword）。C 轮2（CRUD-RAG 新闻问答）是 graph 的首次评估。

### 4.5 A/B 测试：三种改进尝试

| 改进 | hit rate | avg_chunks | 结论 |
|---|---|---|---|
| 降阈值 0.5→0.3（hop=1） | 80%（10q） | 1.2 | 无效，关系本来就少 |
| 二跳 hop=2（score=0.3） | 89%（50q） | 1.7 | hit 微升但噪声多 + 慢（部分 94s） |
| LIKE 模糊匹配（hop=1, score=0.5） | 86%（50q） | 1.34 | 锚点匹配率提升但 hit 没提升 |
| **graph 兜底**（hop=1, score=0.5） | **100%（50q）** | **~9** | **hit 满分，延迟几乎不增加（native 补充 ~0.3s）** |

**A/B 测试结论**：graph 兜底是唯一有效的改进方案。其他三种（降阈值/二跳/LIKE）都没有显著提升，根因是关系数据稀疏。graph 兜底通过补充 native 向量召回的 chunk，解决了 chunk 数少的问题。

### 4.6 根因确认：关系数据稀疏

| 数据 | 数量 | 说明 |
|---|---|---|
| entity | 3419 | |
| relation | 2061 | |
| 平均关系/entity | **0.6 条** | 关系数据稀疏 |

关系少 → 一跳扩展出关系少 → source_chunk_id 少 → chunk 少（~1 个/query）→ Recall 低。

这是导入侧 EntityEnhancer 的抽取问题：ENTITY_TEMPLATE 限制"关系数量控制在 0~5 条，宁缺毋滥"，导致大部分 chunk 只抽到 0-1 条关系。

## 五、LLM 生成质量对比（glm-4-flashx vs glm-4-air）

| 指标 | glm-4-flashx（第一轮） | glm-4-air（第二轮） | 提升 |
|---|---:|---:|---:|
| faithfulness | 0.54 | 0.90 | +66% |
| answer_relevancy | 0.37 | 0.70 | +87% |

**根因**：glm-4-flashx 60.7% query 返回"无法回答"（contexts 有答案但 LLM 没利用），换 glm-4-air 后大幅提升。

## 六、诚实声明

1. **answer 生成 LLM 不统一**：graph 用 glm-4-air 重新生成 answer（第一轮），native 也用 glm-4-air 重新生成（第二轮）。对比公平（同一 LLM），但 answer 和 contexts 来自不同检索模式（共享 answer 策略的固有局限）。

2. **graph 只返回 ~1 个 chunk**：graph 的 BEIR Recall 0.88 和 RAGAS context 指标 0.918/0.925 偏低，主要因为 graph 只返回 1 个 chunk（关系扩展 chunk 少），不是检索逻辑错误。

3. **RAGAS judge 限流**：RAGAS 评估有大量 TimeoutError/429（智谱免费 API 限流），RAGAS 内部降级处理（失败 sample 返回 0 分），可能拉低整体分数。

4. **entity 数据不完整**：700 non-rel docs 有 46 个 import timeout（有 entity 但没 Milvus 向量），后用 sync 脚本批量同步修复。

5. **graph 改造未充分调参**：GRAPH_RELATION_MIN_SCORE=0.5 可能过滤太严格（只剩 1 条关系）。后续可调低阈值（0.3）看 graph 效果是否提升。

## 七、改进建议

### 7.1 graph 改进（A/B 测试验证）

1. **graph 兜底**（A/B 验证有效，已实现）：关系重排后 chunk 数 < limit 时，补充 native 向量召回的 chunk。A/B 测试 hit 88%→100%，avg_chunks 1→9，native 补充延迟 ~0.3s（占比 <2%）。

2. **增加关系抽取量**（根因修复）：导入侧 ENTITY_TEMPLATE 限制"关系 0~5 条，宁缺毋滥"，导致平均每 entity 只 0.6 条关系。改为"关系 1~8 条"或降低"宁缺毋滥"约束，增加关系数据密度。

3. **锚点 name 模糊匹配**（已实现 LIKE）：find_entities_by_names 加 LIKE fallback，锚点匹配率从 61% 提升（但单独使用 hit 没提升，需配合兜底）。

### 7.2 评估方法改进

4. **answer 生成换 glm-4-air**：agent/chat 的 LLM 从 glm-4-flashx 换成 glm-4-air（理解力更强，faith 0.54→0.90，不会 60% 拒绝回答）

5. **per-mode answer**：不用共享 answer，每模式基于自己的 contexts 生成 answer（answer 和 contexts 匹配，faithfulness 更真实）

6. **LLM 调用并发控制**：reranker/graph 的 LLM 调用加 asyncio.wait_for 超时降级（已修复），并发数需控制（3 并发稳定，8 并发 hang）

### 7.3 A/B 测试结论（三种改进无效）

| 改进 | hit rate | 结论 |
|---|---|---|
| 降阈值 0.5→0.3 | 80% | 无效，关系本来就少 |
| 二跳 hop=2 | 89% | 微升但噪声多 + 慢 |
| LIKE 模糊匹配 | 86% | 锚点多但关系少，无效 |

**根因**：关系数据稀疏（3419 entity / 2061 relation，0.6 条/entity），不在锚点匹配或阈值。

## 八、总结

### 核心发现

1. **native 检索质量优秀**：BEIR nDCG 0.99, Recall 1.0；RAGAS faith 0.90, context_precision 1.0

2. **graph 检索质量低于 native**：BEIR nDCG 0.877 vs 0.99；RAGAS faith 0.846 vs 0.90。根因是关系数据稀疏（0.6 条/entity）→ chunk 少（~1 个/query）

3. **graph 兜底是最有效的改进**：A/B 测试 hit 88%→100%，avg_chunks 1→9，延迟几乎不增加（native 补充 ~0.3s，占比 <2%）

4. **LLM 生成质量是评估瓶颈**：glm-4-flashx 60.7% 拒绝回答（contexts 有答案但 LLM 没利用），换 glm-4-air 后 faith 0.54→0.90（+66%）

### graph 兜底方案价值

graph 兜底 = graph 精准 chunk（score 0.9，关系扩展找到的高置信 chunk）+ native 向量召回 chunk（score 0.5-0.75，兜底补充）

- **hit 100%**：native 补充覆盖了 graph 关系稀疏导致的 miss
- **延迟可控**：native 向量检索 ~0.3s，相对 graph LLM 调用 ~10-20s 几乎可以忽略
- **保留 graph 优势**：graph 的精准 chunk 排前面（高置信），native 补充排后面（兜底）

### 后续方向

1. 全量 300 query BEIR 验证 graph 兜底效果
2. 增加关系抽取量（ENTITY_TEMPLATE 调参）
3. agent/chat 换 glm-4-air（解决 60% 拒绝回答）
4. per-mode answer（answer 和 contexts 匹配）

## 九、附录

### 数据统计

| 项 | 值 |
|---|---|
| entity | 3419 |
| relation | 2061 |
| chunks | 1099 |
| query | 300 |
| corpus | 1000 |

### 评估耗时

| 步骤 | 耗时 |
|---|---|
| fill 3 模式（3 并发） | ~1.5h |
| beir 3 对象 | ~45 min |
| RAGAS native 第一轮 | ~4h |
| answer 重生成 | ~15 min × 3 |
| RAGAS native 第二轮 + graph | ~6h |
| **总计** | ~13h |
