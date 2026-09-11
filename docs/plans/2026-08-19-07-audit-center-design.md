# 设计文档 07：全局审计中心（Audit Center）

> 状态：待审阅 | 日期：2026-08-19
> 需求来源：用户评审（2026-08-19）——「记录每一条记录，每一个数据，做全透明的效果」
> 定位：横切面基础设施，覆盖 01-06 全部整改引入的写路径；也是文档 06「GitHub 式 fork/PR 共享协作」模式的可信性底座

## 1. 目标与原则

- **全透明**：系统内每一条数据的每一次创建/修改/删除都可回答「谁、何时、做了什么、改了什么（before→after）、从哪来（request_id/IP）」。
- **只追加**：`audit_log` 在业务代码路径上只有 INSERT，无 UPDATE/DELETE（数据清理仅由归档脚本执行）。
- **旁路不阻塞**：审计写入失败不允许影响业务主流程（异步批量管道 + 降级）。
- **脱敏**：敏感值（API Key、密码）永不落明文。

## 2. 审计事件目录

| 分类 | 事件（action） | 记录要点（detail） |
|---|---|---|
| 认证 | `auth.login` / `auth.register` / `auth.logout` / `auth.login_failed` | user、IP、UA、成败 |
| 配置 | `settings.update` | 每个变更 key 的 before→after（敏感值掩码） |
| 知识库 | `kb.create` / `kb.update` / `kb.delete` | 元数据 before→after（含切割策略/增强器变更） |
| 文档 | `doc.upload` / `doc.delete` | 文件名、大小、路径 |
| 处理管线 | `process.split` / `process.generate` / `process.embed` / `process.import` | 文档、chunk 数、各阶段耗时、token 用量、启用的策略/enhancer 集 |
| 补生成 | `process.generate.missing` | 触发人、缺口统计、补生成结果（文档 03 显性动作，必须可审计） |
| 自进化记忆 | `faq.candidate_create` / `faq.promote` / `faq.demote` / `faq.delete` / `entity.upsert` / `relation.upsert` / `memory.supplement` | kb 归属（私有/自有共享/他人共享）、owner/submitter、问题与答案（蒸馏前后）、热度变化、升格路径（阈值/审核/显式）、用户补全原文 |
| 知识共享协作 | `kb.share` / `kb.unshare` / `kb.clone` / `faq_pr.submit` / `faq_pr.merge` / `faq_pr.reject` | 分享对象与权限（can_write_directly）、克隆来源与快照范围、PR 双方（提交人/库主）、审核意见——共享协作全生命周期 |
| 反馈 | `feedback.like` / `feedback.dislike` | trace_id、评价内容 |
| 检索（可选） | `search.query`（默认关闭） | query、命中层（FAQ/实体/向量）、延迟——量最大，由 `AUDIT_SEARCH` 开关控制 |

## 3. 架构

### 3.1 表结构（PG）

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id            BIGSERIAL PRIMARY KEY,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id       INTEGER,                -- 可空（系统事件）
    action        VARCHAR(64) NOT NULL,   -- 如 faq.promote
    resource_type VARCHAR(32),            -- kb/document/faq/config/...
    resource_id   VARCHAR(64),
    kb_id         INTEGER,
    request_id    VARCHAR(64),            -- 中间件生成，贯穿一次请求的所有事件
    client_ip     VARCHAR(64),
    user_agent    TEXT,
    detail        JSONB                   -- before/after（脱敏后）、指标等
);
CREATE INDEX IF NOT EXISTS idx_audit_time   ON audit_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log (action, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user   ON audit_log (user_id, occurred_at DESC);
```

### 3.2 写入管道（异步批量，不阻塞业务）

- 业务侧调用 `audit.log(action, resource_type=..., detail={...})`——同步入队，微秒级，无 IO。
- 后台消费任务（lifespan 启动）：`asyncio.Queue` 满 100 条或每 500ms 批量 INSERT（executemany）。
- **降级链**：队列满/DB 写失败 → 先写本地日志文件（audit_fallback.log，带 error 级日志）再丢事件——绝不反压业务接口。
- 服务优雅停机（lifespan shutdown）→ flush 队列残留。
- `request_id` 由 FastAPI 中间件生成并注入 `request.state`，业务埋点与审计记录共享，实现一次请求内多事件的串联。

### 3.3 埋点方式（显式为主 + 中间件兜底）

- **显式埋点**（约 25 个调用点，均为一行 `audit.log`）：settings 保存、KB/文档 CRUD、处理管线四阶段、补生成、06 的全部记忆写入/升格/删除、KB 分享/克隆、PR 提交/合并/拒绝、反馈。
- **中间件兜底**：对所有非 GET `/api` 请求自动记录 method/path/status/耗时/用户（粗粒度），与显式事件通过 request_id 关联——保证「无漏记」的兜底层，显式事件提供细粒度。

### 3.4 脱敏规则

- `detail` 写入前过 `mask_sensitive()`：key 名匹配 `(?i)(key|secret|password|token)` 的值替换为掩码（保留前 4 后 4 位可辨识，如 `sk-1a***yz9`）。
- 用户密码、完整 API Key 永不记录。

## 4. API 与权限

| 接口 | 权限 | 说明 |
|---|---|---|
| `GET /api/audit` | 管理员全量；普通用户仅 `user_id=自己` | 分页 + 过滤：user/action/resource_type/kb_id/时间段/request_id |
| `GET /api/audit/export` | 管理员 | CSV/JSON 导出（复用过滤参数，流式输出） |
| `GET /api/audit/stats` | 管理员 | 事件量分布（按 action/按天），审计中心首页概览 |

权限沿用现有 auth 体系（services/auth.py）；用户表若无管理员标识则加 `is_admin` 字段（迁移）。

## 5. 前端（审计中心页面）

- 侧边栏新增「审计中心」（管理员可见）：
  - 概览卡：今日事件数、活跃用户数、Top 事件类型；
  - 时间线列表：过滤器（用户/动作/资源/知识库/时间范围/request_id）+ 事件详情展开（detail JSONB 渲染为 before→after 的 diff 视图）；
  - 导出按钮。
- 普通用户视角：同一页面按权限自动过滤为「我的活动」（个人透明）。
- 排期说明（2026-08-19 定案）：后端基础设施与埋点随 Stage 1-3 逐步上线；本页面（功能版）在 Stage 4 全局验收阶段补齐；完整美化归入 05b 最后整合阶段（见文档 05 第 7 节）。

## 6. 数据量与保留策略

- **量级估算**：核心写事件日均 10³~10⁴（含处理管线事件），年百万级——BIGSERIAL + 三索引无压力；检索审计默认关闭，开启时另行评估。
- **保留策略**：`AUDIT_RETENTION_DAYS`（默认 365，可配）；`scripts/archive_audit.py` 定期将超期数据导出 gzip JSON 后删除，归档文件保留。
- **按月分区**：数据量超千万再启用 PG 声明式分区改造，本期不做（YAGNI）。

## 7. 改动清单

> 排期（2026-08-19 用户定案：**埋点随各 Stage 逐步上线**）：
> - **Stage 1 初**：本清单的基础设施先行落地（audit_log 表 + audit 服务 + 中间件 + 查询 API）；
> - **Stage 1-3**：各 Stage 的写路径在编码时同步埋点——编码过程中最容易发现哪些字段值得透明；
> - **Stage 4**：全局检查验收（§9 六项，此时已有三个 Stage 的真实事件可查）+ 前端页面补齐。

| 文件 | 改动 |
|---|---|
| `backend/services/audit.py`（新） | audit 单例：队列 + 后台批量 flush + 脱敏 + 降级 + request_id 上下文 |
| `backend/services/database.py` | audit_log 建表 + `insert_audit_batch` + 查询/导出方法；users 表 is_admin 迁移 |
| `backend/app.py` | request_id + 兜底记录两个中间件；lifespan 挂载审计任务与 shutdown flush |
| `backend/api/audit.py`（新） | 三个查询接口 + 权限过滤 |
| 写路径埋点 | settings.py / knowledge_bases.py / files.py / processing.py / 06 的 save_* 与升格逻辑 / KB 分享与克隆（clone_kb/submit_faq_pr/approve_faq_pr）/ 反馈接口，各加一行 audit.log |
| `backend/services/runtime_config.py` | `AUDIT_SEARCH` / `AUDIT_RETENTION_DAYS` 入白名单 |
| `frontend/js/pages/audit.js`（新） | 审计中心页面（功能版，Stage 4 补齐） |

## 8. 前后对比

| 维度 | 当前 | 整改后 |
|---|---|---|
| 变更可追溯 | 无（仅应用日志，滚动丢失） | 全事件持久化，request_id 贯穿一次请求 |
| 配置变更 | 不留痕 | 每 key before→after 可查 |
| 自进化记忆 | （尚无功能） | 写入/升格/热度全程可查——fork/PR 共享协作模式的可信底座（谁补充、谁审核、何时合并全透明） |
| 透明度 | 黑箱 | 管理员全量视角 + 用户个人视角（「我的活动」） |
| 导出能力 | 无 | CSV/JSON 流式导出 |

## 9. 验证方式

1. **无漏记**：走完第 2 节事件目录的每个操作，audit_log 均有对应记录且 request_id 关联正确（一次请求多个事件可串联）。
2. **不阻塞**：模拟审计批量 flush 延迟（慢 DB）→ 业务接口耗时无感知变化，降级日志产生。
3. **脱敏**：修改 API Key 类配置 → detail 中值为掩码，全库 grep 不到明文。
4. **权限**：普通用户调 `/api/audit` 只见自己；导出接口仅管理员可用。
5. **优雅停机**：发送停机信号 → lifespan flush 队列残留事件全部落库。
6. **保留策略**：构造超期数据跑归档脚本 → 导出文件完整、表内删除。

## 10. 风险与备注

- **丢数据窗口**：进程崩溃时队列内未 flush 事件丢失（≤500ms 窗口 + 批量 100 条上限）——由兜底中间件的即时粗粒度记录部分补偿，可接受；金融级强一致才需要 WAL 式审计，本项目不需要。
- **埋点侵入**：约 25 个一行调用点，可接受；漏埋由兜底中间件粗粒度覆盖。
- **与 06 的联动价值**：审计中心让 GitHub 式知识协作可信（谁补充了什么、走了哪条路径——阈值升格/库主审核/显式、PR 何时合并拒绝、热度轨迹全透明）——简历叙事上两者互相成就：「审计驱动的可信知识进化」。
- **检索审计开关**：开启后量级可达日均 10⁵+，务必评估存储与保留策略后再开。
