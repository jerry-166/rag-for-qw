# rag-for-qw 整改 Kickoff 提示词（新会话复制即用）

> 生成：2026-08-20。依据 `2026-08-20-loop-engineering-migration.md`（已按环境实测修正：无 `/goal` 命令；`/loop` 是定时器不用于开发主循环，循环纪律由本提示词自身驱动）。
> 单 Stage 使用：把第一行改为「执行 Stage N：…」并附上该 Stage 的验收清单即可。

---

（以下为提示词正文，复制到新会话）

```text
读取 docs/plans/2026-08-19-00-master-plan.md 和 docs/plans/2026-08-20-loop-engineering-migration.md，
从 Stage 0 开始执行 rag-for-qw 六大整改。

## 项目目标（全部满足才算完成）
- Stage 0-5 逐个验收通过，每个 Stage 产出量化报告 docs/plans/stage-N-report.md；
- 每个性能项有「整改前基线 vs 整改后」实测对比，数字来自真实命令，不接受估算；
- 四个「真实」逐项核对：真实提高性能（最关键）/ 真实优化架构 / 真实可拓展 / 真实合理；
- main 分支不被污染，每个 Stage 用独立 feature 分支（feature/stage-N-xxx），验收后再合并。

## 单圈纪律（每个 Stage 内循环执行）
1. 先建 feature 分支，只改最小范围，一次聚焦一个子目标；
2. 改完立即跑该 Stage 设计文档「验证方式」章节的真实命令（pytest/计时/体积查询），
   不接受"看起来对了"；
3. 验证数字原样写入 work/stage-N/verify.log，不美化；
4. 未达标 → 分析原因（目标不合理 or 实现问题）→ 调整后进下一圈；
   同一项连续 2 次未达标或怀疑目标不合理 → 暂停向我报告；
5. 单圈超过 30 次工具调用未收敛 → 强制暂停汇报。

## 自主运行原则（重要）
- 本次整改以自主执行为主：你收到本提示词即开始运行，直到全部 Stage 完成或遇到必须裁决的问题；
- 不要在每个 Stage、每圈之间等我确认——验收项全部客观达标即自动进入下一 Stage；
- 只在以下情况找我：① 性能指标连续 2 圈未达标；② 遇到方案取舍/指标合理性等无法自行判断的岔路；
  ③ 需要破坏性操作；④ 全部 Stage 完成；
- 其余进度通过 docs/plans/stage-N-report.md 自动留痕即可，我不需要逐步看汇报。

## 暂停/汇报格式（仅在需要找我时使用）
【Stage N · 第 M 圈】状态：<达标 | 未达标-继续 | 未达标-请求裁决>
- 本圈改动：<分支名 + 改动文件列表>
- 验证命令与结果：<命令> → <关键数字>（预期 <目标值>）
- 对比上一圈：<变好/变差/不变，原因>
- 下一圈动作：<具体做什么> 或 <需要我裁决的问题>

## 工作方式
- 你（主循环）只做编排：读计划 → 派子 agent（Agent 工具）→ 汇总其验证产物 → 判断收敛；
- 具体实现/探索全部交给子 agent；产物统一落盘 work/stage-N/
  （baseline.md / diff.patch / verify.log / report.md），子 agent 返回主循环只给"结论 + 产物路径"；
- 检索代码用 codegraph MCP，必须传 projectPath: "D:/workspace/rag-for-qw"；
- 跨圈决策记忆读写 agent-memory MCP（projectId: rag-for-qw）；
- UI/UX 相关工作（Stage 5）：
  - Open Design 里目前**没有** rag-for-qw 相关项目（只有 2 个历史测试项目），需要时用
    open-design MCP 的 create_project + start_run 新建项目生成 UI 设计稿，以设计稿为前端实现参照；
  - Open Design 内置 157 个设计 skill，推荐组合：start_run 时传 skill=frontend-design（生成有设计感的生产级 UI），
    辅以 platform-design（Apple HIG/Material 3/WCAG 规则）、design-review 或 plan-design-review（设计审查打分）；
  - 本地也有 Claude Code 插件 frontend-design 可直接用于前端编码阶段；
  - 注意：Stage 5 才需要 UI 工作，届时先确认 chrome MCP（浏览器 DOM 实测）已补装。
- 审计埋点随每个 Stage 编码同步落地，不等最后补。

## 环境事实（2026-08-20 已实测，勿重复排查）
- 后端 venv：backend/.venv（Python 3.13），端口 8003，uvicorn app:app；
  PG rag_system 可连；import app 已验证通过；
- 前端静态服务 8000（api.js 硬编码 localhost:8003）；
- uv 装包镜像 403 时加 --index-url https://pypi.org/simple；
- 测试文档可用 others/Claude Code 源码解读.pdf；
- 未装：gh CLI、chrome/playwright MCP（Stage 5 UI 阶段前需补 chrome）。

现在开始：自主执行，不需要等我确认。遇上述「自主运行原则」列出的情况再找我。
```
