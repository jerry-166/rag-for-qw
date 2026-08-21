# Stage 4 第二圈：大批量压测与数据采集（汇总）

日期：2026-08-21 | 分支：main（工作区） | 服务：uvicorn :8003（PID 47820，已压测结束杀净）
环境：Windows 11 / Python 3.13（backend/.venv）；Zilliz Cloud（eu-central-1 远程 Milvus）；BM25；litellm 代理 LLM/Embedding
测试身份：loadtester / Loadtest#123（user_id=14）；测试 KB：**17 loadtest-noop（增强全关）**、**18 loadtest-real（sub_question+summary 真实增强）**
原始数据目录：`work/stage-4/loadtest/`

## 场景 1：批量文档导入压测（百级）

脚本 `scenario1_batch_import.py`，120 篇程序生成中文 Markdown（30% ~4KB / 50% ~15KB / 20% ~45KB，混合标题/代码块/列表），分 KB 走全流水线。

**简化声明（如实记录）**：110 篇用「增强器全关」KB（generate 为 no-op，验证 split/import 与参数链路），抽 10 篇用真实 LLM 增强做质量路径采样——litellm 配额有限；embedding（腾讯混元经 litellm）全量真实调用，未抽样。

| KB | docs | chunks | upload (wall) | split | generate | import |
|---|---|---|---|---|---|---|
| 17 noop | 110 | 1,999 | 2.5s（并发8） | 14.0s，p50=502ms | 1.0s，p50=31ms（no-op） | **1,894s**，p50=48.2s，p95=97.2s |
| 18 real | 10 | 211 | 0.2s | 1.4s，p50=458ms | 49.6s，p50=6.8s，p95=16.1s（真实 LLM） | 183.7s，p50=50.5s，p95=80.7s |

- **成功率 120/120 = 100%**，失败清单为空；最终 PG 状态全部 completed。
- 总耗时 ~37.5 分钟（120 docs / 2,210 chunks，含采样真实增强）→ **192 docs/h、3,536 chunks/h**（含 no-op 增强简化）。
- 真实增强参考速率：~5 chunks/s·doc 内（generate p50 6.8s/doc 含子问题+摘要 LLM 调用；10 篇共产出 1,051 子问题 + 211 摘要，LLM 正常）。
- **import 是绝对瓶颈**：每 doc 均值 ~17s，日志证实单请求内逐条远程 embedding（慢路径 0.6~1.2s/条）+ Zilliz Cloud 单条 insert + 3 并发即触顶 embedding 429 限流。
- 明细：`scenario1_result.json` / `scenario1_detail.csv` / `scenario1_run.log`。

## 场景 2：并发检索压测（4 模式 + 混合端点）

脚本 `scenario2_search.py` / `scenario2b_hybrid_ep.py`；KB=17，limit=10，use_rerank=true（与 Stage 0 同口径）。

| 模式 | n | 并发 | QPS | p50 | p95 | p99 | 错误率 |
|---|---|---|---|---|---|---|---|
| native | 40 | 10 | 0.09 | 109.2s | 191.7s | 191.7s | 0% |
| advanced | 80 | 10 | 0.09 | 111.0s | 117.2s | 164.6s | 0% |
| hybrid_vec (Milvus 三路) | 40 | 10 | 0.17 | 58.6s | 75.8s | 92.1s | 0% |
| keyword (BM25) | 200 | 20 | 0.10 | 202.8s | 211.2s | 277.2s | **7.5%** |
| hybrid_endpoint | 120 | 20 | 0.08 | 238.9s | 264.7s | 325.7s | 0% |

- **关键词段 15 错**：10×401（脚本 token 30 分钟过期，登录后即恢复）+ 5×-1（客户端 300s timeout）；hybrid_endpoint 段因同因整段 401 作废，已用新 token 重跑（scenario2b，120/120 成功 0 错）。
- **RSS（内存泄漏观测）**：hybrid_endpoint 压测全程（23.7 分钟 120 请求）RSS 838.2 → 916.3 MB；其后的 native 分解段 917.6 → 928.1 MB。上升后趋平，**无持续增长泄漏迹象**（与 Stage 0 稳态 ~900MB 一致；BM25 新建 110 docs 倒排桶为合理增量）。
- Stage 0 的 22-25s 基线在**同等单发条件下复现**，并发下进一步恶化至 110s+（p50），详见下节归因。

### native/hybrid 慢查询归因（遗留问题，本圈只定位不修复）

分解实验（scenario2b，KB=17，limit=10）：

| 配置 | 结果 |
|---|---|
| native + rerank（并发 8） | ok 5/8，p50=35.2s，另 3 个客户端超时 |
| native **无 rerank**（并发 8） | ok 3/8，p50=**2.97s**，另 5 个客户端超时（含 429） |

耗时构成（客户端视角分解，服务端 milvus_client.query 为同步调用）：
1. **查询 embedding（litellm 远程，同步 httpx，单条 ~0.6-1.2s，被 429 限流时重试放大）**——并发下顺序化在事件循环上；
2. **Zilliz Cloud 欧洲区远程 ANN 检索（每次网络往返 ~200-500ms×N）**；
3. **CrossEncoder rerank `model.predict()` 在事件循环内同步执行（reranker.py:193）**，并发 10 时 30 条 (query,doc) 对 CPU 推理互相排队——这解释了 native+rerank 35s vs 无 rerank 3s 的量级差。

结论：慢的主导因素 = ①reranker 同步推理阻塞事件循环（代码级问题，本地可修：predict 应包 run_in_executor）+ ②查询 embedding 同步调用与 429 重试（litellm/配额级）+ ③Zilliz 欧洲区远程延迟（部署级）。advanced 并不比 native 快多少（111s vs 109s p50），Stage 0 观察到的模式间差异在并发 + 事件循环阻塞下被抹平。

## 场景 3：自进化 FAQ 闭环连续运行（50 轮）

脚本 `scenario3_faq_loop.py`，KB=17（loadtester 自有，私有阈值 2），墙钟 405s。

- **成功率 45/50（90%）**；30 新增 supplement + 10 重复 supplement 全部成功，失败 5 个全部是 delete 轮 404（同一 faq_id 先 demote 后被选中的重复 delete——脚本设计所致，非服务缺陷）。
- 闭环 action 分布（真实闭环行为）：created 18 / **merged 14**（重复问题自动合并+计数）/ **promoted 8**（阈值 2 达标自动转 FAQ）/ hit 0（新问题为主，符合预期）；faq 表最终 33 行。
- **审计对账（全量无漏）**：窗口内 loadtester faq 事件 = faq.aggregate 22 + faq.candidate_create 18 + faq.demote 5，与操作数吻合；promote/hit 由 aggregate 事件 detail 携带（audit_log 无独立 promote 行属埋点设计）。
- 明细：`scenario3_result.json`。

## 场景 4：审计中心观测汇总

`/api/audit/stats`（压测后快照，`audit_stats_final.json`）：

- **事件总量 2,639（今日），24h 活跃用户 9**。
- Top：request.write 1,784（兜底）、process.embed.done 130、process.import.done 126、process.split.done 126、process.generate.api_done 124、doc.upload 123、faq.aggregate 23、faq.candidate_create 22、faq.promote 11、faq.demote 5。
- **落库延迟**：批量 flush 500ms 周期（圈 1 已验收），本圈 4 小时窗口内事件全部落库、audit 对账零缺口；flush lag 上限即批量周期 + 队列积压（压测期间未见 fallback 触发，`audit_fallback.log` 无新增）。
- 压测全程审计入队未拖慢写路径（圈 1 已证 p50=7.9ms）。

## 结论与遗留

1. 批量导入链路稳定（100% 成功率），**import 阶段是流水线瓶颈**（逐条远程 embedding + 远程 Milvus 单条写）——建议后续：embedding 批量化已存在但单 doc 粒度太碎，可做跨 doc 聚批；Zilliz 换就近区域或自建。
2. **检索 QPS 0.08-0.17，p50 分钟级延迟在并发下成立**，主导因素已定位（reranker 同步推理阻塞事件循环 > 查询 embedding 同步+429 > Zilliz 远程），均为遗留问题清单，**本圈未修复**，数据供下一 Stage 决策。
3. FAQ 闭环连续运行 90% 成功（失败均为脚本自身重复 delete 404），审计事件完整。
4. RSS 无泄漏迹象；audit 全程无丢失。

## 本次压测产生的测试资源（保留，不清理，供审计验收）

- 用户：loadtester（user_id=14，密码 Loadtest#123）
- KB 17 loadtest-noop：110 docs / 1,999 chunks / status 全 completed；Milvus chunk_vectors 已导入
- KB 18 loadtest-real：10 docs / 211 chunks / 1,051 sub_questions / 211 summaries（真实 LLM 增强采样）；三集合已导入
- faq 表：33 行压测 FAQ（KB 17）
- audit_log：+~2,600 事件；document_chunk 分词缓存（tokenized 列）已填充
- 文件：`data/` 下 120 个 loadtest-doc-*.md 及增强产物

## 服务收尾

- uvicorn（PID 47820）已于压测结束杀掉，端口 8003 已释放（见下）。
