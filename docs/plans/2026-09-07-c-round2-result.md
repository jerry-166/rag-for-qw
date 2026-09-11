# C 轮2 质量评估结果（CRUD-RAG + NFCorpus 公开集，含 graph 对象）

> 日期：2026-09-07 | 分支：feature/c-round2 | 前置：C 轮1 报告 `docs/plans/2026-09-04-c-round1-result.md`
> spec：`docs/plans/2026-09-07-c-round2-handoff.md`

---

## 一、目的与控制变量

### 目的
- 用公开集（CRUD-RAG 中文 + NFCorpus 英文 BEIR 标准）替代 C 轮1 的 KB17 同质文档，消除"同质 doc 自证"批评
- 补 graph 策略评估对象（C 轮1 spec 漏列，C 轮2 评估矩阵补齐）
- 统一控制变量（切块 + embedding dim），排除维度/切块干扰，确认质量差异是编排差异

### 控制变量（两系统对齐）
| 变量 | 本项目 | LightRAG |
|---|---|---|
| CHUNK_SIZE | 1000 | 1000（原默认 1200 已改） |
| CHUNK_OVERLAP | 100 | 100 |
| EMBEDDING_MODEL | DashScope text-embedding-v4 | DashScope text-embedding-v4 |
| EMBEDDING_DIM | 1536 | 1536（原默认 1024 已改 + EMBEDDING_SEND_DIM=true） |
| LLM | 智谱 GLM-4-Flash-250414 | 智谱 GLM-4-flash（同家族，非 250414 后缀） |

---

## 二、数据集

### CRUD-RAG（中文，IAAR-Shanghai/CRUD_RAG）
- 来源：`data/crud_split/split_merged.json`，子任务 `questanswer_1doc` 800 条
- 取 300 条子集（seed=20260907）
- 每条：question（人工编写）+ answer（人工标注 gt）+ news1（源文档）
- 自然 qrel：query i → doc_id `crud_{i:03d}`（1 relevant doc per query）
- KB corpus = 300 docs（每 doc 平均 ~700 chars，切 1-2 chunk）

### NFCorpus（英文 BEIR 标准集）
- 来源：HuggingFace `BeIR/nfcorpus` (parquet) + `BeIR/nfcorpus-qrels` (test.tsv)
- corpus 3633 docs（_id/title/text，医疗健康领域新闻摘要）
- queries 3237 test，取 100 子集（>=2 rel，avg 48 rel/query）
- qrels 3-level relevance（score 1/2/3，12334 pairs），high-rel(score>=2) 共 182 对
- KB corpus = 3633 docs
- gt 无自带 → 用智谱 GLM-4-Flash-250414 从 score>=2 docs 生成

---

## 三、评估矩阵

### 8 模式 × 2 数据集 × 7 指标 = 112 数据点

| 评估对象 | retrieval path | RAGAS | BEIR |
|---|---|:-:|:-:|
| ours_native_rerank_off（baseline） | Milvus vector + filter | ✓ | ✓ |
| ours_native_rerank_on | + BGE CrossEncoder rerank | ✓ | ✓ |
| ours_advanced | summaries + sub_questions（C2 enhancers=[] 关闭，降级 native） | ✓ | ✓ |
| ours_hybrid_vec | BM25 + Milvus RRF + rerank | ✓ | ✓ |
| ours_keyword | BM25 only | ✓ | ✓ |
| ours_graph | entity anchor → relation expand → chunks（C2 enhancers=[] 关闭，降级 native） | ✓ | ✓ |
| lightrag_naive | vector only | ✓ | ✓ |
| lightrag_hybrid | KG entity + relation + vector | ✓ | ✓ |

### 成本声明
- enhancers=[] 决策：本项目为 ~4000 docs 生成 sub_question/summary/entity 需 ~16000 LLM 调用，超 C 轮2 一日预算 → advanced/graph 在无 enhancers 时降级 native（retrieval_strategies.py L287/L351 显式 fallback）
- 影响：advanced 与 native_rerank_off 同结果，graph 与 native_rerank_off 同结果（实际差异化对象 = 6：native rerank开/关、hybrid_vec、keyword、LightRAG naive/hybrid）

---

## 四、RAGAS 8 对象四指标（生成质量）

judge：智谱 GLM-4-Flash-250414（多模型轮换避 429：遇 429 切 DashScope qwen3-flash，再切回）
策略：ours 6 模式共享一份 answer（/api/agent/chat 默认 advanced 检索生成），每模式只换 contexts（per-mode 检索端点）；LightRAG 2 模式 /query 拿 answer + /query/data 拿 chunks

### CRUD-RAG-300 结果

| 对象 | faith | ans_rel | ctx_pre | ctx_rec |
|---|---:|---:|---:|---:|
| ours_native_rerank_off (baseline) | TBD | TBD | TBD | TBD |
| ours_native_rerank_on | TBD | TBD | TBD | TBD |
| ours_advanced (degraded→native) | TBD | TBD | TBD | TBD |
| ours_hybrid_vec | TBD | TBD | TBD | TBD |
| ours_keyword | TBD | TBD | TBD | TBD |
| ours_graph (degraded→native) | TBD | TBD | TBD | TBD |
| lightrag_naive | TBD | TBD | TBD | TBD |
| lightrag_hybrid | TBD | TBD | TBD | TBD |

### NFCorpus-100 结果

| 对象 | faith | ans_rel | ctx_pre | ctx_rec |
|---|---:|---:|---:|---:|
| ours_native_rerank_off (baseline) | TBD | TBD | TBD | TBD |
| ours_native_rerank_on | TBD | TBD | TBD | TBD |
| ours_advanced (degraded→native) | TBD | TBD | TBD | TBD |
| ours_hybrid_vec | TBD | TBD | TBD | TBD |
| ours_keyword | TBD | TBD | TBD | TBD |
| ours_graph (degraded→native) | TBD | TBD | TBD | TBD |
| lightrag_naive | TBD | TBD | TBD | TBD |
| lightrag_hybrid | TBD | TBD | TBD | TBD |

---

## 五、BEIR 8 对象三指标（检索质量）

自实现 nDCG@10 / Recall@10 / MRR@10（pytrec_eval TLS 装不上）

### CRUD-RAG-300 结果（qrel: query i → doc_i 1-to-1）

| 对象 | nDCG@10 | Recall@10 | MRR@10 |
|---|---:|---:|---:|
| ours_native_rerank_off | TBD | TBD | TBD |
| ours_native_rerank_on | TBD | TBD | TBD |
| ours_advanced (degraded→native) | TBD | TBD | TBD |
| ours_hybrid_vec | TBD | TBD | TBD |
| ours_keyword | TBD | TBD | TBD |
| ours_graph (degraded→native) | TBD | TBD | TBD |
| lightrag_naive | TBD | TBD | TBD |
| lightrag_hybrid | TBD | TBD | TBD |

### NFCorpus-100 结果（qrel: BEIR 标准 3-level，对标 BEIR 排行榜）

参考：BEIR 论文（https://arxiv.org/abs/2104.08663）NFCorpus test set
- BM25 baseline: nDCG@10 ~0.325
- DPR (retriever only): ~0.232
- ANCE: ~0.301
- TAS-B: ~0.347

| 对象 | nDCG@10 | Recall@10 | MRR@10 |
|---|---:|---:|---:|
| ours_native_rerank_off | TBD | TBD | TBD |
| ours_native_rerank_on | TBD | TBD | TBD |
| ours_advanced (degraded→native) | TBD | TBD | TBD |
| ours_hybrid_vec | TBD | TBD | TBD |
| ours_keyword | TBD | TBD | TBD |
| ours_graph (degraded→native) | TBD | TBD | TBD |
| lightrag_naive | TBD | TBD | TBD |
| lightrag_hybrid | TBD | TBD | TBD |

---

## 六、关键结论

TBD（待评估完成填写）

---

## 七、诚实声明

1. **公开集 gt 来源差异**：CRUD-RAG 自带人工标注 gt（answers 字段）；NFCorpus 无 gt answer，由智谱 GLM-4-Flash-250414 从 qrel score>=2 docs 生成（self-judge 偏差 + LLM 生成 gt 可能遗漏）
2. **enhancers=[] 决策**：为控制 ~4000 docs × 4 增强调用 = ~16000 LLM 成本，C 轮2 关闭 enhancers，advanced/graph 降级 native，报告已注明；C 轮1 KB17 有 enhancers（advanced 0.941 ≠ native 0.939 略高），C 轮2 失去此对比维度
3. **多模型轮换 self-judge 偏差**：智谱 429 时切 DashScope qwen3-flash 作 judge，两模型评分尺度可能不同（智谱严苛 vs qwen 宽松），分数跨段切换有跳变风险
4. **中英差异**：CRUD-RAG 中文 + NFCorpus 英文，embedding/LLM 对中英表现可能不同（text-embedding-v4 多语言 OK，但智谱 GLM 对英文判断力弱于中文）
5. **控制变量声明**：两系统 CHUNK_SIZE=1000 + EMBEDDING_DIM=1536 已对齐，但 LightRAG 内部切块算法与本项目不同（LightRAG 用 token-based 切，本项目用 RecursiveCharacterTextSplitter char-based），切块单位差异仍存在
6. **shared answer 策略**：ours 6 模式共享一份 answer，answer_relevancy 跨模式无差异（同 answer），仅 faithfulness/context_precision/context_recall 因 contexts 不同而异；此为 C 轮1 同策略，可对比
7. **BEIR qrel 对齐**：CRUD-RAG 1-to-1 qrel（每 query 只 1 relevant doc）使得 nDCG/Recall 偏低且 rerank 后可能反降（同 C 轮1）；NFCorpus 多 rel/query（avg 48）更接近真实 BEIR，rerank 影响更可控
8. **LightRAG 文档分块不同**：LightRAG 内部切块策略与本项目不同，file_path→PG chunk_id 映射后 id 空间不重合度可能仍存在（C 轮1 问题），NFCorpus 3633 docs 可能更严重

---

## 八、面试话术（待评估后补）

---

## 九、产出文件

- 报告：本文档
- 数据集：
  - `backend/evaluation/testsets/crud_rag_300.json`（300 samples）
  - `backend/evaluation/testsets/nfcorpus_100.json`（100 samples）
  - `work/c-round2/corpus/crud_corpus_300.json`
  - `work/c-round2/corpus/nfcorpus_corpus.json`（3633 docs）
  - `work/c-round2/qrels/crud_qrels.json`
  - `work/c-round2/qrels/nfcorpus_qrels.json`
- 16 个 fill 测试集：`backend/evaluation/testsets/c2_{crud|nfcorpus}_{mode}.json`
- RAGAS 报告：`backend/evaluation/reports/eval_c2_*_*.json` + `c_round2_ragas_summary.json`
- BEIR 报告：`work/c-round2/beir_c2_{crud,nfcorpus}.json` + `beir_c2_summary.json`
- 脚本：`work/c-round2/{build_datasets.py, build_kb_ours.py, reset_lightrag_crud.py, fill_c2.py, beir_c2.py, run_ragas_c2.py, generate_nf_gt.py}`
