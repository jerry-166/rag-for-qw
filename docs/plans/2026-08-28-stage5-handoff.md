# 交接文档：Stage 5 收尾 + 全计划剩余工作

> 写给：CodeBuddy（接手继续执行）
> 生成：2026-08-28 | 交接自：Claude Code（jerry）
> 顶层依据：`docs/plans/2026-08-19-00-master-plan.md`
> 环境事实来源：`docs/plans/2026-08-20-loop-engineering-migration.md`

---

## 0. 一句话现状

六大 Stage（0→5）的**功能代码主体已全部写完**（包括最后的 UI/UX Stage 5），但存在两个断点：

1. **工作区有一批未提交、未验证的改动**（覆盖用户后来提的 5 个问题 + 上传/日志优化），这是最紧要先收尾的；
2. **"数据产物"这条线是断的**——Stage 0 基线数据、Stage 1~4 的量化报告不全，Stage 4 大批量压测没做，导致简历要用的"整改前 vs 整改后"对比数字缺失。

CodeBuddy 接手后**先做第一部分（收尾提交+验证），再与用户确认是否做第二部分（补数据产物）**——第二部分涉及"要不要回头补基线/压测"的取舍，不该替用户拍板。

---

## 1. 第一部分：未提交改动收尾（最紧要先做）

### 1.1 改动清单与文件

本轮会话（Claude Code）引入的改动，全部为**工作区未提交**（`git status` 显示 `M`）：

**后端（4 文件）**

| 文件 | 改动 | 备注 |
|---|---|---|
| `backend/api/files.py` | 上传接口 `parse_pdf` 用 `asyncio.to_thread` 抛线程池（方案 A，不阻塞事件循环）；加 `import asyncio` | 关键验证点 |
| `backend/services/pdf_parser.py` | 全部 `print` → `logger`（info/error/warning/debug），加 `init_logger` | 已过语法检查 |
| `backend/api/documents.py` | 文档列表加 `page`/`page_size` 参数 + `total` 返回 + `ORDER BY created_at DESC` + 返回 `knowledge_base_id` | 需验证 `db.fetchone` 存在 |
| `backend/api/knowledge_bases.py` | **注意：这个文件有 155 行 diff，但需核实哪些是本次改的、哪些是历史遗留**（git status 里它一直 `M`） | 交接时先 `git diff` 看清 |

**前端（5 文件）**

| 文件 | 改动 |
|---|---|
| `frontend/js/api.js` | ① TokenManager/UserManager 从 `localStorage` → `sessionStorage`（多账号）② `request()` 对写操作（POST/PUT/DELETE）失败自动 toast ③ `DocumentAPI.list` 加分页参数 |
| `frontend/js/app.js` | ① 登录/登出/初始化 6 处 `localStorage` → `sessionStorage` ② 新增全局 `btnLoading(btn, text)` 工具函数 + `window.btnLoading` 挂载 |
| `frontend/js/pages/documents.js` | ① 分页 `_renderPagination()` ② `_setUploading`/`_resetUploadZone` 上传 spinner ③ 删除重复错误 toast |
| `frontend/js/pages/knowledge-bases.js` | ① 时间倒序排序 ② 搜索筛选 `_renderKbList()` ③ 创建/更新/删除/分享/克隆加 `btnLoading` |
| `frontend/js/pages/faq.js` | 升格/降级/PR 合并-拒绝/补全提交加 `btnLoading`，删重复错误 toast |

### 1.2 未改动（已确认不涉及）

- `frontend/js/pages/agent.js`、`settings.js`、`pipeline.js`、`search.js`、`audit.js` —— 本轮只删了重复 toast，未加 btnLoading（agent 发送/compare 已有 disabled，settings 已有 loading）
- 批量上传（`multiple` 属性）**之前已实现**，本轮未动

### 1.3 必须做的验证（用客观命令，不靠"看起来对"）

改完先跑这些，全绿才算收尾完成：

```bash
# 1. 前端全部 JS 语法
cd frontend
node --check js/api.js && node --check js/app.js
for f in js/pages/*.js; do node --check "$f" || echo "FAIL: $f"; done

# 2. 后端 Python 语法
cd backend
py -c "import ast; ast.parse(open('api/files.py', encoding='utf-8').read())"
py -c "import ast; ast.parse(open('api/documents.py', encoding='utf-8').read())"
py -c "import ast; ast.parse(open('services/pdf_parser.py', encoding='utf-8').read())"
```

**关键功能验证（重点）**：

1. **上传链路**：起后端 + 前端，上传一个 PDF，确认
   - dropzone 出现 spinner + "MinerU 解析中…"
   - 事件循环不被阻塞（上传期间另开一个标签页发检索请求，应秒回）
   - 上传成功后进入进度轮询队列卡
2. **多账号**：同浏览器两个标签页分别登 admin 和另一账号，确认 token 互不串（sessionStorage 按标签页隔离）
3. **分页**：文档超 20 条时翻页正常，`total` 正确，KB 筛选重置页码
4. **KB 排序**：新建 KB 后列表按创建时间倒序，搜索框能筛选
5. **toast**：删 KB 时故意传错，确认弹出错误 toast（写操作才有，GET 不弹）

> ⚠️ 后端启动需用 `uvicorn app:app --host 0.0.0.0 --port 8003` 或 `py app.py`，前端静态服务端口 8001（见迁移文档 §5）

### 1.4 提交要求

- **不污染 main**：本轮改动如果只是收尾 bugfix，可直接提 main（master-plan 允许 main 可演示）；如果涉及新功能，建议 feature 分支
- **提交信息**遵循仓库风格：`feat(frontend):` / `fix(backend):` 前缀 + 中文说明（参考 `git log` 里 `1b48b46 feat(frontend): Stage 5 圈5...`）
- 提交前 `git diff` 逐文件核对，**特别警惕** `backend/api/knowledge_bases.py` 和 `backend/audit_fallback.log`、`backend/config.py` 之类可能混入无关改动

---

## 2. 第二部分：全计划剩余工作（需先与用户确认是否要补）

### 2.1 核心判断

master-plan 的终点是"支撑大批量测试与数据采集，沉淀简历素材"。**功能代码基本都在，但缺的是量化数据**，具体：

| 缺口 | 现状 | 影响 |
|---|---|---|
| Stage 0 基线 | 有 `work/stage-5/baseline/` 截图，但**系统性"整改前"性能基线**（启动耗时/四阶段处理耗时/内存/检索质量 20 查询命中）不完整 | 没有对照组，无法产出"提速 X%" |
| Stage 1~4 量化报告 | `git log` 有 Stage 4 "六项全过 2639 事件零缺口"，但启动优化/处理性能/压测报告是否齐备待核 | 简历量化点断档 |
| Stage 4 大批量压测 | **百级文档导入、并发检索、自进化闭环连续运行**未做 | 吞吐/延迟/成功率/资源占用这些核心数字没有 |

### 2.2 建议 CodeBuddy 先做什么

1. **先 `git log --oneline` 全扫一遍**，列出每个 Stage 有没有对应的 `docs/plans/stage-N-report.md`；
2. **盘出现有量化数字**（哪些 Stage 有基线对比、哪些是"感觉做了"但没数据）；
3. 把结果汇报用户，**问用户要不要补 Stage 0 基线 + Stage 4 压测**，还是就此打住。

---

## 3. 边界约束（CodeBuddy 必须遵守）

### 3.1 硬约束（来自 CLAUDE.md + master-plan §6/§7）

- **性能指标用客观命令当裁判**（pytest/耗时命令/体积查询返回值），不靠模型主观判断
- 任何性能指标未达标 → 立即暂停，带实测数据向用户报告，**不硬凑数字、不擅自降级目标**
- 遇到无法自行判断的岔路（方案取舍、指标疑点）→ 暂停询问，不绕过
- 审计埋点随编码同步落地，不等最后补
- 单圈超 30 次工具调用未收敛 → 强制暂停汇报

### 3.2 分支策略

- main 保持干净可演示，各 Stage 用独立 feature 分支（如 `feature/stage-N-xxx`）
- Stage 验收通过后才合入

### 3.3 上下文污染隔离

- 主循环只做编排：读计划 → 派子 agent → 汇总验证结果 → 判断收敛
- 子 agent 做具体实现，其 token 不进入主循环
- 子 agent 之间通过文件产物交接（报告、diff、验证日志），**落到 `work/stage-N/`**，不口头传递
- 子 agent 返回主循环的文本只允许"结论 + 产物文件路径"

### 3.4 环境约定（迁移文档 §1.5，勿重复排查）

- Python 命令用 `py`（不是 `python`/`python3`，会指向 WindowsApps 占位 exit 49）
- 后端 venv：`backend/.venv`（Python 3.13）；uv 装包若 403 加 `--index-url https://pypi.org/simple`
- 后端端口 8003，前端静态 8001；`frontend/js/api.js` 的 `API_BASE` 写死 localhost:8003
- 测试模型已由 litellm 提供，浏览器点击/调 API 即可，不需额外配 key
- 测试文档可用本机现有 PDF（如 `others/Claude Code 源码解读.pdf`）
- Git Bash 下路径用 `/`，脚本注意 CRLF vs LF
- codegraph 调用需显式传 `projectPath: "D:/workspace/rag-for-qw"`

### 3.5 已知风险（如实交接，不要掩盖）

| 风险 | 说明 |
|---|---|
| 方案 A 的局限 | `asyncio.to_thread` 只解决"事件循环不被单次解析阻塞"，单个上传请求仍要等解析完才返回；彻底秒回需方案 B（上传秒回 + `parsing` 状态机 + 后台解析），**尚未定是否做** |
| 模型是第三方代理（glm 系） | 自我收敛能力可能弱于原生 Claude，验收条件要写数值化、可机器判定 |
| `sessionStorage` 副作用 | 用户关闭标签页后登录态丢失（这是预期：多账号隔离的代价）；刷新页面登录态保留（同一标签页内） |

---

## 4. 遗留决策点（等用户拍板，CodeBuddy 不要自行决定）

1. **方案 B 是否做**：上传彻底异步化（秒回 + 后台 MinerU 解析 + `parsing` 状态）。当前只做了方案 A。这是架构改动，需用户点头 + 出方案。
2. **是否补 Stage 0 基线 + Stage 4 压测**：这是"数据产物"的核心，做不做取决于用户是否要衔接简历素材这一步。
3. **`backend/api/knowledge_bases.py` 的 155 行 diff**：需先核实哪些是本次改动、哪些是历史遗留，再决定提交范围。

---

## 5. 快速恢复我的工作现场（给 CodeBuddy 的上下文速查）

- 本次会话工作目录：`D:\workspace\rag-for-qw`（git 仓库，分支 `main`）
- 最近提交：`1b48b46`（Stage 5 圈 5 已完成并提交）
- 当前分支 `main` 上有大量未提交的 `M` 改动（就是 §1 的清单）
- 我本会话最后做的事：把 `pdf_parser.py` 的 print 换成 logger，语法已过
- 我本会话已创建的任务清单（task #19-#23）已全部标记 completed，只有 #18"提交所有前端改动"仍是 pending
