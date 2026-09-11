# Loop Engineering 迁移核查清单 + 提示词设计（rag-for-qw）

> 用途：将 rag-for-qw 的多 Stage 整改从 CodeBuddy 迁移到 Claude Code，用 Loop Engineering（`/goal` + `/loop`）跑开发。
> 生成日期：2026-08-20
> 顶层依据：`docs/plans/2026-08-19-00-master-plan.md`

---

## 第一部分：环境核查结论（现状 vs 缺口）

### 1. 核心运行时

| 项 | 现状 | 结论 |
|---|---|---|
| Claude Code CLI | ✅ v2.1.215（`C:\Users\ASUS\.local\bin\claude.exe`） | 已装，`/goal` `/loop` 原生可用 |
| 模型后端 | ⚠️ 第三方代理 `http://127.0.0.1:15721`，映射 glm-5.x | 可用，但收敛质量取决于 glm 模型；Loop 的退出条件/收敛检测要设得更保守 |
| CodeBuddy | ✅ 仍可用 | 可作为对照/回退 |

### 2. Skill（`C:\Users\ASUS\.claude\skills\`）— 已迁移/可用

| Skill | 用途 | 状态 |
|---|---|---|
| `save-knowledge` | 沉淀知识到 Obsidian + 生成操作手册 | ✅ 已存在 |
| `buglog` | 结构化 bug 日志 | ✅ 已存在 |
| `recall` | 知识库手动检索 | ✅ 已存在 |
| `agent-memory-mcp` | 混合记忆系统（Architecture/Patterns/Decisions） | ⚠️ skill 目录在，但 MCP server 未配（见 MCP 缺口） |
| `superpowers:*`（brainstorming / writing-plans / subagent-driven-development / systematic-debugging / test-driven-development / verification-before-completion / finishing-a-development-branch 等） | Loop 开发的核心方法技能 | ✅ 插件已装（superpowers 5.1.0） |
| `frontend-design` | 前端 UI 规范 | ✅ 已装（文档 05 UI/UX 阶段用） |
| `skill-creator` | 造新 skill | ✅ 已装 |

### 3. MCP Server（`.claude.json` → `mcpServers`）— 现状仅 2 个

| MCP | 现状 | 用途 | 是否需要 |
|---|---|---|---|
| `pencil` | ✅ 已配 | 绘图（Pencil） | 保留（UI 原型可选） |
| `codegraph` | ✅ 已配 | 语义代码索引（explore/search/node/callers/callees/impact） | **Loop 开发关键**，强烈建议保留并优先用 |
| `github` | ❌ 缺失 | 分支/PR 操作（多 Stage 多分支开发需要） | **建议补**：`npx -y @modelcontextprotocol/server-github`，需 GITHUB_PERSONAL_ACCESS_TOKEN |
| `agent-memory-mcp` | ❌ 缺失（仅 skill 目录在） | 持久记忆（Architecture/Patterns/Decisions）——Loop 跨会话记忆 | **建议补**，否则 `/goal` 多圈循环间的"决策记忆"只能靠文件 |
| `chrome`（superpowers-chrome CDP） | ❌ 缺失 | 浏览器 DOM 分析（文档 05 UI 实测） | **建议补**：连用户已开的 Chrome |
| `playwright` | ❌ 缺失 | 自动化测试/截图/表单填写（文档 05） | 建议补，UI 阶段再决定 |

### 4. Hooks（`C:\Users\ASUS\.claude\hooks\`）

- 文件已存在：`kb-inject.js` / `bug-capture.js` / `bug-detect-user-report.js` / `bug-failure-capture.js` / `hook-utils.js` / `bug-utils.js` / `kb-utils.js`
- ⚠️ **需确认激活**：`.claude/settings.json` 中没有 `hooks` 字段（CodeBuddy 的 `settings.json` 里有完整 hooks 配置）。**若要在 Claude Code 复用 buglog/kb-inject 的 hook 触发，需把 hooks 配置段迁到 Claude Code 的 `settings.json`**（SessionStart/UserPromptSubmit/PostToolUse/PostToolUseFailure 四个事件，Claude Code 的 hook 事件名与 CodeBuddy 一致）。
- 若不用 hook 自动触发，退化为"手动调 `/buglog add`"，可接受但会丢"事件驱动"的自动化。

### 5. 项目级环境（Loop 开发全程依赖）

| 项 | 说明 | 备注 |
|---|---|---|
| Python venv | `backend/.venv`（勿在根目录建） | 已存在 |
| uv 装包 | `UV_INDEX_URL` 指向清华镜像曾 403 | 装包加 `--index-url https://pypi.org/simple` |
| 后端 | 端口 8003，`uvicorn app:app` | 启动流程将按文档 01 整改 |
| 前端 | 静态服务 8001 | api.js 硬编码 localhost:8003，整改中改可推导 |
| 测试模型 | 项目已配模型（litellm 提供 token） | 浏览器点击/调 API 即可，不需额外配 key |
| 测试文档 | 本机现有 / 网络下载 | 如 `others/Claude Code 源码解读.pdf` |
| Obsidian 知识库 | `D:/ASUS/Documents/obsidian/new/` | save-knowledge/recall 目标 |

---

## 第二部分：Loop Engineering 提示词与规则设计

> 目标：把 master-plan 的 Stage 纪律翻译成可执行的开发循环（改 → 验证 → 汇报真实数据 → 判断收敛）。
> ⚠️ 2026-08-20 环境实测后修正：Claude Code **没有 `/goal` 命令**；内置 `/loop` 是定时器（适合轮询外部状态），**不适合当开发主循环**——开发循环靠提示词里的纪律本身驱动。实际启动方式见下方「kickoff 提示词」。

### 0. 实际启动方式（修正后）

- 新会话使用一份 kickoff 提示词启动整个项目（存于 `docs/plans/2026-08-20-kickoff-prompt.md`，复制即用）；
- 目标、验收、退出条件直接写在提示词里，不依赖不存在的 `/goal`；
- 单 Stage 会话只需把提示词第一行改为「执行 Stage N」。

### 1. 项目级目标（已写入 kickoff 提示词，全文见 `docs/plans/2026-08-20-kickoff-prompt.md`）

- 退出条件（全部满足才算完成）：
  - Stage 0-5 全部验收通过，每个 Stage 有对应的量化报告（存 docs/plans/）；
  - 每个性能项都有「整改前基线 vs 整改后」的实测对比数据；
  - 四个「真实」逐项核对：真实提高性能（最关键）/ 真实优化架构 / 真实可拓展 / 真实合理；
  - main 分支未被污染，各 Stage 用独立 feature 分支。
- 硬约束：
  - 任何性能指标未达标 → 立即停止该 Stage，携带实测数据向我（用户）报告，不硬凑数字、不擅自降级目标；
  - 遇到无法自行判断的岔路（如方案取舍、指标不合理的疑点）→ 暂停询问，不绕过；
  - 审计埋点（文档 07）随每个 Stage 编码同步落地，不等最后补。

### 2. 每个 Stage 的启动提示词模板（可复用）

```text
执行 Stage N：<名称>（依据 docs/plans/ 对应设计文档，工作分支 feature/stage-N-xxx）

目标：<一句话可判定结果>

验收（逐条可验证，见对应文档「验证方式」章节）：
1. <验证项 1 及其预期数值/行为>
2. <验证项 2>
...

退出条件：上述验收项全部通过，且产出 docs/plans/stage-N-report.md（含基线 vs 整改后对比数据）。

失败处理：任一验收项失败 → 暂停，按汇报格式带数据向我报告。

产物落盘：子 agent 的 diff/验证日志/报告统一写 work/stage-N/，通过文件交接，不口头传递。
```

### 2b. 暂停/退出时的汇报格式（统一收敛判断）

每次向用户暂停汇报时，按此格式（避免收敛标准漂移）：

```text
【Stage N · 第 M 圈】状态：<达标 | 未达标-继续 | 未达标-请求裁决>
- 本圈改动：<分支名 + 改动文件列表（一行内）>
- 验证命令与结果：<命令> → <关键数字>（预期 <目标值>）
- 结论对比上一圈：<变好 / 变差 / 不变，原因>
- 下一圈动作：<具体做什么> 或 <需要你裁决的问题>
```

### 3. Loop 循环纪律（写进 CLAUDE.md 或项目规则）

```
每个 Stage 内部按 loop 执行，单圈 = 改 → 验证 → 汇报真实数据 → 决定下一圈：
1. 只改最小范围，一次聚焦一个子目标；
2. 改完立即按「验证方式」跑真实验证（不是"看起来对了"）；
3. 把验证结果（数字/截图/日志）如实记录，不美化；
4. 未达标 → 分析原因（是目标不合理还是实现问题）→ 调整后进下一圈，或暂停询问我；
5. 达标 → 收敛，产出报告，进入下一 Stage。

预算/防跑飞：单圈超过 30 次工具调用仍未收敛 → 强制暂停，汇报当前状态。
```

### 4. 关键 Skill 在 Loop 各阶段的使用映射

| Loop 阶段 | 用哪个 skill | 作用 |
|---|---|---|
| 开工前定目标 | `superpowers:brainstorming` / `writing-plans` | 把需求转成可判定目标与验收基线 |
| 开发中 | `subagent-driven-development` / `test-driven-development` | 拆任务、隔离上下文（避免主循环上下文污染） |
| 出问题时 | `systematic-debugging` | 根因分析，而非打补丁 |
| 收敛前 | `verification-before-completion` | 强制跑真实验证，产出证据再宣称完成 |
| 收尾 | `finishing-a-development-branch` | 分支合并/清理 |
| 全过程 | `save-knowledge` / `buglog` | 沉淀决策、记录 bug |

### 5. 上下文污染隔离（你特别要求的）

- **主循环（主 agent）只做编排**：读计划 → 派子 agent → 汇总验证结果 → 判断是否收敛。
- **子 agent 做具体实现/探索**：每个 Stage 或每个子目标用独立子 agent（`Task` / subagent），其大量读文件、搜索、试错的 token 不进入主循环上下文。
- 子 agent 之间通过**文件产物**（报告、代码 diff、验证日志）交接，而非长对话。
- **产物落盘位置约定**：Stage N 的所有中间产物统一写 `work/stage-N/`（如 `work/stage-N/baseline.md`、`diff.patch`、`verify.log`、`report.md`）；最终验收报告复制到 `docs/plans/stage-N-report.md`。子 agent 返回主循环的文本只允许"结论 + 产物文件路径"。
- 主循环只保留：目标、当前状态、最近一次验证结论、下一圈动作。
- **环境实测事实（2026-08-20，勿重复排查）**：agent-memory MCP 已就绪（projectId: `rag-for-qw`，跨圈决策记忆写入此处）；codegraph 已建索引（1248 节点），但调用时必须显式传 `projectPath: "D:/workspace/rag-for-qw"`；hooks（kb-inject/buglog 四事件）已生效；后端 `backend/.venv`（Python 3.13）可用、PG rag_system 可连。

---

## 第三部分：待办清单（迁移/安装动作）

### 需要你确认后执行的（我会帮你检查，但改配置文件需你同意）

1. **补 MCP**（在 `.claude.json` 的 `mcpServers` 增加）：
   - `github`（多分支开发）
   - `agent-memory-mcp`（Loop 跨圈记忆）
   - `chrome`（UI 阶段）
2. **迁移 hooks 配置**到 Claude Code `settings.json`（把 CodeBuddy `settings.json` 的 hooks 段搬过去），让 buglog/kb-inject 自动触发在 Claude Code 也生效。
3. **项目级 CLAUDE.md**（`d:\workspace\rag-for-qw\CLAUDE.md`）：写入 Loop 循环纪律 + 验收原则 + 分支策略 + 测试资源约定（见第二部分第 3 条 + master-plan §6/§7）。

### 不需要额外动作（已就绪）

- Claude Code CLI、superpowers/frontend-design/skill-creator 插件、codegraph MCP、三个知识管理 skill、hooks js 文件、Python 环境、测试模型/文档。

---

## 第四部分：给你的几个提醒（重要）

1. **模型是 glm 系（代理），不是原生 Claude**：Loop Engineering 依赖模型"自我评估是否达标"，glm 的自我收敛能力可能弱于 Claude Opus/Sonnet。建议：退出条件写得非常具体（数值化），把"达标判断"尽量交给**可执行脚本/命令的返回值**（如 pytest、耗时命令、体积查询），而非让模型"觉得达标了"。这正好契合你"性能指标未达标就暂停"的原则——**用客观数字当裁判，不用模型主观判断**。
2. **提示词里的退出条件是循环收敛的核心**（2026-08-20 修正：Claude Code 无 `/goal` 命令，收敛机制由 kickoff 提示词承担，见 `2026-08-20-kickoff-prompt.md`）。务必把"性能实测数据达标"写成可机器判定的条件（例如"启动耗时 < 2s 且产出对比报告"），而不是"感觉变快了"。内置 `/loop` 是定时器，仅适合轮询外部状态，不要用作开发主循环。
3. **UI/UX 阶段（文档 05b）记得切模型**：你之前提过届时切 kimi k3（或你指定的前端强模型），Loop 跑到 Stage 5 时我会提醒你。

---

## 第五部分：2026-08-20 环境实测与整改记录（本文档修正日志）

- hooks 四事件已迁入 `~/.claude/settings.json` 并实测生效（本会话已见知识库地图注入）；
- agent-memory MCP 已配置并读写测试通过（server：`D:/workspace/agent-memory-mcp`，projectId：`rag-for-qw`）；
- **codegraph 此前从未建过索引**（原文档"已就绪"判断有误），已补 `codegraph init`（1248 节点/2584 边）并实测可用，调用需传 projectPath；
- github MCP / gh CLI、chrome / playwright MCP 仍未装（按需后补，Stage 5 前补 chrome）；
- 本文档第二部分已按 5 条整改意见修正：去 `/goal` 化、补环境事实、补产物落盘约定（work/stage-N/）、补统一汇报格式、澄清 `/loop` 定位；kickoff 提示词落盘为 `2026-08-20-kickoff-prompt.md`。
