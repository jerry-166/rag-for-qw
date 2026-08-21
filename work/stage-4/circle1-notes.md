# Stage 4 第一圈产物：文档 07 审计中心全局验收 + 审计前端页面（功能版）

日期：2026-08-21 | 分支：main（工作区，Stage 4 圈内）| 服务：uvicorn :8003，admin/admin123

## §9 六项验收逐项结论

| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 无漏记（事件目录走查） | **通过（修复后）** | 初次走查发现 9 类漏记（见下），补埋后复验全 PASS：kb.create/update/delete、doc.upload/delete、process.split/generate/import、agent.chat、feedback.like、auth.login/login_failed/register、settings.update 均有显式事件 + request.write 兜底事件；检索三模式（native/advanced/hybrid）由 request.write 覆盖（search.query 按 §2 默认关闭，符合设计） |
| 2 | 不阻塞（慢 DB/降级不反压） | **通过** | 30 个写请求（每个产生审计事件）p50=7.9ms / max=15.8ms——审计入队为纯内存操作；降级链（队列满/DB 失败 → audit_fallback.log）代码在 services/audit.py，本轮未触发（正常路径） |
| 3 | 脱敏（敏感值不落明文） | **通过（修复后）** | 修复前 settings.update 明文记录 API Key（发现 2 处漏洞：dict-key 掩码规则掩了字段名却放过值；清除配置分支记录原始 before）。修复后 LITELLM_API_KEY 落库为 `sk-a***0xyz`；测试产生的 3 条明文行已物理删除，全量 detail grep 明文=0 |
| 4 | 权限（普通用户只见自己；导出/统计仅管理员） | **通过** | 普通用户 /api/audit 仅返回 user_id=自己（total=2, user_ids={自己}）；查他人 user_id=403；export=403；stats=403；admin stats=200（today=581），export=200（CSV 128KB 头部正确） |
| 5 | 优雅停机 flush | **通过** | 发 5 条事件后 taskkill -F（严于 SIGTERM）→ 5/5 已落库（500ms 定时 flush 快于杀进程）；lifespan→audit.stop()→_flush() 路径代码确认。注：极端崩溃 <=500ms 窗口的丢失由 request.write 兜底中间件即时记录补偿（文档 10 已声明可接受） |
| 6 | 保留策略（归档脚本） | **通过（补建后）** | scripts/archive_audit.py 本轮新建并真实运行：dry-run 统计→seed 400 天前数据→导出 gzip JSON（回读校验通过）→表内删除 1 条。AUDIT_RETENTION_DAYS 环境变量可配（默认 365） |

## 漏记清单（初次走查发现）与修复

| 漏记事件 | 原因 | 修复 |
|---|---|---|
| auth.login / auth.login_failed / auth.register | 无埋点（登录成功仅 request.write，user_id=null） | api/auth.py 补埋 3 处 + request.state.audit_user_id 回填兜底事件用户 |
| kb.create / kb.update / kb.delete | 无埋点 | api/knowledge_bases.py 补埋 3 处（update 含 before→after，含策略/enhancers） |
| doc.upload（PDF/Markdown 两入口） | 无埋点 | api/files.py 补埋 2 处（文件名/大小/来源/耗时） |
| doc.delete | 无埋点 | api/documents.py 补埋 1 处 |
| settings.update | 无埋点；且本轮新埋点初版有脱敏缺陷（值未掩码/字段名被误掩/清除分支漏掩） | api/settings.py 补埋 + _mask_if_sensitive 前置掩码；detail 用 `config` 字段名避开 key 掩码规则误伤 |
| agent.chat | 无埋点 | api/agent.py 补埋（query/agent_type/sources_count） |
| feedback.like / dislike | 无埋点 | api/agent.py 补埋 |
| process.* 事件 request_id 缺失 | 埋点存在但不传 request_id，无法与兜底事件串联 | processing.py / knowledge_bases.py 改用 audit.log_from_request() 自动注入 |
| 归档脚本缺失 | §6 规划未落地 | scripts/archive_audit.py 新建 + 真实验收 |

**漏记修复数：17 个埋点补齐 + 3 个脱敏缺陷修复 + request_id 串联修复 7 处 + 归档脚本补建。**

基础设施工具：services/audit.py 新增 `log_from_request()`（自动注入 request_id/IP/UA）；api/audit.py 新增 §4 规划的 `/api/audit/export`（CSV/JSON）与 `/api/audit/stats` 两个缺口接口。

## request_id 串联验证

- 带 `X-Request-ID: stage4ridXXX` 的 native 检索 → 响应头回传同一 RID，request.write 事件 rid 精确匹配。
- 显式事件（kb/process/doc/agent/feedback/settings 类）现均与同请求的 request.write 共享同一 request_id（修复后抽查 kb.create rid=0d749d...、process.import rid=497b38... 均为请求级 UUID）。
- 单请求多事件串联：一次文档上传请求内 doc.upload + request.write 同 rid（upload 分支）。

## 审计前端页面（功能版）

- 新增 `frontend/js/pages/audit.js`：概览卡（24h 事件/活跃用户/总数/Top 动作，管理员）、事件表格（时间/用户/动作/资源/KB/request_id/IP）、过滤（action/user_id/request_id/resource_type）、分页、详情展开（detail JSONB）、CSV 导出（带 token fetch）。普通用户同页自动收敛为「我的活动」（后端权限过滤）。
- `js/api.js` 新增 AuditAPI；`js/app.js` 挂 window.AuditAPI + 'audit' 路由 case；`index.html` 导航「审计中心」+ script 引入；`css/main.css` 追加功能版样式。
- 验证：node --check 全过；API 数据契约（GET /api/audit 返回 {total,page,page_size,items[]}，stats/export 403/200 行为）已实测核对。**浏览器 UI 实测留待 Stage 5 浏览器验收**（本环境无浏览器），已标注。

## 验证命令与产物

- 主验收脚本：`work/stage-4/verify_audit.py`（可重复执行，幂等注册专用用户）
- 汇总日志：`work/stage-4/verify.log`（含四轮迭代完整真实输出：run2 发现漏记 → run3 发现脱敏缺陷 → run4 全 PASS）
- 辅助：`shutdown_flush_test.py` / `nonblock.txt` / `shutdown_flush.md`、服务日志 `server.log`

## 遗留 / 备注

- `process.generate.done`（document_processor 内部）user_id=None（后台任务无用户上下文），由同请求 api_done 事件（带 user）+ request.write 兜底，可接受。
- search.query 显式审计仍按 §2 默认关闭（AUDIT_SEARCH 未开启），由 request.write 粗粒度覆盖——符合设计。
- doc.delete 的 detail.file_name=null（document 表无该列），字段保留不阻断。
