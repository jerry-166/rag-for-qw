# Stage 1 Circle 1 — 审计中心基础设施（文档 07）改动摘要

日期：2026-08-20 分支：feature/stage-1-perf-startup

## 范围
仅文档 07「基础设施」：表 + 服务 + 中间件 + 查询 API + 脱敏。不含业务埋点（后续圈随编码同步）、不含前端页面（Stage 4）、不含导出/统计接口（后续）。

## 改动清单

### backend/services/database.py
- create_tables() 新增 `audit_log` 表（BIGSERIAL，11 列，与文档 3.1 一致）+ 4 索引（time/action/user/request_id）
- 新增 `insert_audit_batch(events)`：executemany 批量 INSERT，detail dict → JSONB
- 新增 `query_audit_logs(...)`：分页 + 过滤（user_id/action/resource_type/kb_id/request_id/时间段），返回 {total, page, page_size, items}

### backend/services/audit.py（新）
- `AuditService`：asyncio.Queue（maxsize 10000）+ 后台消费任务（攒满 100 条或 500ms 批量写）
- `audit.log(action, *, user_id=..., detail=...)`：埋点入口，同步入队微秒级，绝不抛异常
- 降级链：队列满 / DB 失败 / 服务未启动 → 写 audit_fallback.log（JSON Lines）后丢弃
- `start()` / `stop()`：lifespan 挂载 / 优雅停机 flush
- `mask_sensitive()`：递归脱敏，key 匹配 `(?i)(key|secret|password|token)` → 保留前4后4位掩码
- `new_request_id()`：uuid4 hex
- 落库经 `run_in_executor` 避免阻塞事件循环

### backend/app.py
- import Request
- lifespan：startup 调 `audit.start()`，shutdown `await audit.stop()`（flush 残留）
- 新增 `audit_middleware`（@app.middleware("http")）：
  - request_id：透传 X-Request-ID，否则生成；注入 request.state 并写回响应头
  - 异常兜底：未捕获异常即时同步粗记录（action=request.error）后 re-raise
  - 非 GET /api 请求兜底粗记录（action=request.write，method/path/status/duration_ms），与显式事件通过 request_id 关联

### backend/api/audit.py（新）+ api/__init__.py
- GET /api/audit：分页查询；权限 = 现有 `get_current_user`，管理员判定用现有 `role == 'admin'`（与 check_permission 一致，未加 is_admin 迁移）；非管理员强制 user_id=自己
- 注册到 api_router（prefix="/audit"）

## 设计取舍
1. 管理员判定：文档 07 提议加 `is_admin` 字段，但现有 users.role 已承载 admin 概念（auth.py 在用），本圈复用 role，避免重复权限轴；is_admin 迁移推迟。
2. 兜底事件 user_id 为空（中间件在鉴权前运行，token 解析放埋点里会增加耦合）；显式埋点（后续圈）会带 user_id，靠 request_id 关联。
3. request_id 单列索引额外加（查询过滤验证需要）。

## 验证
见 verify.log：import OK / 表+索引 OK / request_id 透传+请求级记录 OK / 脱敏（单元+端到端+库内无明文）OK / 401 与权限过滤 OK / 管理员全量 12 条 + request_id 过滤命中 1 条 OK。

## 后续圈待办
- 业务埋点约 25 处（settings/KB/文档/管线/记忆/分享/反馈）随各 Stage 编码同步
- GET /api/audit/export、/api/audit/stats
- runtime_config 白名单加 AUDIT_SEARCH / AUDIT_RETENTION_DAYS
- 前端审计页面（Stage 4）
