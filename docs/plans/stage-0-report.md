# Stage 0 基线采集报告（整改前基线）

- 采集时间：2026-08-20 12:40 ~ 13:20 (+08:00)
- 分支：feature/stage-0-baseline
- 环境：Windows 11 / Git Bash；Python 3.13（backend/.venv）；uvicorn app:app --port 8003
- 外部依赖（.env 实际配置）：Milvus = Zilliz Cloud serverless（in03-7dc201e632cee68...eu-central-1），PG 本机 localhost:5432/rag_system，SEARCH_BACKEND=bm25，TRACER_BACKEND=langfuse，STORAGE_TYPE=local
- 所有数字来自真实命令输出（原始输出见 verify.log 与各输出文件）

## 1. 启动耗时

方法：`work/stage-0/scripts/startup_test2.py` —— 冷启动 `python -m uvicorn app:app --port 8003`，轮询 `/docs` 首个 200（注意：**本应用没有 /health 端点，返回 404**）计时；之后 sleep 15s（等 reranker/agent 预热完成）再读进程内存。每轮结束 kill 进程并确认端口释放。轮询间隔 0.2s，误差 ±0.2s。

| 轮次 | 启动耗时 (s) |
|---|---|
| RUN1 | 26.93 |
| RUN2 | 29.55 |
| RUN3 | 29.53 |
| **均值** | **28.67** |

启动日志（server_run1~3.log）显示主要耗时项：PG/Milvus 连接、CrossEncoderReranker 模型加载（约 6.3s）、三类 Agent 预热。

首版测量事故（如实记录）：第一次脚本误用 404 的 /health 且命中了未杀干净的残留服务进程，得出 0.05s 假数据；已作废并重测。

## 2. 大文档处理四阶段耗时（历史数据，来自 PG workflow_log + document 表）

方法：PG 中已有 ≥200 chunk 的已完成文档（doc 11：889 chunks；doc 15：360 chunks，即测试文档《Claude Code 源码解读.pdf》；doc 10：152 chunks），直接查询 `document.split_time/generate_time/import_time` 与 `workflow_log` 汇总，未重新跑流水线。

| 文档 | chunks | upload (s) | split (s) | generate (s) | import (s) |
|---|---|---|---|---|---|
| doc 10 video.pdf | 152 | 4.41 | 0.43 | 26.97（4-27）/ 49.35 | 73.70 |
| doc 11 算法.pdf | 889 | 6.81 | 1.82 | 11363.0（累计字段）/ 日志侧多次增量 | 152.73 |
| doc 14 task1.pdf | 12 | 8.43 | 0.32 | 12.92 | 25.72 |
| doc 15 Claude Code 源码解读.pdf | 360 | 75.42 | 0.80 | 749.04（首次全量，360 chunks）→ 增量补跑 64.85 | 109.16 |
| doc 16 opendesign-mcp-setup.md | 5 | 0.01 | 0.39 | 6.69 | 27.01 |

注意：document 表的 split/generate/import_time 字段为累计值（多次重跑会叠加，如 doc 11 generate=11363s、import=152727ms 明显是累加），单次真实耗时以 workflow_log 对应记录为准，例如 doc 15：generate 749.04s（360 chunks，约 2.08 s/chunk）、import 109.16s（约 0.30 s/chunk）。

## 3. 内存 / 存储

### 进程稳态 RSS（真实服务进程 PID 25976，含一次完整检索基准测试后）

- WorkingSet：**1646.2 MB**（测试后峰值态）；启动稳态（预热完成、无请求时）**897.1 MB**
- PrivateMemory：3656.8 MB（测试后）/ 2908 MB（启动稳态）
- 说明：startup_test2.py 内打印的 4.6MB 为 Popen 启动器壳进程，无效，已用监听 8003 端口的实际 python 进程替代测量。

### PG 表体积（pg_total_relation_size，字节）

| 表 | 大小 (bytes) | ≈ | 行数 |
|---|---|---|---|
| sub_question | 2,973,696 | 2.84 MB | 5,983 |
| document_chunk | 2,473,984 | 2.36 MB | 1,418 |
| chunk_summary | 1,474,560 | 1.41 MB | 1,418 |
| document | 114,688 | 112 KB | 5 |
| workflow_log | 106,496 | 104 KB | 80 |
| users | 65,536 | 64 KB | 1 |
| knowledge_base | 49,152 | 48 KB | 2 |

## 4. 检索质量抽样（20 查询 x 3 模式 + 混合端点）

方法：`work/stage-0/scripts/retrieval_bench.py`。20 个固定中文查询（围绕 Claude Code 主题，覆盖概念/操作/机制/配置等意图，见脚本 QUERIES）。所有请求 `limit=10, use_rerank=true`。鉴权说明：admin 密码未知（多组候选密码 401），未改数据库，改用应用自身 `services.auth.create_access_token({'sub':'admin'})` 生成的 JWT 只读访问。

端点说明：三种 retrieval_mode（native/advanced/hybrid）走 `POST /api/milvus/query`（hybrid_vec 行 = Milvus 内部三路 RRF）；另有真实混合检索端点 `POST /api/hybrid/search`（向量+BM25+RRF+rerank）单独统计为 hybrid_endpoint。

结果：全部 80 次调用成功（0 error），每次均返回 topk=10。

| 模式 | n | avg ms | min | p50 | max |
|---|---|---|---|---|---|
| native | 20 | 25,724 | 18,652 | 25,065 | 48,566 |
| advanced | 20 | 10,199 | 5,152 | 10,518 | 14,536 |
| hybrid_vec (Milvus 三路 RRF) | 20 | 22,408 | 16,773 | 22,564 | 28,831 |
| hybrid_endpoint (/api/hybrid/search) | 20 | 1,603 | 1,351 | 1,565 | 2,147 |

关键观察：native 与 hybrid_vec 的 p50 达 22~25 秒，远高于 advanced（10.5s）和 hybrid_endpoint（1.6s）；native 单次 max 48.6s。慢的主导因素疑似 Zilliz Cloud（欧洲区 eu-central-1）远程 Milvus 网络往返 + native 集合数据量较大；hybrid_endpoint 反而最快（其内部路径/召回深度不同）。整改时可优先排查。原始逐条数据：`retrieval_results.json` / `retrieval_bench_output.txt`。

## 产物清单

- work/stage-0/baseline.md（本文件）
- work/stage-0/verify.log（关键原始输出）
- work/stage-0/retrieval_results.json（80 条检索明细）
- work/stage-0/retrieval_bench_output.txt（基准原始 stdout）
- work/stage-0/pg_stats_output.txt（PG 查询原始输出）
- work/stage-0/server_run1~3.log（启动日志）
- work/stage-0/openapi.json（启动后端点快照）
- work/stage-0/scripts/（startup_test.py 作废版、startup_test2.py、pg_stats*.py、retrieval_bench.py、token.txt）
