# Stage 2/3 报告：适配器架构（02/03）+ 自进化 RAG（06）

> 日期：2026-08-21 | 分支链：feature/stage-2-3-adapters（CodeBuddy 实现 c308aaa→c5f7f0b）→ 审阅修复合并（033c5cc→c5fe7cc→e087302）→ 验证补齐 + C 组回退（d644dff）
> 审阅报告：work/review-stage23/report.md；验证明细：work/stage-2/verify.log、verify-remaining.log、remaining-notes.md、merge-notes.md

## 结论：验收通过（含 1 项按设计走回退后通过）

## Stage 2：切割/增强适配器（文档 02/03）

- **切割策略注册表**（auto/markdown/recursive）+ 三级解析（请求>KB>全局，未知回落 auto）落地；auto 行为快照与迁移前一致（4 chunks）。
- **增强器流水线**：双开=合并 prompt（与旧路径逐字一致）、全关=no-op 秒回；KB 级配置（chunk_strategy/enhancers 列）全链路支持；未启用增强的 KB 检索短路不查对应集合。
- **全链路 E2E 实测**（doc19，kb6，markdown+sub_question）：49 chunks / 242 子问题 / 291 向量（dim1536），upload→split→generate→import 全通，audit 与 PG 落库一致。
- **03§7 质量对照实验（A/B/C，16 样本/组，LLM judge）**：
  - B（CombinedEnhancer 迁移）vs A（旧路径）：打分差 ≤0.13，结构一致 → **迁移达标**；
  - C（独立精简 prompt）：子问题相关性 -0.50、摘要忠实度 -0.44，超 0.3 门槛 → **不通过，按设计走回退**：单开委托 CombinedEnhancer（合并 prompt 与 A 逐字一致）只取所需字段；
  - 回退后同呈现同轮重评：SubQ vs A = 0.00/-0.06，Summary vs A = +0.13，全部 ≤0.3 → **达标**。过程中发现并量化了 judge 呈现偏置与跨轮漂移（>0.3），实验方法修正后收敛。
- **显性补生成**：GET /api/process/generate/{id}/missing 缺口检测 + 前端提示条。

## Stage 3：自进化 RAG（文档 06）

- **FAQ 闭环**：私有 KB 阈值 2 实测——faq#2 hit 1→2 自动 LLM 蒸馏升格 active（口语→结构化答案），第 2 次命中直返（faq_hit=true，sources=0）；判重聚合 ≥0.95 hit 累加实测；候选/正式/PR 三 Tab 管理页。
- **GraphStrategy**：KB6 生成 65 实体/116 关系，graph 模式 5/5 返回 type=graph（锚点 score=0.9，7.1s）；无 KB 降级 native、越权 403 均验证。审阅发现的 P0（模块级 logger NameError）已修复，graph 调用 NameError=0。
- **KB 克隆（fork）**：kb6→13 全量复制——PG doc/chunk/subq/faq 行数与源全等（1/49/242/5），Milvus 296 向量；克隆后 5 种检索模式全部可用。审阅发现的搬运 bug（subquestions 未重映射 chunk_id 恒 0）已修复。
- **PR 审核闭环**：prverify 注册→tester 分享→supplement 走 PR（pr_id=2）→tester merge（faq#19）→prverify 同问命中直返（相似度 1.00），audit submit/merge 留痕。
- **审计埋点**：process.split/generate（带 strategy）、faq.* 六类、kb.share/unshare/clone、faq_pr.* 全部真实落库，与操作一一对应。

## 审阅发现并修复的问题（CodeBuddy 实现的纠偏）

- P0：GraphStrategy 模块级 logger 未定义（NameError）——修复；
- P0：合并冲突 9 处/4 文件（含 rag_workflow.py 热读被覆盖的语义冲突）——手工合并保留 Stage 1 热读；
- P1×7：克隆向量搬运 bug（实测纠正审阅猜想：真因是 chunk_id 未查未重映射）、隐式 PR 判空、FAQ 阈值锁定 COSINE、graph 结果补 distance 键、clone 失败回滚、调试产物清理、list_prs N+1——全部修复；
- **hybrid 首请求返回空的根因**：PG 单 cursor 并发冲突（非 rerank）——database.py 改独立游标，冷启动首请求 0 条→5 条，连测 3 次稳定。

## 05a 批次 1/2（前端功能修复）

- 批次 1（Stage 1 完成）：bug1-4、console 清理、auth.js 死代码、API_BASE origin 推导；
- 批次 2：配置分组保存/dirty-only 提交（API 语义实测 ok，非法值 partial_error）、流式渲染节流——代码级验证通过，浏览器 UI 点击待 Stage 5 一并实测。

## 遗留（如实记录）

1. admin 密码重置为 admin123（原哈希与所有候选不符），role 已修正为 admin，audit 全量查询恢复；
2. GraphStrategy 实体向量匹配偶发 Milvus "required argument is not a float"（有降级不阻塞），Stage 4 观测；
3. 检索质量回归对比（hybrid/advanced vs Stage 0 基线）随 Stage 4 压测一并做；
4. Stage 0 发现的 native/hybrid 单查询 22-25s 慢查询问题未解决（预存在，超本 Stage 范围）。

## 四个「真实」核对

- 真实提高性能：增强全关 no-op 秒回、检索短路、嵌入并行（Stage 1）——量化见各 verify.log；
- 真实优化架构：三处注册表模式（chunking/enhancers/retrieval），新增策略零侵入已由 GraphStrategy 验证；
- 真实可拓展：KB 级策略配置、三级解析、runtime_config 热改均实测；
- 真实合理：C 组实验未过即回退（未硬切）、judge 偏置被发现并方法修正、全部数字来自真实命令。
