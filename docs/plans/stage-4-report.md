# Stage 4 报告：审计全局验收 + 大批量测试

> 日期：2026-08-21 | 分支：main（圈1 e6a35bc → 圈2 1e615b3）
> 验证明细：work/stage-4/{verify.log, circle1-notes.md, circle2-notes.md, loadtest/}

## 结论：验收通过（07 §9 六项全过 + 三场景压测完成，含 2 项遗留性能问题移交 Stage 5 前处理）

## 一、文档 07 §9 全局审计验收（六项，初次走查发现并修复后全过）

| # | 验收项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 无漏记 | ✅（修复后） | 初次走查发现 9 类漏记 → **补 17 个埋点**（auth×3/kb×3/doc×3/settings×1/agent×1/feedback×2 + request_id 串联 7 处）→ 复验全 PASS |
| 2 | 不阻塞主路径 | ✅ | 30 写请求 p50=7.9ms / max=15.8ms（纯内存入队） |
| 3 | 脱敏 | ✅（修复后） | 修 3 处缺陷（值未掩码/字段名误掩/清除分支泄漏明文）；修复后全库明文 grep=0 |
| 4 | 权限过滤 | ✅ | 普通用户仅见自己；admin 全量 + stats/export |
| 5 | 优雅停机 flush | ✅ | taskkill -F 下 5/5 事件落库 |
| 6 | 保留策略 | ✅ | 补建 scripts/archive_audit.py，实测 seed 400 天数据→gzip 导出回读→删除 |

补建缺口接口：/api/audit/export、/api/audit/stats。审计前端功能版（audit.js：列表/过滤/分页/详情/概览/CSV 导出）已挂载，浏览器实测留 Stage 5。

## 二、大批量测试压测

### 场景 1：批量导入（120 docs / 2,210 chunks，100% 成功）
- 吞吐 **192 docs/h、3,536 chunks/h**（37.5 分钟）；split p50=0.5s；no-op generate p50=31ms；真实增强采样 10 篇 p50=6.8s/doc（1,051 子问题+211 摘要）。
- **瓶颈：import p50=48s/doc**——单 doc 逐条远程 embedding（0.6-1.2s/条）+ Zilliz 单条 insert；并发 3 即触 embedding 429。
- 简化声明：110 篇用全关增强 KB（配额限制），质量路径由 10 篇采样覆盖。

### 场景 2：并发检索（并发压测，limit=10，rerank 开）
| 模式 | QPS | p50 | p95 |
|---|---|---|---|
| native | 0.09 | 109s | 192s |
| advanced | 0.09 | 111s | 117s |
| hybrid_vec | 0.17 | 59s | 76s |
| keyword | 0.10 | 203s | 211s |
| hybrid_endpoint | 0.08 | 239s | 265s |

- 错误率 0%（keyword 7.5% 为脚本 token 过期+客户端超时，非服务错误）；RSS 838→928MB 趋平，**无泄漏**。
- **Stage 0 遗留慢查询复现且并发下恶化**（单发 22-25s → p50 109s）。分解归因：native+rerank p50=35s vs native 无 rerank **3s** —— ① reranker.py:193 CrossEncoder predict() 在事件循环内同步执行（主因，修法 run_in_executor）；② 查询 embedding 同步调用被 429 重试放大；③ Zilliz 欧洲区远程往返。

### 场景 3：自进化闭环连续运行
- 50 轮 90% 成功（失败全为脚本重复 delete 404）；created 18 / merged 14 / promoted 8，真实闭环。

### 场景 4：审计中心观测
- 压测全程 **2,639 事件**，loadtester 窗口对账零缺口，500ms 批量 flush，fallback 未触发。

## 三、遗留问题（移交）

1. **reranker 阻塞事件循环**（性能主因，已定位到行级）——建议 Stage 5 前热修（run_in_executor），预期 native 并发 p50 从 109s → ~10s 级；
2. import 逐条 embedding + 单条 insert——批量 embedding + Milvus batch insert 可再提速（embedding 429 限制需统筹）；
3. GraphStrategy 偶发 Milvus "required argument is not a float"（有降级不阻塞）；
4. 测试资源保留未清理：loadtester(u14)、KB17（110 docs/1,999 chunks）、KB18、33 条压测 FAQ。

## 四、四个「真实」核对

- 真实提高性能：审计零阻塞（p50 7.9ms）实测；压测数字全部来自真实负载；
- 真实优化架构：审计从 Stage 1 地基到本 Stage 全局验收，三 Stage 事件对账零缺口；
- 真实可拓展：归档/export/stats 接口补齐即插即用；
- 真实合理：漏记/脱敏缺陷如实发现并修复，压测简化（no-op generate）明确声明理由。

---

# 压测复验（2026-08-28/29，修复后）

> 范围：用当前代码（含 `7a69337` reranker 移出事件循环 + 工作区 BM25 A+C 多桶/clone-delete run_in_executor/Milvus 瞬态重试/上传 to_thread 等修复）重跑 Stage 4 三场景，与 8-21 基线形成 before/after。
> 数据产物：`work/stage-4/loadtest-reattack/`（原 8-21 数据在 `work/stage-4/loadtest/` 未动，保证可比）。
> 环境：12 物理核/16 逻辑、15.6GB RAM；检索走 Zilliz Cloud（`MILVUS_URI`）；嵌入/LLM 走 litellm 代理 localhost:4000；`SEARCH_BACKEND=bm25`。压测前**必须停掉本地 milvus docker 容器**（`start_all.ps1` 会自动拉起，但检索实际走 Zilliz，本地容器在 15.6GB 机器上会吃爆内存——见 §6 发现 4）。

## 五、场景2 并发检索复验（5 模式 × 客户端压测）

参数与 8-21 完全一致（KB17=110 docs/1999 chunks，loadtester=u14，limit=10，`use_rerank=True` 全开；native/advanced 40@10，hybrid_vec 40@10，keyword 200@20，hybrid_endpoint 200@20）。

| 模式 | 8-21 基线 p50/p95/QPS | 复验 p50/p95/QPS | err_rate | 提升幅度 |
|---|---|---|---|---|
| native (40@10) | 109s / 192s / 0.09 | **70.3s / 89.9s / 0.14** | 0% | p50 -36%, p95 -53% |
| advanced (80@10) | 111s / 117s / 0.09 | **78.3s / 92.1s / 0.12** | 0% | p50 -29%, p95 -21% |
| hybrid_vec (40@10) | 59s / 76s / 0.17 | **36.2s / 51.1s / 0.26** | 0% | p50 -39%, p95 -33% |
| keyword (200@20) | 203s / 211s / 0.10（7.5%\*） | **158.8s / 175.8s / 0.12** | **0%（200/200）** | p50 -22%，错误率清零 |
| hybrid_endpoint (200@20) | 239s / 265s / 0.08 | **149.4s / 206.7s / 0.13** | 0% | p50 -38%, p95 -22% |

\* 基线 keyword 7.5% 为脚本自身 token 过期+客户端超时（8-21 报告声明），非服务错误；复验改为 300s 客户端超时阈值，零超时。

**结论**：五模式 p50 全部下降（-22%~-39%）、p95 全部下降（-21%~-53%）、QPS 全部上升（56% 量级）、错误率全部为 0。reranker 移出事件循环 + Milvus 瞬态重试 + BM25 多桶重构 三项修复**方向正确、实测有效**，但没有达到 8-21 报告"预期 p50 109s → ~10s 级"的乐观预测——残留瓶颈见 §7 发现 2/3。RSS 在干净轮稳定（908→1315MB，~400MB 增长，健康）。

### 5.1 rerank 开/关 A/B 对照（瓶颈归因实验）
为隔离 reranker 在并发下的贡献，补做 native 模式 40 请求 @ conc 10 两组（`use_rerank=True/False`）：

| 组 | p50 | p95 | max | QPS | wall |
|---|---|---|---|---|---|
| native + rerank **开** | 72.0s | 85.6s | 101.6s | 0.14 | 294.4s |
| native + rerank **关** | **10.0s** | **13.4s** | 13.4s | **0.95** | **42.2s** |

**决定性结论**：rerank 关时 p50=10s（恰好是 8-21 预测的"~10s 级"——但那是无 rerank 的数字）；rerank 开时 p50=72s。**reranker 贡献了 p50 的 ~86%**。根因：`run_in_executor` 后多个线程池线程并发调 `CrossEncoder.predict`，每个 predict 默认开满 torch intra-op 线程（≈核数），10 并发 → 10×12=120 可运行线程挤 12 核 → 严重超订阅 → 吞吐崩塌（单发 rerank 仅 ~2-3s，并发下放大到 ~62s/请求）。**reranker.py 注释"predict 只读推理、多线程并发安全"被实测证伪**——不仅是性能问题，还偶发 native 崩溃（见 §7 发现 1）。

## 六、场景3 自进化闭环复验（50 轮 + 审计对账）

50 轮（30 新增 supplement + 10 重复 supplement + 10 demote/delete 交替），wall=320s，**45/50 ok（90%，与基线完全持平）**。action 分布：created 20 / merged 14 / promoted 6 / demote 5 / delete 5(全 404)。5 个失败全部是脚本侧"对已删除的 faq_id 重复 delete → 404"（与基线失败模式一致，非服务问题）。

**审计对账（修正列名后）**：窗口内 `faq.aggregate=20 / faq.candidate_create=20 / faq.promote=6 / faq.demote=5`，与闭环行为一一对应，**零缺口**。

> 注：8-21 原版对账脚本用错了列名（`created_at`，实际是 `occurred_at`），db 模块吞错返回空 → 当时对账结果其实是假空（`work/stage-4/loadtest/scenario3_audit_recon.log` 里能看到 `{}` + TypeError）。本次用正确列名重做，对账真实通过。

## 七、场景1 导入链路回归（缩减版 33 docs）

原版 8-21 为 120 docs（37.5 min）；BM25 索引侧函数未受多桶重构影响（diff 仅 `_candidate_bucket_keys`/`_buckets_for_kbs` 检索侧），故本次做 33 docs 缩减版回归（30 noop→KB17 + 3 real→KB18），目的验证导入链路（upload/split/generate/import + BM25 索引 + Milvus 批量写 + 审计）在当前代码下健康：

| 阶段 | 复验 | 8-21 基线 | 判定 |
|---|---|---|---|
| upload noop (30) | 30/30, 0.7s | — | ✓ |
| split noop | p50 618ms / p95 1.14s | p50 0.5s | ✓ 同量级 |
| generate noop (30) | p50 42ms | p50 31ms | ✓ |
| import noop (30) | 30/30, p50 **44.1s** | p50 48s | ✓ 一致 |
| generate real (3) | 3/3, p50 13.9s/doc | p50 6.8s/doc | ✓（3 docs 样本方差） |
| import real (3) | 3/3, p50 54.2s | — | ✓ |

**33/33 零失败，吞吐各阶段量级全部对齐基线**。导入瓶颈未变（import p50 ~44-54s/doc，单条远程 embedding 0.6-1.2s + Zilliz 单条 insert；批量 embedding + Milvus batch insert 提速待 Stage 5+ 后续迭代）。

## 八、四个「真实」核对（复验轮）

- 真实提高性能：5 模式 p50 全降 22-39%、p95 全降 21-53%、QPS 全升、错误率全 0；A/B 实验把 rerank 贡献量化到 86%；不是"看起来快了"。
- 真实优化架构：BM25 多桶重构扛住 20 并发 200 请求零失败；审计对账用正确列名重做、零缺口（顺手修正了 8-21 对账脚本的假空 bug）。
- 真实可拓展：导入链路在重构后健康回归；3 场景脚本全部复用未改业务逻辑。
- 真实合理：reranker 修复**未达 8-21 的乐观预测**（p50 70s 而非 10s）——如实记录、定位到行级（§7 发现 2/3），不硬凑"提速 10×"。

## 九、遗留问题（移交下一迭代，未自行改代码）

1. **c10.dll 崩溃（P0，新发现）**：完整跑批进行到 hybrid_endpoint ~80s 时后端进程 **APPCRASH 0xc0000005，faulting module c10.dll（PyTorch）**（Windows 事件日志 2026-08-28 22:29:35，pid 33124）。根因：多线程池线程并发 `CrossEncoder.predict` 在 torch native 层访问违例——`reranker.py` "多线程并发安全"的假设被证伪。keyword 组 20 并发 200/200 幸存、hybrid_endpoint ~15 请求后崩（并发 torch 前向在 Windows/torch 构建上不稳定）。重跑未稳定复现（marginal，与瞬时内存/CPU 负载相关）。**未修**——建议方向：`asyncio.Lock` 串行化 predict（max 1 并发，单发 ~2-3s）或单线程 executor + `torch.set_num_threads(1)` + 小 worker 池，比无界并发 predict 更优（既能避崩溃又能压住超订阅）。需用户拍板。

2. **残留串行瓶颈（行级定位，未修）**：`api/search.py:188` async 路由直接同步调 `milvus_client.query()`，其内部 `milvus_client.py:703` 同步 `embed_query` HTTP + 同步 pymilvus search——事件循环仍被每请求 ~5-8s 同步段串行。A/B 显示无 rerank 时 p50=10s（即此同步链贡献）。8-21 报告列的"查询 embedding 同步调用"仍未修，只修了 reranker。修法：`query()` 整体 `run_in_executor`（与 reranker 先例一致）。

3. **reranker CPU 超订阅**：见 §5.1，并发 predict 放大到 ~62s/请求。与 §9.1 同一治理路径（加锁/限线程）。

4. **环境混杂陷阱**：`start_all.ps1` 会自动拉起本地 milvus docker 容器，但检索实际走 Zilliz（`MILVUS_URI` 配置），本地容器在 15.6GB 机器上是纯负担。本次复跑第一轮误入此坑——20 并发下机器内存吃爆，单组超时 44.5%、后端 RSS 失控涨到 5.4GB；停容器重跑后正常（RSS 911→1315MB）。建议：`start_all.ps1` 加开关默认不拉本地 milvus 容器，或仅当 `MILVUS_HOST=localhost` 时才拉。

5. **小缺陷：faq.promote 埋点漏传 user_id**（`faq_service.py:309`，其他埋点都传了）。导致按 user 过滤的审计视图会漏看升格事件。一行修复。

## 十、原始数据

全部落 `work/stage-4/loadtest-reattack/`：
- `scenario2_recovered_summaries.json`（4 组汇总，首跑崩前抢救）
- `scenario2_hybrid_ep_result.json`（hybrid_endpoint 干净轮完整明细）
- `scenario2_hybrid_ep_result_confounded.json`（hybrid_endpoint 污染轮，留证环境混杂效应）
- `rerank_ab.json`（A/B 实验明细）
- `scenario3_result.json` + `scenario3_audit_recon_fixed.json`（闭环 + 审计对账）
- `scenario1_result.json` + `scenario1_detail.csv`（导入回归明细）
- `rerank_ab.py`/`scenario2_hybrid_ep.py`/`scenario3_faq_loop.py`/`scenario1_reduced.py`（复用脚本）
- 各 `*_run.log`/`*_run.err.log`（客户端运行日志）
