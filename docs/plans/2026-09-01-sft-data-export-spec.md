# SFT 训练集导出 spec（数据飞轮 Step 4）

> 日期：2026-09-01 | 状态：spec（待执行，依赖飞轮 Step 2/3 跑出足够样本后启动）
> 前置：飞轮 Step 1+2+3 完成，已积累 ≥30 条 approved + 评估过的样本
> 目标：从飞轮产出的高质量样本导出 SFT 训练集，为后续微调轻量组件（query 改写器 / reranker / 意图分类器）准备数据

---

## 一、为什么是 spec 不是实现

1. **数据量不够**：当前 `all_sessions_20260901.json` 20 条 + GT 全空，离 SFT 起步线 1k 条差 10×
2. **硬件扛不住**：本机 16GB RAM、无独显，跑不动 7B 模型 SFT（Qwen-7B SFT 显存需 ~24GB）
3. **ROI**：先写设计文档，等飞轮跑 2-3 周积累到 500-1000 条样本后再决定是否实施

---

## 二、SFT vs RAGAS 测试集的本质区别

| 维度 | RAGAS 测试集 | SFT 训练集 |
|---|---|---|
| 用途 | **评估**：拿模型回答跟 GT 比对算分 | **训练**：直接喂模型学映射，更新权重 |
| 数量 | 几十条就够 | 通常 1k-10k 条起 |
| 质量 | 高（要标 GT） | **极高**（错误样本会让模型学坏） |
| 在 RAG 项目里的角色 | 测当前系统好不好 | 微调某个组件让它更好 |

---

## 三、RAG 项目能微调什么（不是微调整个 LLM）

RAG 的主 LLM 一般直接用商用 API（gpt-4o/claude），不微调。**能微调的是这些轻量组件**：

1. **Query 改写模型**（0.5B 小模型）
   - 输入：用户口语化提问
   - 输出：检索友好的关键词
   - SFT 后比通用 LLM 快 10×，省 token
2. **Reranker**（基于 bge-reranker-base）
   - 输入：`{query, doc}`
   - 输出：relevance_score（0-1）
   - 业务领域精度提升明显（通用 reranker 在垂直 KB 表现一般）
3. **意图分类器**（小模型）
   - 输入：query
   - 输出：`retrieval / greeting / clarification`
   - 省 LLM 调用，意图分错直接走对应分支

---

## 四、SFT 数据格式

### 4.1 标准 SFT 格式（JSONL）

```jsonl
{"instruction": "用一句话解释 BM25", "input": "", "output": "BM25 是基于词频和逆文档频率的经典排序函数..."}
{"instruction": "把这个查询改写成检索关键词", "input": "我想了解一下向量的检索怎么工作的", "output": "向量检索 工作原理 embedding 相似度"}
```

### 4.2 DPO 偏好对格式（可选，用于偏好优化）

```jsonl
{"prompt": "什么是 BM25", "chosen": "BM25 是基于词频和逆文档频率的经典排序函数...", "rejected": "BM25 是一种机器学习算法..."}
```

DPO 不需要 GT 重新写——直接用 RAGAS 分数排序：
- 高分样本（faithfulness ≥0.9）的 answer → `chosen`
- 低分样本（faithfulness <0.5）的 answer → `rejected`

---

## 五、导出接口设计

### 5.1 REST 端点

```http
POST /api/evaluation/dataset/{name}/export-sft
Content-Type: application/json

{
  "format": "sft" | "dpo",
  "min_faithfulness": 0.9,
  "min_answer_relevancy": 0.7,
  "require_human_approved": true,
  "target_component": "query_rewriter" | "reranker" | "intent_classifier" | "general"
}
```

### 5.2 质量闸门（关键，不能让坏样本污染训练集）

导出条件：
1. `sample.status == "approved"`（人工或 LLM 自评过）
2. 关联的 RAGAS 报告里该样本 `faithfulness ≥ 0.9`
3. 关联的 RAGAS 报告里该样本 `answer_relevancy ≥ 0.7`
4. （可选）`require_human_approved=true` → 只导出人工 approve 的，跳过 LLM 自评

### 5.3 输出文件

```
backend/evaluation/exports/
├── sft_YYYYMMDD_HHMMSS.jsonl          # 标准 SFT 格式
├── dpo_YYYYMMDD_HHMMSS.jsonl          # DPO 偏好对
└── export_manifest_YYYYMMDD.json       # 导出清单（含闸门统计）
```

`export_manifest` 内容：
```json
{
  "exported_at": "2026-09-15T10:30:00",
  "format": "sft",
  "source_dataset": "flywheel_20260915",
  "thresholds": {"min_faithfulness": 0.9, "min_answer_relevancy": 0.7},
  "total_candidates": 100,
  "passed_gate": 47,
  "rejected_by_gate": 53,
  "rejection_reasons": {
    "faithfulness_below_threshold": 30,
    "answer_relevancy_below_threshold": 15,
    "not_approved": 8
  },
  "target_component": "query_rewriter",
  "output_file": "sft_20260915_103000.jsonl"
}
```

---

## 六、实施待办（飞轮 Step 2/3 跑稳后启动）

1. **新增** `backend/evaluation/sft_exporter.py`（导出器，约 150 行）
   - `export_sft(dataset, min_faithfulness, min_answer_relevancy, ...) -> JSONL`
   - `export_dpo(dataset, ...) -> JSONL`
   - 关联 RAGAS 报告的样本分数通过 `sample.metadata.report_score` 查
2. **新增** `POST /api/evaluation/dataset/{name}/export-sft` 端点（`api/evaluation.py`）
3. **新增** `backend/evaluation/exports/` 目录（gitignore 或入库二选一）
4. **前端** evaluation.js 加导出按钮（设计稿 wireframe 08-audit.html 已有评估页框架）

---

## 七、训练框架选型（实施时决定，不锁定）

| 框架 | 优点 | 缺点 |
|---|---|---|
| **LLaMA-Factory** | 中文社区最活跃、UI 友好、支持 Qwen/ChatGLM 全系 | 部分高级特性需付费 |
| **Axolotl** | 配置驱动、社区大、Slack 活跃 | 文档偏英文 |
| **unsloth** | 显存优化最强（4bit 量化训 7B 只需 6GB） | 仅支持 LoRA/QLoRA，模型覆盖不如前两者 |

**本机建议**：unsloth（4bit 量化让 16GB RAM 也能跑 7B QLoRA），但需要租 Colab/A100 跑完整训练。

---

## 八、量化指标对比（实施后跑）

微调前后对比维度：
1. **延迟**：query 改写器微调后 p50 是否从 ~2s 降到 ~200ms（小模型推理快）
2. **质量**：用同一 RAGAS 测试集评估，faithfulness/answer_relevancy 是否提升
3. **成本**：每次查询的 LLM token 数是否下降（小模型替代大模型）

---

## 九、风险与对策

| 风险 | 对策 |
|---|---|
| 高分样本不够（< 100 条）| 飞轮先跑 2-3 周积累，期间不导出 |
| LLM 自评 approve 的样本质量参差 | 默认 `require_human_approved=true`，只导人工审核的 |
| 微调后过拟合 | 保留 20% 高分样本做 eval set，训练集不重叠 |
| 数据合规（用户 session 含敏感信息）| 导出前脱敏（替换邮箱/手机号/IP），导出清单记录脱敏操作 |
