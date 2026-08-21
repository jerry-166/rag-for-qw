# Stage 2/3 未验证项补齐 — 验收记录（2026-08-21）

执行环境：uvicorn 127.0.0.1:8003（本会话启动/结束杀净），backend/.venv 未用系统 py，admin(1)/tester(7, test123456)/prverify(新建, Pr@Test123)。原始命令与响应见 `verify-remaining.log`。

## 总表

| # | 项目 | 结论 |
|---|---|---|
| 1 | 全链路 E2E 核对 | 通过（audit 管理员判定缺口已定位） |
| 2 | 03§7 A/B/C 质量对照 | **部分：B 达标、C/C2 未达标 → 切换默认路径不通过** |
| 3 | FAQ 蒸馏升格 | 通过 |
| 4 | GraphStrategy 实体检索 | 通过 |
| 5 | KB 克隆 E2E | 通过 |
| 6 | PR 审核闭环 | 通过 |
| 7 | 05a 批次 2（半成品评估） | 部分通过（代码完整保留；API 语义+语法验证通过，浏览器 UI 未点击验证） |

---

## 1. 全链路 E2E 核对 — 通过

- 产物 `up_resp.json / split18.json / gen19.json / imp19.json`（2026-08-20 22:34–22:40，tester 执行）。
- PG 核对：doc 19（kb=6, e2e_doc.md, status=completed），49 chunks / 242 sub_questions / 0 summary（KB6 未启用 summary，符合 enhancers=[entity, sub_question]）；17/18 为中间上传产物，最终入库为 19。
- imp19.json：49 chunks → 290 向量 + 241 子问题向量（audit 显示 291/242，含一次重放），vector_dim=1536。
- audit `process.import.done` PG 3 条（23:03/23:20/23:58），detail 含 chunks/vectors/sub_questions/vector_dim/processing_time_ms，与 JSON 一致。
- 各阶段耗时：split 345s（首次含切分+索引）、generate 28841s（该值为断点续跑累计计时，非单次）、import 872360ms（同上，含历史累计；最快一次 94.2s）。注：processing_time 字段跨批次累加，只可作上界参考。
- **发现（非阻塞）**：`/api/audit?action=...` 对 admin 返回 0 条——原因：admin 用户 role='user'（非 'admin'），非管理员被强制只查自己的记录。tester 查询返回 3 条正常。审计 API 行为与代码一致，但「admin 全量审计」实际依赖 users.role='admin'，当前 admin 账号未设该角色 → 已如实记录，建议 DB 修正。

## 2. 03§7 A/B/C 质量对照 — 部分（切换默认路径：不通过）

数据：`ab_c_results.json`（16 样本/组，chunk 5991–6023 抽自 KB6 已处理文档），设计标准：docs/plans/2026-08-18-03-enhancer-adapter-design.md §7。

| 组 | n | parse_ok | subq 均值(越界) | 摘要长度均值 | subq相关性 | subq有用性 | 摘要忠实度 |
|---|---|---|---|---|---|---|---|
| A 基线(gen_chain) | 16 | 16 | 4.94 (1条<3-5区间边) | 149.2 | 3.94 | 3.62 | 3.75 |
| B CombinedEnhancer | 16 | 16 | 4.81 (1条=4) | 146.4 | 3.94 | 3.56 | 3.88 |
| C 子问题单开 | 16 | 16 | 5.06 (**1条=6 越界**) | — | 3.44 | 3.19 | — |
| C2 摘要单开 | 16 | 16 | — | 131.7 | — | — | 3.31 |

LLM-as-judge 每组 16 条全评（judge_valid=16）。硬性判定（差 ≤0.3）：

- **B vs A：通过**。三项打分差 -0.00/-0.06/+0.13，结构指标一致（子问题数、摘要长度分布）。迁移无事故。
- **C vs A：不通过**。subq 相关性差 -0.50、有用性差 -0.43，均超 0.3；且 1 条子问题数=6 越界。
- **C2 vs A：不通过**。摘要忠实度差 -0.44 > 0.3。
- **结论：切换默认路径（单开精简 prompt）未达准入门槛**。按 §7 回退方案执行：单开路径复用合并 prompt 只取所需字段，或迭代 C/C2 prompt 后重跑（建议扩大样本至 50 chunk，16 条偏小）。

## 3. FAQ 蒸馏升格 — 通过

KB6 threshold=2。faq#2 "What is RAG system?"（candidate, hit=1）。tester 连续 2 次 `/api/agent/chat`（claw，kb=6）：

- 第 1 次命中 → hit=2 达阈值 → 自动 `distill_and_promote`：LLM 蒸馏（before "RAG combines retrieval with generation." → after 结构化完整答案），`db.promote_faq` 置 active。
- audit #417 `faq.promote`（via=threshold, hit_count=2, before/after 全文）；audit #419 `faq.hit`（score=1.0, hit_count=3，第 2 次命中 active 直返，服务器日志 `[rag_workflow] FAQ 直返回答 faq_id=2`）。
- 产物：`faq_hit_1.json / faq_hit_2.json`（第 2 轮响应即蒸馏后的 FAQ 答案）。

## 4. GraphStrategy 实体检索 — 通过

KB6 已有 65 实体 / 116 关系（audit process.entity_sync=3，实体在 E2E 文档处理时生成，无需补跑）。tester `POST /api/milvus/query {retrieval_mode:'graph', knowledge_base_id:6}`：

- 返回 5/5 条 `type='graph'` 结果，锚点 chunk score=0.9，内容为 Milvus 章节（chunk 5977/6001/6013），7.1s（含 LLM 锚点提取）。
- 失败路径已验证：无 KB → 降级 native（server log）；admin 无 KB6 权限 → 403（权限链正常）。首次用错字段 kb_id → 前置条件不满足降级 native，符合设计。
- 已知小缺陷：GraphStrategy 实体向量匹配偶发 MilvusException "required argument is not a float"（降级按名直查仍工作，不阻塞）。产物 `graph_item4.json`。

## 5. KB 克隆 E2E — 通过

tester `POST /api/kb/6/clone {new_name:'TestKB-Clone-Verify'}`（24.5s）→ kb_id=13：

- PG 对账：kb 1 行（enhancers 同步 entity+sub_question）、document 1、chunk 49、sub_question 242、faq 5 —— 与源 KB 逐一相等；entity/entity_relation 未克隆（0 行，设计如此：克隆 FAQ/向量，实体可由增强器重建）。
- Milvus 响应 `vectors:{chunks:49, summaries:0, subquestions:242, faq:5}` = 296 向量。
- 克隆后检索：native 5 条、advanced 5 条、graph 5 条（降级 native 路径，因实体未克隆——预期行为）、关键词（BM25）3 条（`elasticsearch/search`，克隆 BM25 内存索引补写生效）、hybrid 3 条。
- 附带发现：hybrid 不带 `use_rerank` 参数时返回空——默认 rerank 链路对中文查询返回 0 结果（kb6 同样为 0，非克隆引入；显式 use_rerank:true/false 均返回 3 条，疑似默认参数组装差异，**待查，非本次范围**）。产物 `clone_resp.json / clone_search_*.json`。

## 6. PR 审核闭环 — 通过

1. 新建用户 prverify（Pr@Test123）注册+登录。
2. tester `POST /api/kb/share` 分享 KB6 → success。
3. prverify `POST /api/faq/supplement {kb_id:6}` → `pr_submitted, pr_id=2`（非 owner 自动走 PR，audit #438 faq_pr.submit）。
4. tester `GET /api/faq-pr?target_kb_id=6` 见 open PR → `POST /api/faq-pr/2/merge` → `merged, faq_id=19`（audit #442 faq_pr.merge）。
5. prverify 随后 `/api/agent/chat` 同问题 → 命中新 FAQ 直返（回复尾部标注「命中问题…相似度 1.00」）。产物 `item6_chat.json`。

## 7. 05a 批次 2 半成品评估 — 部分通过（保留，不回退）

git 11 文件 diff 审查结论：**改动完整自洽，保留**。构成：

- settings.js（+150/-51）：`_dirtyKeys` Set 替代全局 bool，字段级 dirty 比对（回到原值撤销）、分组保存按钮（组内 dirty 计数徽标）、`collectDirtyConfigs(groupKey)` dirty-only + 组过滤、partial_error 组内联标红；与后端 PUT 语义（敏感项空串=跳过、null=清除、partial_error）严格对齐。
- agent.js（+11/-1）：SSE 流式渲染 100ms 节流（performance.now），done 事件终渲兜底 + 计时器复位。
- 后端配套：processing.py 补 `process.import.done`/entity 缺口检查埋点、document_processor entity 增量、faq_service 克隆 BM25 索引补写（第 5 项已实证生效）、milvus/bm25/database 小改。

验证：

- `node --check` settings.js / agent.js 通过。
- API 语义实测（admin）：单 key PUT（dirty-only 单项提交）→ `ok, updated:{RETRIEVAL_TOP_K:5}`；非法值 → `partial_error + errors`；未知 key → `partial_error`。
- **未做**：浏览器端点击验证（分组保存按钮/节流视觉效果）——记录为缺口，前端手工验收清单第 5 项待用户走查。

## 遗留问题清单（不在本次范围，如实移交）

1. admin 用户 role='user'，审计全量查询/管理功能实际不可用（DB 修正即可）。
2. `/api/hybrid/search` 不显式传 use_rerank 时结果为空（kb6/kb13 均复现）。
3. GraphStrategy 实体向量匹配偶发 Milvus "required argument is not a float"（有降级，不阻塞）。
4. C/C2 单开 prompt 未达对照门槛，切换默认路径需按 §7 回退或迭代重试。
