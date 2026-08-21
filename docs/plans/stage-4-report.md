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
