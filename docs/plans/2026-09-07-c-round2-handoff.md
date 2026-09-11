# C 轮2 交接文档（公开集 + graph + 控制变量）

> 日期：2026-09-07 | 分支：feature/quality-evaluation（合 main 后新会话开 feature/c-round2）| 前置：C 轮1 报告 `docs/plans/2026-09-04-c-round1-result.md`

---

## 一、C 轮1 现状（已完成，新会话继承）

### 完成内容
1. **KB17 milvus 索引重建**（text-embedding-v4 dim=1536，向量空间从 github_copilot 换）
2. **补量 32 条实质 gt**（`backend/evaluation/testsets/kb17_supplement.json`，智谱 GLM-4-Flash 生成）
3. **fill kb17_supplement**（32 complete，claw agent 智谱）
4. **LightRAG 9621 配置换智谱+DashScope** + 重建 KB17 索引（PG rag 库 truncate + 重导入 140 docs）
5. **fill_from_lightrag**（naive+hybrid 32 complete，关键：`/query` references.content 全 null 改用 `/query/data`）
6. **RAGAS 8 对象四指标**（judge 智谱 GLM-4-Flash-250414，256 次评估）
7. **BEIR 8 对象三指标**（自实现 nDCG/Recall/MRR，pytrec_eval TLS 装不上）
8. **报告** `docs/plans/2026-09-04-c-round1-result.md`

### 关键结论（面试王牌）
- **本项目 faithfulness 全面碾压 LightRAG**：hybrid_vec **0.969** vs LightRAG naive **0.798**（**+21%**）
- **context_recall** 本项目 **0.992** vs LightRAG **0.858**（+13%）
- 根因：本项目 answer 严格基于检索 contexts（单步生成 faith 高），LightRAG multi-step LLM 编排引入额外内容（图增强/实体摘要 faith 低）

### RAGAS 8 结果
| 对象 | faith | ans_rel | ctx_pre | ctx_rec |
|---|---|---|---|---|
| ours_hybrid_vec | **0.969** | 0.763 | nan† | 0.965 |
| ours_advanced | 0.941 | 0.762 | 1.000 | 0.988 |
| ours_native_rerank_off | 0.939 | 0.765 | 1.000 | 0.975 |
| ours_native_rerank_on | 0.900 | 0.758 | nan† | 0.988 |
| ours_keyword | 0.880 | 0.781 | 1.000 | 0.992 |
| lightrag_naive | 0.798 | 0.752 | nan† | 0.802 |
| lightrag_hybrid | 0.768 | 0.763 | nan† | 0.858 |

†4 对象 context_precision nan：智谱 429 限流（256 次后期），可信 4 对象全 1.000

### BEIR 8 结果
| 对象 | nDCG@10 | Recall@10 | MRR@10 |
|---|---|---|---|
| native_rerank_off | 0.585 | 0.988 | 0.618 |
| native_rerank_on | 0.389 | 0.525 | 0.441 |
| hybrid_vec | 0.422 | 0.615 | 0.461 |
| keyword | 0.395 | 0.538 | 0.426 |
| lightrag_naive | 0.002 | 0.006 | 0.004 |
| lightrag_hybrid | 0.014 | 0.006 | 0.031 |

BEIR 局限：① qrel 只标 native 召回 2-5 份同质 doc，rerank 后 nDCG 反降；② LightRAG chunk 策略不同 id 空间不重合 → LightRAG BEIR 极低不反映真实质量

---

## 二、C 轮1 缺失 TODO（C 轮3 进行C1的补充）

1. **graph 策略评估**——spec 8 对象漏列 graph（实体+关系图谱，Stage 4 文档 06 GraphStrategy），C 轮2 评估矩阵补 graph
2. **控制变量重跑**——统一切块 1000 + embedding dim 1536（LightRAG 默认 1200+1024 需改），排除维度/切块干扰，确认编排差异归因
3. **context_precision 4 对象 nan**——智谱 429 限流，错峰重跑（C 轮2 多模型轮换避限流）

---

## 三、C 轮2 计划

### 数据集
- **CRUD-RAG**（中文，中科大发布）子集 100-200 条，自带 (query, answer, context) 标注
- **NFCorpus**（英文 BEIR 标准子集）100-200 条，自带 qrel，**nDCG@10 对标 BEIR 排行榜**（https://arxiv.org/abs/2104.08663）
- 两套分别建 KB 导入两边系统

### 评估矩阵（补 graph，9 对象）
| 评估对象 | RAGAS 四指标 | BEIR 三指标 |
|---|---|---|
| 本项目 native（rerank 关） | ✓ | ✓ |
| 本项目 native（rerank 开） | ✓ | ✓ |
| 本项目 advanced | ✓ | ✓ |
| 本项目 hybrid_vec | ✓ | ✓ |
| 本项目 keyword | ✓ | ✓ |
| **本项目 graph（新增）** | ✓ | ✓ |
| LightRAG naive | ✓ | ✓ |
| LightRAG hybrid | ✓ | ✓ |

共 8 对象 × 7 指标 = 56 数据点（+ baseline）

### 控制变量
- **切块统一**：本项目 CHUNK_SIZE=1000 + overlap=100（.env），LightRAG 默认 1200 + 100 需改 CHUNK_SIZE=1000
- **embedding dim 统一 1536**：本项目 text-embedding-v4 dimensions=1536，LightRAG openai binding 默认 1024 需传 dimensions=1536
- 公开集重建索引时顺便统一（新数据新切块新 embedding）
- 目的：排除维度/切块干扰，确认质量差异是编排差异（本项目单步 vs LightRAG multi-step）

### 限流方案（多模型轮换，方案 a 推荐）
- 智谱 GLM-4-Flash-250414（免费，256 次/窗口 ~1h reset，1.05s 快）
- DashScope qwen3.7-flash（免费，慢 8.26s 但备用，避智谱限流）
- 轮换：智谱用完 256 切 DashScope，再切其他
- C 轮2 ~3200 调用（100 query × 8 对象 × 4 指标），一天跑完
- 备选：错峰分批（256 次/窗口 sleep 1h，延期 1 天）/ 生产 key（智谱付费 或 Cohere 月 1000）

---

## 四、服务配置（C 轮1 已对接，C 轮2 继承）

### LLM 智谱 GLM-4-Flash-250414（分离对接）
- `config.py` get_runtime LITELLM_API_KEY 特殊处理 → `ZHIPU_API_KEY`（系统环境变量 LITELLM_API_KEY 是旧 litellm key 绕过）
- `.env` LITELLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/ + DEFAULT_MODEL=glm-4-flash-250414
- 速度 avg 1.05s（比 qwen3.7-flash 8.26s 快 8 倍）

### embedding DashScope text-embedding-v4（分离对接）
- `config.py` 加 EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 + EMBEDDING_API_KEY=DASHSCOPE_API_KEY
- 4 处 OpenAIEmbeddings（document_processor L51 / faq_service L41 / milvus_client L700 / evaluator L247）用 EMBEDDING_BASE_URL+EMBEDDING_API_KEY + dimensions=1536 + check_embedding_ctx_length=False
- `.env` EMBEDDING_MODEL=text-embedding-v4 + EMBEDDING_BASE_URL=DashScope + EMBEDDING_DIM=1536

### 服务端口
- 后端 8003（uvicorn app:app，启动 ~50s Zilliz+BM25+Agent）
- litellm 4000（docker litellm-litellm-1，config_fixed 加 DashScope provider，本项目直接走 DashScope 不走 litellm）
- pg 5432（docker litellm_db / 本项目 rag 库）
- redis 6379（docker，缓存）
- LightRAG 9621（D:\workspace\LightRAG，work/lightrag-vs/start_lightrag.bat，需 ollama embedding nomic-embed-text:v1.5）

---

## 五、环境变量（系统级，C 轮2 继承）

| 变量 | 用途 | 状态 |
|---|---|---|
| ZHIPU_API_KEY | LLM 智谱 GLM-4-Flash | ✓ 主力 |
| DASHSCOPE_API_KEY | embedding DashScope text-embedding-v4 + 备用 LLM qwen | ✓ |
| COHERE_API_KEY | Cohere rerank（trial 20 不够，备用）| 限流 |
| ARK_API_KEY | 火山 doubao（备用，需 endpoint id）| 未通 |
| DEEPSEEK_API_KEY | deepseek-chat（402 余额不足）| 不可用 |
| HUGGINGFACE_API_KEY | HF Inference（非 OpenAI 兼容）| 跳过 |
| MIMO_API_KEY | 小米 mimo（401 失效）| 不可用 |
| NVIDIA_API_KEY | nvidia llama（需代理）| 超时 |

---

## 六、代码改动（C 轮1，已合 main）

1. **config.py get_runtime**：LITELLM_API_KEY → ZHIPU_API_KEY + EMBEDDING_API_KEY → DASHSCOPE_API_KEY（分离 LLM + embedding）
2. **config.py 加字段**：EMBEDDING_BASE_URL + EMBEDDING_API_KEY
3. **4 处 OpenAIEmbeddings**（document_processor/faq_service/milvus_client/evaluator）：用 EMBEDDING_BASE_URL+EMBEDDING_API_KEY + dimensions=1536 + check_embedding_ctx_length=False
4. **backend/api/search.py:_enrich_results**：datetime 序列化修复（isoformat，BUG-024，hybrid 500→32 complete）
5. **langchain-community 0.4.2→0.3.31 降级**（ragas 0.4.3 兼容，`uv pip install 'langchain-community<0.4'`）
6. **.env**：LITELLM_BASE_URL=智谱 + DEFAULT_MODEL=glm-4-flash-250414 + EMBEDDING_MODEL=text-embedding-v4 + EMBEDDING_BASE_URL=DashScope + EMBEDDING_DIM=1536

---

## 七、产出文件（C 轮1，C 轮2 复用）

- 报告：`docs/plans/2026-09-04-c-round1-result.md`
- RAGAS 8 报告：`backend/evaluation/reports/eval_kb17_*_20260907_*.json`
- BEIR：`work/lightrag-vs/beir_round1.json`
- 脚本（C 轮2 复用）：
  - `work/lightrag-vs/run_ragas_8.py`（RAGAS 8 对象，C 轮2 改 9 对象 + graph）
  - `work/lightrag-vs/beir_eval.py`（BEIR，自实现 nDCG/Recall/MRR）
  - `work/lightrag-vs/reset_lightrag_v2.py`（LightRAG 重建索引）
  - `work/lightrag-vs/fill_from_lightrag_v2.py`（用 /query/data 拿 chunks）
  - `work/lightrag-vs/fix_hybrid_vec.py`（hybrid datetime 修复）
  - `work/lightrag-vs/c_round1_supplement.py`（补量，C 轮2 改公开集 query）
- buglog：BUG-024（5 bug 经验：datetime + langchain ragas + LightRAG /query null + 智谱限流 + BEIR id 对齐）

---

## 八、C 轮2 验收标准（四个「真实」）

1. **真实提高性能**：质量指标对照 BEIR 排行榜（NFCorpus nDCG@10），不达标说明差距来源
2. **真实优化架构**：评估中质量短板（graph faith 低？hybrid rerank nDCG 反降？）作为优化方向
3. **真实可拓展**：测试集 + 评估脚本可复用于后续迭代回归
4. **真实合理**：self-judge 多模型轮换偏差 + 中英差异 + 控制变量声明 + gt 来源（公开集自带 vs LLM 生成）

### 具体验收
- ≥100 条实质 gt（CRUD-RAG + NFCorpus 各一套）
- RAGAS 9 对象四指标（含 graph）
- BEIR 9 对象三指标（NFCorpus 对标 BEIR 排行榜）
- 控制变量（统一切块 1000 + dim 1536）
- 报告 `docs/plans/2026-09-0X-c-round2-result.md`
- 诚实声明（self-judge 多模型轮换 + 控制变量 + gt 来源）

---

## 九、启动命令（新会话）

```powershell
# 后端（读 .env 智谱+DashScope）
cd d:\workspace\rag-for-qw\backend
$py = ".\.venv\Scripts\python.exe"
Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app:app","--host","0.0.0.0","--port","8003" -WorkingDirectory $PWD -WindowStyle Hidden
# 等 ~50s docs 200

# LightRAG（需 ollama embedding）
D:\workspace\rag-for-qw\work\lightrag-vs\start_lightrag.bat

# litellm（备用，本项目直接走 DashScope/智谱不走 litellm）
docker start litellm-litellm-1

# redis（尽量使用本机redis，不要启动docker）
docker start $(docker ps -aq --filter "name=redis")

# 测服务
curl http://localhost:8003/docs  # 后端
curl http://localhost:9621/health  # LightRAG
```

---

## 十、关键坑（C 轮1 踩过，C 轮2 避免）

1. **langchain OpenAIEmbeddings check_embedding_ctx_length**：默认 True 用 tiktoken 编码 token 数组，DashScope 不认返 400 → 必须设 False
2. **pydantic 环境变量优先于 .env**：系统环境变量 LITELLM_API_KEY（旧 litellm key）覆盖 .env → get_runtime 特殊处理绕过
3. **LightRAG /query vs /query/data**：/query references.content 全 null（只返 file_path）→ 用 /query/data 拿 chunks content
4. **ragas 0.4.x 兼容**：ragas 0.4.3 强依赖旧 langchain_community（vertexai 模块），langchain-community 0.4.x 移除 → 降级 0.3.31
5. **BEIR doc_id 对齐**：本项目 milvus chunk_id vs hybrid/search id vs LightRAG file_path → 反查 PG document_chunk.id 映射
6. **智谱免费 tier 限流**：256 次/窗口 ~1h reset → 多模型轮换或错峰
7. **datetime 序列化**：FastResponse JSON 返回前 datetime 字段 isoformat
