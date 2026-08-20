# Stage 1 报告：性能与启动（01 + 04 独立项 + 07 基础设施 + 05a 批次 1）

> 分支：feature/stage-1-perf-startup（a21532e → 6ff8e3f，6 圈）| 基线：docs/plans/stage-0-report.md
> 结论：验收通过。启动耗时 -93.5%；文档 01 的 <2s 目标最终实测 1.87s 达标（用户裁决口径：有明显优化即可，不硬凑）。

## 核心指标（整改前 vs 后，全部实测）

| 指标 | 基线 | 整改后 | 变化 |
|---|---|---|---|
| 启动 → HTTP 首个 200（3 次均值） | 28.67s | **1.87s**（1.27/2.68/1.66） | **-93.5%** |
| readiness 全绿（/healthz 200，后台不阻塞） | ≈28.67s（无门控） | ~18-47s（不阻塞服务） | 服务可用性与预热解耦 |
| BM25 建桶（1046 chunk） | 1390ms（冷） | **94ms**（缓存热路径） | **14.7x** |
| 被逐出桶重建 | n/a | 39ms（分词缓存全命中） | LRU 淘汰代价可忽略 |
| 嵌入填充循环 O(n²) 修复 n=16000 | 1379ms | 5.3ms | **259x**（n=1000 时 19.5x） |
| 稳态 RSS | 897MB | 未显著变化（预热后台并发） | 见 verify.log |

启动耗时演进：28.67s 基线 → 7.26s（圈4 并发预热+readiness 门控）→ 1.87s（圈6 重 import 延迟化：pymilvus/jose/PDFParser/langfuse/Database 构造/tracing 后台化）。

## 各圈交付

1. **圈1（a21532e）07 审计基础设施**：audit_log 表+4 索引、异步批量管道（500ms/100 条，降级 audit_fallback.log）、request_id 中间件+异常兜底、脱敏（mask_sensitive，全库明文 grep=0）、GET /api/audit 分页查询（admin 全量 / user 限自身）。
2. **圈2（d6bec65）04 独立项**：generate/import 参数热读（BATCH_SIZE/MAX_CONCURRENCY）；O(n²) 填充修复；摘要/子问题嵌入并行 gather；删 process_document 死代码；process.* 埋点。
3. **圈3（5406191）01-C 分词缓存落 PG**：TEXT+LZ4 TOAST，jieba 空白 token 可逆编码（`'␣'+码点hex`）保证打分严格等价（np.allclose 5 query × 1046 chunk 一致）。存储比率实测 1.633（超设计预期 0.8-1.2，绝对量 +1.9MB，用户裁决接受，根因语料为代码文本）。
4. **圈4（aec099d）01-B 并发预热 + readiness**：lifespan gather 并发（同步重活线程池）；/healthz 503→200；search/agent 请求路径就绪门（等待/超时 503）；预热失败降级不 crash。
5. **圈5（a10577e+86482ad）BM25 LRU + 05a 批次 1**：LRU 双上限（BM25_CACHE_BUCKETS=16 / MAX_CHUNKS=100000，热改）+逐出审计+单桶超限兜底；前端 bug1-4 修复、console.log 19 处清零、auth.js 死代码删除、API_BASE origin 推导。
6. **圈6（6ff8e3f）启动 <2s**：importtime 定位后 6 处重 import 延迟化 + tracing 后台化；附带运行时配置参数化、Markdown 直传接口、.gitignore 加固（此前未提交改动一并纳入）。

## 已知遗留（如实记录）

- hybrid 检索返回 0 结果：**预存在缺陷**（基线 20/20 即 0 条）。定位：Milvus advanced 检索返回 auto_id 与 PG document_chunk.id 不一致 + BM25 按 user_id 分桶致 keyword 路 0 条。非 Stage 1 回归，待后续修复。
- native/Milvus-hybrid 单查询 22-25s 异常（基线发现）：未在本 Stage 范围，待排查。
- 05a 批次 2（配置分组保存、流式渲染节流）按计划随 Stage 2/4 补齐。
- process.* 审计事件需真实跑 LLM 流水线才触发，Stage 1 验证期未跑完整流水线。

## 验收清单核对（四个「真实」）

- 真实提高性能：✅ 全部指标来自真实命令（work/stage-1/verify.log 六段），无估算；
- 真实优化架构：✅ 审计管道/预热并发化/LRU/参数热读均为结构性改动，非局部补丁；
- 真实可拓展：✅ audit.log(...) 埋点入口供 Stage 2/3 使用；runtime_config 白名单可热改；
- 真实合理：✅ 未达标项（存储比率、初始 <2s）如实记录并经裁决，未美化。
