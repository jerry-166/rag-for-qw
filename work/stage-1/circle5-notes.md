# 圈5 记录 — 01 §7.1 BM25 LRU + 05a 批次1 前端功能修复

日期：2026-08-20　分支：feature/stage-1-perf-startup

## A. BM25 LRU 双上限（文档 01 §7.1）

### 改动
- `backend/config.py`：新增 `BM25_CACHE_BUCKETS`（默认 16）、`BM25_CACHE_MAX_CHUNKS`（默认 100000）。
- `backend/services/runtime_config.py`：两个配置加入 `WRITABLE_CONFIGS`（system 组，立即生效）。
- `backend/services/bm25_client.py`：
  - `_models` 改 `OrderedDict` LRU：命中 `move_to_end`；插入后 `_evict_to_limits` 按**双上限**（桶数 / 总 chunk 数）从头部逐出最久未用桶；
  - 建桶日志升级为 INFO：bucket / 文档数 / token 总数（内存观测）；
  - 逐出写日志 + 审计事件 `bm25.cache.lru_evict`（含逐出明细、剩余桶数、总量、两个上限值）；
  - 兜底：单桶 chunk 数 > `BM25_CACHE_MAX_CHUNKS` → 不缓存、每次现算，warn 日志 + 审计 `bm25.cache.oversized_bucket`；
  - `BM25_CACHE_BUCKETS=0` → 完全禁用模型缓存。
- `backend/app.py`：BM25 预热完成后输出各分桶 chunk 分布（内存观测汇总）。

### 实测（脚本：work/stage-1/bm25_lru_test.py + bm25_lru_live.py，输出见 verify.log 追加段）
1. 单元级 5 用例全 PASS：
   - 桶数上限 LRU 逐出顺序（命中刷新后 u1:2 被逐出，u1:1 保留，终态 `["u1:3","u1:1","u1:4"]`）；
   - 逐出审计事件产生（detail 含 evicted 明细）；
   - 总 chunk 上限（25 上限，三桶 10+10+10 → 逐出 a:1，余 20）；
   - 单桶超限不缓存 + 现算可用 + warn/审计；
   - 桶上限=0 禁用缓存。
2. 真实 PG 级（BM25_CACHE_BUCKETS=2，真实语料 1418 chunks / 2 桶）：
   - 建桶 0:1（372 docs）0.356s（首次含分词回写）；第 3 桶 9:1 触发逐出 0:1，audit_fallback.log 有 `bm25.cache.lru_evict` 事件（audit 队列未启动时降级写本地文件，符合 audit.py 设计）；
   - 被逐出桶重建 0.039s（分词缓存全命中 372/372，12.4ms）——印证"LRU 排在 C 之后"的设计前提。
3. 服务级：BM25_CACHE_BUCKETS=2 启动服务（`/docs` 200），3 用户连续关键词检索全 200。注：当前库存量 chunk 归属 user_id=0（load_from_database 兜底），登录用户桶为空 → 未在 HTTP 层触发逐出，逐出行为由 2 的进程内真实数据验证覆盖。

### 未做 / 待人工
- 逐出后内存 RSS 曲线观测（需大语料压测，本地 1418 chunks 无压力）。

## B. 05a 批次1 前端功能修复

| # | 问题 | 修复方式 | 自验 |
|---|---|---|---|
| 1 | `loadKnowledgeBables()` 拼写错误（search.js:284） | 改为 `loadKnowledgeBases()` | node --check + 方法名 grep 确认存在；待人工浏览器验收（需制造 KB 加载失败） |
| 2 | 历史查询内联 onclick 转义失效（search.js:623） | 改 `data-history-idx` + addEventListener，按数组下标回放，彻底消除转义问题 | node --check；待人工浏览器验收 |
| 3 | `search-stats-card` 双 style 属性（search.js:147） | 合并为单一 style="margin-top:16px; display:none;" | node --check + 源码 grep；待人工浏览器验收（需真实检索后确认显示切换） |
| 4 | 上传移除按文件名 key + 文件名注入内联 onclick（documents.js:141） | 改为闭包持 File 对象引用 + addEventListener；文件名显示加 `_escapeHtml`（documents.js 原无该 helper，已补） | node --check；待人工浏览器验收 |
| 6 | console.log 残留 19 处 | 全量删除（agent.js 10 / documents.js 4+空 forEach / pipeline.js 3 / app.js 2），保留 console.error | `grep -r console.log frontend/js` → 0 |
| 7 | auth.js 死代码 | 删除文件 + index.html script 标签（app.js 的 initAuthEvents 为实际使用路径，未动） | curl js/auth.js → 404 |
| 8 | API_BASE 硬编码 | 改 `window.API_BASE` 覆盖 + `location.origin.replace(/:\d+$/, ':8003')` 推导 | node 断言：localhost:8000→8003 / 127.0.0.1:8000→8003 / 192.168.1.5:8000→同主机 8003；无端口 origin 保持同源（反代场景合理） |

### 未含（按 05a 范围外或后置）
- 问题 5（上传进度/轮询）、9（假进度条）、10（流式节流）、A 部分配置分组保存：属 05a 后续批次/05b，本圈未做（任务范围仅"功能 bug 1-4、console 清理、auth.js、API_BASE"）。

## 验证命令（详见 verify.log 追加段）
- `backend/.venv/Scripts/python.exe work/stage-1/bm25_lru_test.py` → ALL PASS
- `backend/.venv/Scripts/python.exe -X utf8 work/stage-1/bm25_lru_live.py` → LIVE PASS
- BM25_CACHE_BUCKETS=2 启动 + 3 用户检索 → 全 200；预热日志输出分桶分布（0:1=372, 0:2=1046）
- `python -m http.server 8000`（frontend/）+ curl：index.html 及全部改动 JS 200，auth.js 404
- node --check 6 个改动 JS 文件全通过
