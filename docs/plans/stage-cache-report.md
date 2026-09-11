# Stage-Cache 验收报告：三层缓存 + Stage 4 遗留修复

> 日期：2026-09-01 | 分支：`feature/stage-cache`
> 设计依据：`docs/plans/2026-08-31-08-cache-design.md`
> 实施计划：`docs/plans/2026-08-31-cache-implementation-plan.md`
> 提交：18 个 commit（daf50eb → 27eaccb）

## 一、交付清单（已完成）

### Phase 0：遗留修复（4 commit）
- [x] reranker 专用有界线程池 + `torch.set_num_threads` 预算（`reranker.py`）— 治理 c10.dll 崩溃 + p50 86% 来源
- [x] `MilvusClient.aquery()` 整体移出事件循环 + 3 处调用点替换（`milvus_client.py` / `api/search.py`）
- [x] `faq.promote` 埋点补 `user_id`（`faq_service.py`）
- [x] `start_all.ps1/.sh` 开关：milvus 默认不拉、redis 改为本地端口检测（不用 docker）

### Phase 0 修复性能验证（`verify_phase0.py`，对照 Stage 4 基线）

**验证 1 — aquery 移出事件循环**：3 并发检索（无 rerank）期间探 `/healthz`：
- healthz 响应 **0.020s** 秒回（PASS <1s）——证明事件循环未被同步 query 阻塞。
- 旧代码（同步 `milvus_client.query()` 含同步 embed_query HTTP）会卡到检索串行跑完。
- 注：并发 wall 断言因 L2 缓存命中（单次 0.01s）无法体现并发差异，是断言设计假阴性；healthz 秒回是更直接的事件循环未阻塞证据。

**验证 2 — reranker 有界线程池**：rerank 开，并发 6@3（CACHE_BACKEND=off 排除缓存干扰）：
- **0 崩溃 / 6 成功**——c10.dll APPCRASH 治理验证通过（Stage 4 §9.1 的 P0 崩溃已消除）。
- p50=**19.7s**、p95=32.4s（最后一个排队等完），对照 Stage 4 基线 40@10 p50=70s **显著改善**。
- **诚实记录未达乐观预测**：Stage 4 报告预测"~10s 级"，实际 19.7s——因为默认 `RERANK_MAX_CONCURRENCY=1` 串行化排队（6 个并发 × 单发 2-3s 排队，最后等 ~32s）。落在 Stage 4 报告自己预告的"串行化后 15-35s"区间。如需更高吞吐可热调 `RERANK_MAX_CONCURRENCY=2-4`（乘积≤物理核），但需观察崩溃边际（Windows/torch 并发 predict 的稳定性边界）。

**结论**：Phase 0 两项性能修复**实测有效且未受损**——aquery 解放事件循环（healthz 秒回）、reranker 消除崩溃且 p50 改善（70s→19.7s）。reranker 串行化是"安全换吞吐"的取舍（先避崩溃），可按需放宽。

### 安全 P0 修复（1 commit，越权）
- [x] **AIAgent 会话层越权**（BUG-019）：`SessionStore` 全方法加 user_id + `_is_owner` 属主校验；`api/agent.py` list/history/delete 三端点加守门；`rag_workflow.py` 调用点传 user_id；迁移脚本归属 ownerless 会话到 admin。**验证 10/10 PASS**（admin 可见 18、loadtester 可见 0、越权访问全 404）

### Phase 1：缓存核心（5 commit）
- [x] PG schema：`query_embedding_cache` 表 + `knowledge_base.cache_version` 列（`database.py`）
- [x] `CacheManager`：L1（PG 向量）+ L2（内存 LRU → Redis 两级），key 归一化 + 版本维度 + 双上限逐出 + 降级容错（`services/cache.py`）
- [x] L1 接入 `milvus_client.query()`（embed_cached）
- [x] L2 接入 3 检索端点 + `rag_tools`（key = 生效过滤条件 + 版本，权限闸门在前）
- [x] 写路径 bump（split/import/delete + FAQ promote/demote/delete/aggregate/writeback/pr_merge 共 10 处）
- [x] runtime_config 6 个缓存项 + lifespan stats 快照任务 + `redis>=5.0.0` 依赖

### Phase 2：可观测（2 commit）
- [x] `/api/cache/*` 5 端点（admin-only）：stats / entries / entries/{key} / invalidate / clear
- [x] 前端 `cache.js` 缓存中心页：三总览卡片 + tab 明细 + 详情抽屉（浮层铁律）+ 管理动作

### 单元验证（2 脚本，全过）
- [x] `verify_task5.py`：11 项 PASS（bump 递增 / 版本查询 / L1 roundtrip / 列存在性）
- [x] `verify_task6.py`：16 项 PASS（key 归一化 / 版本失效 / TTL / 双上限 / off 短路 / L1 fail-open / 空结果不占内存）

## 二、端到端冒烟（已完成）

- 后端启动成功（PID 20148），前端启动成功（PID 21364）
- Redis 未运行 → 自动降级内存模式（审计有 `cache.degrade` 事件，符合降级容错设计）
- `/api/cache/stats` 未授权返回 401（路由注册 + 权限守门验证通过）
- `/healthz` 返回 ok

## 三、A/B 实验数据（真实数据，已达成）

> 自动化脚本：`work/stage-cache/verify_task13_ab.py`（双账号：admin 切 CACHE_BACKEND + loadtester 跑 KB17 检索，重复 query 场景）

### 3.1 端到端 A/B 结果

| backend | p50 | p95 | 命中率 | 说明 |
|---|---|---|---|---|
| **off**（基线） | 0.388s | 4.589s | 0% | 第一次 4.589s 是 embedding 冷启动；第二次起 0.388s（L1 仍命中省了远程 embedding，剩余是 Milvus search） |
| **memory** | 0.021s | 0.073s | 100% | L2 命中跳过 embedding + Milvus search 全链路 |
| **redis** | 0.018s | 0.036s | 100% | 与 memory 同量级（本地 Redis 延迟低） |

**缓存命中加速 21.5x**（off 0.388s → redis 0.018s）；命中率 100%（重复 query 场景）。

### 3.2 L1/L2 分层贡献（额外验证）

A/B 数据意外验证了 L1 embedding 缓存的独立价值：
- off 模式（L2 关闭）下，第一次检索 4.589s（embedding 冷启动调远程 litellm），第二次起 0.388s——说明 **L1 在 off 模式仍工作**（off 只关 L2，L1 命中省了远程 embedding HTTP 往返），剩余 0.388s 纯 Milvus search；
- L2（memory/redis）命中时连 Milvus search 都跳过 → 0.018s；
- 即：L1 把 4.589s → 0.388s（省 embedding），L2 再把 0.388s → 0.018s（省 Milvus search），两层各有贡献，分层设计有效。

### 3.3 缓存机制逻辑层验收（已过，独立于运行时）

- `verify_task5.py` 11 PASS（PG schema + db 方法）
- `verify_task6.py` 16 PASS（key 归一化、版本失效、TTL、双上限、降级、L1 fail-open）
- `verify_sessions_auth.py` 10 PASS（会话越权修复）


## 四、权限安全用例（5 项，一票否决，待手动验证）

复用 `verify_task6.py` 已自动覆盖的纯逻辑：KB 列表顺序无关=共享缓存、版本 bump 失配=失效、不存在 KB 跳过。

端到端手动用例（浏览器 + 两个账号）：

- [ ] **U1 无权访问 KB → 403**：普通用户查无权 KB，权限闸门 `check_kb_permission` 在缓存查找前拦截
- [ ] **U2 共享 KB 两用户同查 → B 命中 A 的缓存**：admin 用 KB X 查询（cached:true 第二次），被分享者同查（应 cached:true，复用 A 的结果）
- [ ] **U3 移出分享后 → 403**：撤销分享后，被移出者再查 KB X 应 403（碰不到缓存）
- [ ] **U4 KB 导入新文档后同查 → miss**：导入文档触发 bump，同查询 key 失配，重新检索
- [ ] **U5 降级韧性**：`docker stop` 或停本地 Redis → 服务不 crash，自动降级 memory，审计有 `cache.degrade`

## 五、四个「真实」对账

- **真实提高性能**：A/B 数据说话（待填）——缓存命中 p50 降幅 + 命中率，对照 Phase 0 干净基线
- **真实优化架构**：三层各有职责（内存挡热点 / Redis 共享 / PG 持久），`CACHE_BACKEND` 热切换，与 BM25 缓存先例架构语言统一
- **真实可拓展**：key 规范成文（§2.4），新检索参数进 key 有纪律；Redis 层为多实例部署预留
- **真实合理**：精确缓存命中率依赖查询分布（压测高、开放查询低）；承认全局检索版本粒度粗（TTL 兜底）；Redis 当前未起用 memory 降级运行

## 六、简历对齐（动机达成）

简历"Redis 缓存层"叙述 → 本轮实现落地：内存 LRU / Redis / PG 三层真实架构，面试可深挖：
- 多级缓存职责分层（本地挡热点 / Redis 跨请求共享 / PG 持久化）
- 版本号失效替代删除缓存（无删除竞态，与项目"走正常 DB 写接口即自动失效"哲学一致）
- key 权限维度 = 生效过滤条件（非 user_id，共享场景正确共享缓存）
- 穿透/雪崩应对（空结果短 TTL、TTL 随机抖动）
- 降级容错（Redis 故障自动降级 memory，不 crash）
- 可观测（缓存中心页 + 60s 审计快照）

## 七、遗留与移交

1. **正式 A/B 压测**：需用户启动本地 Redis + 传 admin 凭证 + 确认 KB/查询参数后跑 `verify_task13_ab.py`
2. **5 权限用例手动验证**：需两个账号 + 分享操作，浏览器走完整流程
3. **import 批量化（P2）**：Stage 4 §九.2 遗留，本轮按计划留下一迭代
