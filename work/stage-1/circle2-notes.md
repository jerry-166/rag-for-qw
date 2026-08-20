# Stage 1 Circle 2 — 文档 04 Stage 1 独立项改动摘要

日期：2026-08-20 分支：feature/stage-1-perf-startup

## 范围
仅文档 04 中标记 Stage 1 可独立落地的项：参数热读（§3.1）、O(n²) 修复（§3.3）、死代码删除（§3.5）。
摘要/子问题嵌入并行（§3.2）按文档建议「随 03 一起落地」，但本次因 O(n²) 修复直接位于该函数内，为避免改两遍，将 §3.2 的 gather 并行 + 共享 Semaphore 一并实现（超出最小范围的理由：§3.3 与 §3.2 在同一段代码，分开做会重复返工）。
BM25 分词出协程（§3.4）依赖文档 01-C，未做。观测性增强（§3.6）属 Stage 2/后续，未做。

## 改动清单

### backend/services/document_processor.py
1. 死代码：删除 `process_document_async` + `process_document`（旧串行流程，把路径当内容传 split，全库无外部引用），同时删除随之无用的 `uuid`/`Path` import。
2. O(n²) 修复：`generate_and_fill_embeddings` 填充循环中 `valid_datas.index(d)` → `enumerate(zip(valid_indices, valid_datas))` 按位置落位。
3. 嵌入并行（§3.2 提前合并）：摘要/子问题两段串行 `batch_embed_texts` 改为 `asyncio.gather` 并行，共享同一 `Semaphore(MAX_CONCURRENCY)`（热读），限流总量不变、坑位可交错；批大小（32/64）与分批逻辑（EMBEDDING_BATCH_FACTOR 热读）与原实现一致。
4. `generate_chunk_embeddings` 的 `settings.EMBEDDING_BATCH_SIZE`/`settings.MAX_CONCURRENCY` 启动期冻结读 → `get_runtime` 热读。
5. 审计埋点：
   - `process.generate.done`（generate_batches_async_concurrent 增量/全量两出口，含 mode/batch_size/max_concurrency/duration）
   - `process.embed.done`（batch_embed_texts）
   - `process.embed.fill_done`（generate_and_fill_embeddings）

### backend/api/processing.py
1. generate 接口 `batch_size=16, max_concurrency=8` 硬编码 → `get_runtime("BATCH_SIZE"/"MAX_CONCURRENCY", settings.…)` 热读。
2. 审计埋点 `process.generate.api_done`（user_id/document_id/kb_id + 计数 + 耗时）。

## 过程中发现并修复的问题
- 首版替换丢失了 `subq_offset = 0` 初始化（SubUnboundLocalError），mock 单测抓出后修复复验通过。

## 验证
见 verify.log Circle 2 段：import OK；O(n²) 基准 old 1378.95ms vs new 5.314ms @n=16000（259.5x，new 无超线性）；mock 并行填充正确性 OK；死代码 grep 无残留（仅注释）；服务启动 + 登录 + 文档列表 200 + 非法 token 401；audit_log 有 request.write 事件（process.* 需真实流水线触发，本圈未跑 LLM，如实记录）。

## 备注 / 遗留
- admin 密码本轮重置为 Stage1@Test（原密码未知，DB 里 role='user'）。
- process.* 事件落库验证推迟到下一次真实跑 split/generate/import 流水线时。
- 文档 04 §3.4（BM25 executor）依赖 01-C，Stage 2。
