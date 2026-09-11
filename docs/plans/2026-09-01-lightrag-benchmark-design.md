# 方案 B 设计：本项目 vs LightRAG 延迟对比

> 日期：2026-09-01 | 状态：spec（待执行）
> 前置报告：`docs/plans/2026-08-31-rag-benchmark-comparison.md`
> 目标：在同一数据集 + 同一 embedding/LLM 模型 + 同一硬件 + 同一并发模式下，对比本项目与 LightRAG 的端到端检索响应速度（p50/p95/p99/QPS/错误率），判断本项目 RAG 在延迟维度的相对优势。

---

## 一、设计决策（已与用户确认）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 数据集策略 | **两轮**：轮1 用本项目已入库的 KB17（110 docs/1999 chunks 中文）；轮2 引入权威评估集（CRUD-RAG 中文 + NFCorpus 英文）重新导入两边 | 轮1 快速出对比结论，轮2 出权威对标 |
| LightRAG 查询模式 | **Naive + Hybrid** | Naive≈本项目 native（纯向量）；Hybrid≈本项目 hybrid_vec（双层检索，体现 LightRAG 图增强核心能力）；Local/Global 建图成本过高（2-4h + 大量 token）不跑 |
| 公平性铁律 | 同 embedding 模型 + 同 LLM + 同硬件 + 同并发 + 同 top_k | 任何一项不同则数字不可比 |
| 对比维度 | 端到端（含 LLM 生成） | 两边 `/query` 与 `/api/milvus/query` 都是端到端，天然可比 |

---

## 二、环境与公平约束

### 2.1 硬件（固定）
- 12 物理核 / 16 逻辑、15.6GB RAM
- 检索走 Zilliz Cloud（`MILVUS_URI`）—— **本项目侧**
- LightRAG 侧存储后端：**默认内存+文件持久化**（`rag_storage/`），不接 Milvus（避免引入额外的 Milvus 连接复杂度，且 LightRAG 默认后端是官方推荐开发模式）
  - ⚠️ 差异声明：本项目检索走 Zilliz Cloud 远程，LightRAG 走本地文件。这是架构差异，对比报告中必须注明。若要消除，可让 LightRAG 也接 Zilliz（轮2 可选做）。

### 2.2 模型配置（两边必须一致，照抄本项目 config.py）

| 配置项 | 本项目值 | LightRAG 环境变量 | 值 |
|---|---|---|---|
| LLM | `gpt-4o` | `LLM_BINDING` / `LLM_BINDING_HOST` / `LLM_MODEL` | `openai` / `http://localhost:4000/v1` / `gpt-4o` |
| Embedding | `github_copilot/text-embedding-ada-002` | `EMBEDDING_BINDING` / `EMBEDDING_BINDING_HOST` / `EMBEDDING_MODEL` | `openai` / `http://localhost:4000/v1` / `github_copilot/text-embedding-ada-002` |
| 向量维度 | 1536 | `EMBEDDING_DIM` | `1536` |
| Reranker | BGE CrossEncoder（本地） | `RERANK_BINDING` / `RERANK_MODEL` | 轮1 关（公平对比纯检索）/ 轮2 开（对比 rerank 效果，用 LightRAG 支持的 cohere 或保持关） |

> 关键：litellm 代理 `localhost:4000` 必须在压测期间保持运行（嵌入/LLM 走它）。本项目侧 reranker 是本地 BGE CrossEncoder，LightRAG 侧若开 rerank 用 cohere 远程——**这会引入不公平**（本地 vs 远程）。**轮1 两边都关 rerank**，只比纯检索+生成；rerank 效果差异在方案 C 用质量指标体现。

### 2.3 压测参数（固定，复用 Stage 4 基线）
- 并发：10（轮2 加梯度 1/5/10/20 看拐点）
- 请求数：40（轮2 加 200）
- top_k：10
- 预热：2 次
- 客户端超时：600s
- query 集：20 条中文（轮1 复用 `rerank_ab.py` 的 QUERIES；轮2 用评估集自带的 query）

---

## 三、LightRAG 部署配置

### 3.1 安装
```bash
uv tool install "lightrag-hku[api]"
# 或 pip install "lightrag-hku[api]"
```

### 3.2 `.env`（`work/lightrag-vs/.env`，接 litellm）
```ini
HOST=127.0.0.1
PORT=9621
WORKING_DIR=./rag_storage_kb17
INPUT_DIR=./inputs_kb17

LLM_BINDING=openai
LLM_BINDING_HOST=http://localhost:4000/v1
LLM_BINDING_API_KEY=sk-litellm
LLM_MODEL=gpt-4o
TIMEOUT=150
MAX_ASYNC_LLM=4

EMBEDDING_BINDING=openai
EMBEDDING_BINDING_HOST=http://localhost:4000/v1
EMBEDDING_BINDING_API_KEY=sk-litellm
EMBEDDING_MODEL=github_copilot/text-embedding-ada-002
EMBEDDING_DIM=1536

RERANK_BINDING=null
RERANK_BY_DEFAULT=False
```

### 3.3 启动
```powershell
lightrag-server --host 127.0.0.1 --port 9621 --working-dir ./rag_storage_kb17 --timeout 150 --max-async 4
```

### 3.4 数据导入（轮1）
- 从本项目 KB17 导出 110 docs 的原文（PG 查 `documents` 表，或调 `/api/documents?kb_id=17`）
- 用 LightRAG `POST /documents/texts` 批量导入（每条 text + 元数据）
- 等待索引完成（轮询 `GET /health` 的 `pipeline_busy`，Naive 模式几十分钟，Hybrid 需建图 1-2h）

---

## 四、对比矩阵

| 对比组 | 本项目端点 + body | LightRAG 端点 + body | 对比维度 |
|---|---|---|---|
| 纯检索（rerank 关） | `POST /api/milvus/query` `{retrieval_mode:native, use_rerank:false, limit:10}` | `POST /query` `{mode:naive, enable_rerank:false, top_k:10}` | 端到端 p50/p95/p99/QPS |
| 纯检索（rerank 开） | 同上 `use_rerank:true` | 同上 `enable_rerank:true` | rerank 对延迟的影响 |
| 双层检索 | `POST /api/milvus/query` `{retrieval_mode:hybrid_vec, use_rerank:false, limit:10}` | `POST /query` `{mode:hybrid, enable_rerank:false, top_k:10}` | 图增强 vs 向量+BM25 混合 |

---

## 五、压测脚本设计（复用 `rerank_ab.py`）

新脚本 `work/lightrag-vs/bench_lightrag.py`，结构照抄 `rerank_ab.py`，改：
- `B = 'http://localhost:9621'`（LightRAG）vs `B2 = 'http://localhost:8003'`（本项目）
- `ep = '/query'`（LightRAG）vs `'/api/milvus/query'`（本项目）
- body 字段映射：`{query, mode, enable_rerank, top_k}` vs `{query, retrieval_mode, use_rerank, limit, knowledge_base_id}`
- 跑 6 组（3 对比组 × 2 系统），每组 40@10，预热 2，输出 JSON 汇总

输出 `work/lightrag-vs/result_round1.json`：
```json
{
  "native_rerank_off": {"ours": {p50,p95,max,qps,wall,err}, "lightrag": {...}},
  "native_rerank_on":  {...},
  "hybrid":            {...}
}
```

---

## 六、指标与产出

### 6.1 延迟指标
- p50 / p95 / p99 / max（ms）
- QPS（n/wall）
- 错误率（err/n）
- wall time（s）

### 6.2 资源占用（可选，附 RSS 采样）
- 复用 Stage 4 的 rss 采样线程，记录两边进程 RSS 曲线

### 6.3 产出文档
- `docs/plans/2026-09-0X-lightrag-comparison-result.md`（轮1 结果 + 轮2 结果）
- 原始数据 `work/lightrag-vs/result_round{1,2}.json`

---

## 七、工期与里程碑

### 轮1（KB17，1 天）
1. 安装 LightRAG + 配 `.env`（0.5h）
2. 从 KB17 导出 110 docs → 导入 LightRAG + 等 Naive 索引（30min）+ 等 Hybrid 建图（1-2h，期间可做别的）
3. 写 `bench_lightrag.py`（复用 rerank_ab.py 改 endpoint，0.5h）
4. 跑 6 组压测（1h）+ 出轮1 报告（0.5h）

### 轮2（权威集，2-3 天）
1. 下载 CRUD-RAG（中文）+ NFCorpus（英文 BEIR 子集）
2. 两边都导入这两套数据集（本项目走 `/api/documents`，LightRAG 走 `/documents/texts`）
3. 用评估集自带 query 跑压测（加并发梯度 1/5/10/20）
4. 出轮2 报告 + 对标 BEIR 排行榜

---

## 八、风险与对策

| 风险 | 对策 |
|---|---|
| LightRAG Hybrid 建图消耗大量 token / 时间 | 已限 Naive+Hybrid，不跑 Local/Global；建图期间可并行做本项目侧准备 |
| 本项目走 Zilliz 远程 vs LightRAG 走本地文件，架构不公平 | 报告明确声明差异；轮2 可选让 LightRAG 接 Zilliz 消除 |
| litellm 代理 429（embedding 限流） | 复用 Stage 4 经验，并发 ≤10，预热 2 次；轮2 加梯度观察拐点 |
| LightRAG `/query` 端到端含生成，本项目也是，但两边生成 prompt 不同导致延迟差异 | 关键是两边都用同一 LLM（gpt-4o via litellm），prompt 差异属架构差异，报告中说明 |
| LightRAG 版本变动 API | 锁定版本 `lightrag-hku==<具体版本>`，spec 执行时记录版本号 |

---

## 九、验收标准（四个「真实」）

1. **真实提高性能**：对比结论必须基于真实压测数据，不臆测。
2. **真实优化架构**：对比中发现的本项目瓶颈（如 Stage 4 已定位的 reranker 超订阅）作为优化方向佐证。
3. **真实可拓展**：压测脚本可复用于后续与其他 RAG 框架对比。
4. **真实合理**：架构差异（Zilliz vs 本地文件、reranker 本地 vs 远程）如实声明，不掩盖不利因素。
