# 方案 C 设计：RAGAS + BEIR 检索质量评估

> 日期：2026-09-01 | 状态：spec（待执行，方案 B 之后）
> 前置报告：`docs/plans/2026-08-31-rag-benchmark-comparison.md`
> 目标：用业界标准评估框架（RAGAS + BEIR）量化本项目与 LightRAG 的检索/生成质量，产出可与论文排行榜对标的数字（nDCG@10 / Recall@k / faithfulness 等），作为方案 B 延迟对比的质量维度补充。

---

## 一、设计决策（已与用户确认）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 数据集策略 | **两轮**：轮1 用 KB17（复用 B 的索引）；轮2 引入公开评估集 | 与 B 联动，复用数据导入成果 |
| Ground truth 来源 | **轮1 先查 FAQ 库存量 + session 历史；不够用 LLM 生成补；轮2 用公开集自带标注** | 先看本项目自进化 FAQ 库（Stage 4 跑了 50 轮有真实 Q&A）省标注成本 |
| 评估语言 | **中英各一**：中文（KB17 自造 + CRUD-RAG 子集）+ 英文（NFCorpus 子集） | 中文贴合本项目业务，英文可对标 BEIR 排行榜 |
| 评估对象 | 本项目 5 检索模式 + LightRAG Naive/Hybrid | 本项目 5 模式对比是本项目核心价值；LightRAG 2 模式做横向参照 |

---

## 二、复用现有评估基础设施（关键，不重造轮子）

本项目已有完整 RAGAS 评估模块，**C 直接复用，不重新搭建**：

### 2.1 后端模块
- `backend/evaluation/evaluator.py` → `RagasEvaluator` 类（跑 RAGAS 四指标）
- `backend/evaluation/dataset.py` → `EvaluationDataset`（测试集加载/保存/填充）
- `backend/api/evaluation.py` → REST 接口

### 2.2 REST 接口（已实现）
| 端点 | 用途 | C 中的角色 |
|---|---|---|
| `POST /api/evaluation/dataset/from-sessions` | 从 session 历史自动提取测试集 | **轮1 ground truth 来源 1**（真实用户问答） |
| `GET /api/faq` | 列 FAQ 库存量 | **轮1 ground truth 来源 2**（自进化 FAQ Q&A） |
| `POST /api/evaluation/fill/{dataset_name}` | 填充 answer/contexts（调本项目检索） | 评本项目 5 模式时填充 |
| `POST /api/evaluation/run` | 异步跑 RAGAS 四指标 | 主评估入口 |
| `GET /api/evaluation/reports` | 列历史报告 | 取结果 |

### 2.3 需新增的能力
- **评 LightRAG**：`fill_dataset` 目前只调本项目 agent。需新增一个 `fill_from_lightrag` 变体，把 query 发给 LightRAG `/query`，拿回 answer + contexts 填入测试集。这是 C 唯一需要写的新代码（约 50 行）。
- **BEIR 检索质量**（nDCG@10/Recall@k/MRR@10）：RAGAS 评的是生成质量，BEIR 评的是纯检索质量。需新增一个脚本 `work/lightrag-vs/beir_eval.py`，用 `pytrec_eval` 或 `beir` 库算检索指标。

---

## 三、Ground Truth 策略

### 轮1（KB17，2 天）
1. **查 FAQ 库存量**：`GET /api/faq?knowledge_base_id=17`，统计有多少条 promote 状态的 Q&A（Stage 4 跑了 50 轮，预期 created 20 / merged 14 / promoted 6-8）
2. **查 session 历史**：`POST /api/evaluation/dataset/from-sessions`（max_samples=100），从历史问答提取 (query, answer, contexts) 三元组
3. **补量**：若 FAQ + session 不足 50 条，用 litellm 接的 LLM 对 KB17 文档生成补充 query（每 doc 生成 1-2 个 query + ground truth answer + 标注 context chunk_id），人工抽检 20% 质量
4. 产出 `evaluation/testsets/kb17_rag.json`

### 轮2（公开集，3 天）
- **CRUD-RAG**（中文，中科大发布）：取子集 100-200 条，自带 (query, answer, context) 标注
- **NFCorpus**（英文 BEIR 子集）：取子集 100-200 条，自带 (query, qrel) 标注
- 两套分别建 KB 导入两边系统（复用 B 轮2 的索引成果）

---

## 四、评估指标

### 4.1 RAGAS（生成质量，复用本项目 evaluator）
| 指标 | 含义 | 数值范围 | 业界参考 |
|---|---|---|---|
| `faithfulness` | 答案是否忠实于检索上下文（无幻觉） | 0-1 | 生产级 >0.8 |
| `answer_relevancy` | 答案是否切题 | 0-1 | >0.7 |
| `context_precision` | 检索上下文精确度（前k条相关比例） | 0-1 | >0.6 |
| `context_recall` | 检索上下文召回（ground truth context 被覆盖比例） | 0-1 | >0.7 |

> RAGAS 的 judge LLM 用 litellm 接的 `gpt-4o`（与被评系统同模型，注意 self-judge 偏差，报告中声明）。

### 4.2 BEIR（纯检索质量，新增脚本）
| 指标 | 含义 | 业界 SOTA 参考 |
|---|---|---|
| `nDCG@10` | 归一化折损累计增益@10 | BEIR 英文 SOTA ~0.5-0.6（取决于数据集）；中文通常低 5-15% |
| `Recall@k` | 前 k 条命中 ground truth 比例 | k=10 时 >0.8 为优 |
| `MRR@10` | 平均倒数排名@10 | >0.5 为优 |

> 用 `pytrec_eval` 库（`pip install pytrec_eval`）计算，输入是每 query 的检索结果 ranking + qrel 标注。

---

## 五、评估矩阵

| 评估对象 | RAGAS 四指标 | BEIR 三指标 |
|---|---|---|
| 本项目 native（rerank 关） | ✓ | ✓ |
| 本项目 native（rerank 开） | ✓ | ✓（rerank 后重排） |
| 本项目 advanced | ✓ | ✓ |
| 本项目 hybrid_vec | ✓ | ✓ |
| 本项目 keyword | ✓ | ✓ |
| 本项目 hybrid_endpoint | ✓ | ✓ |
| LightRAG naive | ✓ | ✓ |
| LightRAG hybrid | ✓ | ✓ |

共 8 评估对象 × 7 指标 = 56 个数据点。

---

## 六、中英评估集执行

### 6.1 中文（KB17 自造 + CRUD-RAG 子集）
- KB17：轮1 测试集 `kb17_rag.json`
- CRUD-RAG：轮2 取子集，两边建 KB（复用 B 轮2 导入）
- RAGAS：用中文 query，judge LLM 用 gpt-4o（中文能力强）
- BEIR：CRUD-RAG 自带 qrel

### 6.2 英文（NFCorpus 子集）
- 取 NFCorpus 100-200 query + qrel
- 两边建 KB（英文文档导入）
- RAGAS：英文 query，judge 同 gpt-4o
- BEIR：NFCorpus 自带 qrel，**nDCG@10 可直接对标 BEIR 排行榜**（https://arxiv.org/abs/2104.08663）

---

## 七、工期与里程碑

### 轮1（KB17，2 天，B 轮1 之后）
1. 查 FAQ + session 存量，定 ground truth 来源（0.5h）
2. 补量生成 + 抽检（若需，0.5 天）
3. 新增 `fill_from_lightrag` 变体（0.5 天）
4. 跑本项目 5 模式 RAGAS + LightRAG 2 模式 RAGAS（0.5 天）
5. 写 BEIR 脚本 + 跑 8 对象检索质量（0.5 天）
6. 出轮1 报告（0.5h）

### 轮2（公开集，3 天，B 轮2 之后）
1. 下载 CRUD-RAG + NFCorpus 子集（0.5 天）
2. 两边建 KB（复用 B 轮2 导入成果）（0.5 天）
3. 跑全评估矩阵（1 天）
4. 对标 BEIR 排行榜 + 出轮2 报告（1 天）

---

## 八、风险与对策

| 风险 | 对策 |
|---|---|
| RAGAS self-judge 偏差（judge 与被评同模型） | 报告声明；轮2 可换更强 judge 模型（如 claude）做交叉验证 |
| FAQ 库存量不足（<30 条） | 用 LLM 生成补 + session 历史补，目标 ≥50 条 |
| LightRAG `/query` 返回的 contexts 格式与本项目不同 | `fill_from_lightrag` 做格式归一化（取 chunk content + source） |
| BEIR 英文评估不代表中文业务表现 | 中英各跑一套，报告中分别呈现，不混淆 |
| CRUD-RAG 数据集获取困难（可能需申请） | 备选 DuReader / CMRC；NFCorpus 是 BEIR 标准子集，开放下载 |

---

## 九、产出文档

- `docs/plans/2026-09-0X-quality-evaluation-result.md`（轮1 + 轮2 结果）
- 原始数据：
  - `evaluation/testsets/kb17_rag.json`（轮1 测试集）
  - `evaluation/reports/eval_kb17_*.json`（RAGAS 报告，复用现有报告目录）
  - `work/lightrag-vs/beir_round{1,2}.json`（BEIR 检索质量）
- 最终对标表：本项目 5 模式 + LightRAG 2 模式 × 7 指标，中英两套

---

## 十、验收标准（四个「真实」）

1. **真实提高性能**：质量指标对照业界 SOTA，不达标要说明差距来源（模型/数据/架构）。
2. **真实优化架构**：评估中发现的质量短板（如某模式 context_precision 低）作为优化方向。
3. **真实可拓展**：测试集 + 评估脚本可复用于后续迭代回归。
4. **真实合理**：self-judge 偏差、中英差异、ground truth 来源如实声明。
