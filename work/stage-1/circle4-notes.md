# 圈 4（01-B）：并发预热 + readiness 门控

日期：2026-08-20 ｜ 分支：feature/stage-1-perf-startup

## 半成品处理

前次圈 4 尝试被 API 错误中断，留下未 commit 的完整度较高的改动：
- `backend/services/startup.py`（Readiness 信号，新文件，完整）
- `backend/app.py`（预热并发化 + /healthz，完整）
- `backend/services/runtime_config.py` 已含 STARTUP_PREHEAT / STARTUP_READY_TIMEOUT

**评估结论：半成品可用，选择继续完善而非 stash。** 缺口为设计 3.1 的"请求路径就绪门"，本圈补齐。

## 本圈改动

| 文件 | 内容 |
|---|---|
| `backend/services/startup.py` | （半成品沿用）Readiness：set_pending / mark / wait（超时+失败语义）/ snapshot / all_ready |
| `backend/app.py` | （半成品沿用）lifespan 不再同步连接 Milvus / 加载 BM25；`_preheat_all` 用 `asyncio.gather` 并发预热 milvus/search/agents；同步重活（Agent 构建、jieba、模型加载）经 `run_in_executor` 入线程池；`STARTUP_PREHEAT=false` 可跳过；新增 `GET /healthz`（全就绪 200，否则 503 + 各组件状态） |
| `backend/api/search.py` | 新增 `_await_ready(*names)`：milvus/query 门= milvus，elasticsearch/search 门= search，hybrid/search 门= milvus+search；未就绪带锁等待，超时/失败 503 + 原因 |
| `backend/api/agent.py` | 新增 `_await_agents_ready()`：chat / chat/stream / compare / preheat 相关 4 处调用点加门 |
| `backend/services/milvus_client.py` | （半成品沿用）连接从构造函数剥离为 `connect()`（返回 bool），构造零阻塞；query() 内 create_collections 兜底重连 |

- BM25 LRU（01 §7.1）按任务说明确认与预热解耦，**留下一圈**。
- 预热失败语义：任一组件异常 → `readiness.mark(name, err)`，不 crash；对应请求 503 带原因。

## 实测数据（详见 verify.log 追加段）

| 指标 | 基线 | 圈 4 后 |
|---|---|---|
| 启动 → HTTP 首个 200 | 28.67s 均值 | **7.26s 均值（7.33/6.62/7.84）**，-74.7% |
| readiness 全绿（/healthz 200） | ≈同首个 200 | 47.4s 均值（不阻塞服务） |
| HTTP 起来即登录 | 不可（服务未起） | login 200 @ 7.1s |
| 预热未完成时打 /api/agent/chat | — | 不报错，带锁等待至 38.6s 返回 200 |

预热时间线（boot_bench3.log）：search（BM25 1418 chunk 从 PG 读原文）~1s、milvus（Zilliz 连接）~1s（并发后与 BM25 不再串行叠加）、agents ~39s（3 Agent 构建 + reranker 加载 16~18s）——readiness 长尾是 agents，属预期（不影响服务可用性）。

## 预存在问题（非本圈回归，如实记录）

hybrid `/api/hybrid/search` 返回 0 结果：
- Stage 0 基线 `work/stage-0/retrieval_results.json` 中 hybrid_endpoint 20/20 全 0 条；圈 3 verify.log 亦多次 `results: []`。
- 离线复现定位：Milvus advanced 检索返回的 `chunk_id` 是集合 auto_id（如 135/179/205），与 PG `document_chunk.id`（5940+）不一致；RRF 融合后 `_enrich_results(final_ids)` 按 id 查 PG 全部落空 → 空结果。
- 另 BM25 按 user_id 分桶，admin(user_id=1) 无桶 → keyword 路 0 条。
- 建议修复方向：向量导入时写入 PG 真实 chunk_id（或查询层做 ID 映射）；BM25 桶键策略复核。留待后续圈/Stage 处理。

## 验收对照（文档 01 §6）

1. 冷启动计时：28.67s → 7.26s（目标 <2s 未达：剩余为 Python import + lifespan 同步段（PG 建表、storage、audit）+ uvicorn 起服，且 Windows 冷盘）。已按纪律如实记录，未达标部分原因是 import 链仍重（fastapi/langchain 等），后续可在 04/05 圈或独立圈继续压。
2. 未就绪请求：带锁等待不报错 ✅（agent chat 实测等待后 200）
3. 降级：预热失败不 crash（代码路径 mark(err)，未实测 Milvus 配错场景——如实注明）
4. 混合检索：API 行为与基线一致（200 success 空数组），无回归 ✅
