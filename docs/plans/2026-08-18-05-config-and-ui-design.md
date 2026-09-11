# 设计文档 05：配置保存（分组 + 增量提交）与 UI 体验整改

> 状态：待审阅 | 日期：2026-08-18（2026-08-19 修订排期定位）
> 范围：A 配置保存交互；B 浏览器实测驱动的 UI 体验与解析正确性
> 排期定位（用户评审确认）：**分两批执行**——05a 功能性修复随各后端整改批次同步小步落地；**05b UI/UX 整体优化（主题修改、比例调整、页面重构、美化）后置到所有整改完成的最后整合阶段**统一执行，并适配整改后的新功能体验（KB 级切割/增强选择、补生成按钮、FAQ 管理、审计中心等新 UI 元素）。详见第 7 节阶段划分。

## 1. 现状诊断

### A. 配置保存

后端已达标，无需改：`PUT /api/settings`（api/settings.py:56-143）逐项校验 + `set_runtime` + `persist_to_env`（runtime_config.py:520-540，单 key 原位替换、保留注释、白名单校验、失败回滚）。

**问题全在前端**（settings.js）：

- 全页仅 **1 个保存按钮**（settings.js:87-96），8 个配置组共享。
- 点击后收集**所有非敏感输入项**整体提交（settings.js:230-245），不是只提交改动项——放大部分失败面（后端 partial_error 时用户难以定位是哪个组失败）。
- 已有 dirty 跟踪（settings.js:212-216）但只用于禁用按钮，未用于过滤提交内容。

### B. UI 已知问题（代码探索发现）

| # | 问题 | 位置 | 类型 |
|---|---|---|---|
| 1 | **拼写错误**：`loadKnowledgeBables()` → 知识库加载失败时「重试」按钮必抛 ReferenceError | search.js:284 | 功能性 bug |
| 2 | 转义写错 `.replace(/'/g, "\'")`（结果与原串相同），历史查询含引号时 onclick 断 | search.js:623 | 功能性 bug |
| 3 | 同一 div 两个 style 属性（后者无效），`search-stats-card` 隐藏失效 | search.js:147 | 显示 bug |
| 4 | 删除用文件名做 key（同名误删）且文件名未转义拼进 onclick | documents.js:141 | 功能性 bug |
| 5 | 上传无进度条，大文件期间无反馈；文档列表不自动轮询状态 | documents.js:126-171, 236-246 | 体验 |
| 6 | 大量调试 console.log 残留 | documents.js:180-185、app.js:130/233、agent.js 多处、pipeline.js 等 | 代码质量 |
| 7 | `js/auth.js` 与 app.js:344-469 `initAuthEvents` 功能重复且从未被调用 | auth.js 全文 | 死代码 |
| 8 | `API_BASE='http://localhost:8003'` 硬编码 | api.js:4 | 部署隐患 |
| 9 | 假进度条（写死 width:100%）、timeline `embed:'N/A'` 恒占位 | pipeline.js:542-543, 1128 | 展示正确性 |
| 10 | 流式回答每个 token 全量 `innerHTML = marked.parse(fullContent)` 重渲染 | agent.js:1059 | 性能（长回答卡顿） |

## 2. 目标

- A：配置页改为**分组保存 + 只提交改动项**。
- B：以**浏览器实际登录体验**为准绳，修复功能性 bug → 修复展示正确性 → 美化打磨，三层递进。

## 3. 设计

### 3.1 A 部分：配置保存交互

**分组保存**：8 个配置组（检索/文档切分/LLM参数/会话与记忆/文档处理/模型与LLM/系统/API Keys）每组头部加「保存本组」按钮；底部保留「全部保存」。

**dirty-only 提交**：

```javascript
// settings.js 保存逻辑改造
function collectDirtyConfigs(groupKey = null) {
  // 只收集 dirtyFields 中的 key（现有 dirty 跟踪已有集合）
  // groupKey 非空时再按组过滤
  // 敏感项规则不变：留空=不提交；标记清除=提交 null
}
```

- 每组按钮按「本组 dirty 数」显示徽标（如 `保存本组 (3)`），无改动时禁用。
- 全部保存 = 各组 dirty 的并集，一次请求（保持批量接口不变，后端无需改）。
- partial_error 时按 key → 组映射，在对应组内联标红显示错误原因（比现状 toast 更可定位）。

### 3.2 B 部分：浏览器实测流程（先行）

整改以**真实体验**驱动，顺序：

1. 启动前后端，用浏览器自动化（agent-browser / playwright-cli）走一遍完整用户旅程并截图存档：
   登录/注册 → 建库 → 上传文档 → 四步 pipeline → 检索（三种模式 + rerank 开关）→ Agent 对话（流式 + 来源面板 + 反馈）→ 设置保存。
2. 每一步记录：视觉问题（截图）、交互问题（无反馈/卡顿）、控制台报错、网络请求异常。
3. 问题清单合并上表 1-10，按「功能 bug > 展示正确性 > 体验 > 美化」排序修复。

### 3.3 B 部分：修复方案要点

| 问题 | 方案 |
|---|---|
| 1-4 功能 bug | 直接修复；2 的正确转义改为 DOM 事件绑定替代内联 onclick（顺带解决 4 的注入隐患），或统一用 `data-*` + addEventListener |
| 5 上传进度 | `XMLHttpRequest` + `upload.onprogress`（fetch 不支持上传进度）替换上传请求；文档列表处理中状态 5s 轮询，完成/失败即停 |
| 6 调试残留 | 全量清除 console.log（保留 console.error 真实错误） |
| 7 死代码 | 删除 `auth.js` 及其 script 标签引用 |
| 8 API_BASE | 改为相对路径/同源推导：`const API_BASE = window.location.origin.replace(/:\d+$/, ':8003')` 或构建期注入；至少支持 `window.API_BASE` 覆盖 |
| 9 假进度条 | Step 2/4 接入真实进度（后端若无法给进度则改为 spinner + 阶段文字，删除误导性 100% 条）；timeline embed 字段随文档 04 落地 |
| 10 流式渲染 | 节流重渲染（每 100ms 或每 N token 一次 marked.parse），结束后终渲；避免每 token 全量 innerHTML |
| 展示解析正确性 | 统一 marked 渲染入口（agent.js / pipeline.js 两处 `_renderMarkdown` 收敛为一个工具函数）；数学公式/代码高亮如需再议（本期评估 marked 配置即可）；确认 `_escapeHtml` 与 marked 的先后关系无双重转义 |

**美化方向**（**移至最后整合阶段执行**，即 05b，以截图对比验收）：

- 以现有暗色主题体系（main.css 83.6KB 已有 light-mode）为基础，但本阶段允许**主题修改、布局比例调整、页面级重构**——此时所有后端整改（01-04、06、07）已定型，UI 重构一次到位，避免中途重构后又为适配新功能返工。
- 整合阶段的 UI 工作清单：
  1. 适配新功能 UI：KB 级切割策略/增强器选择、补生成提示条与按钮、FAQ 管理页（候选/正式/PR 队列、KB 过滤、手动升格/删除）、KB 分享与克隆入口（分享管理、「克隆此 KB」「提交共享」按钮）、审计中心页面、检索漏斗可视化（FAQ→实体→向量分层命中展示）；
  2. 全局主题与比例：色彩体系统一、间距/圆角/字号比例规范化、响应式断点复查；
  3. 页面重构候选：pipeline 四步流程的信息架构、Agent 页来源面板与补全引导的融合、设置页分组导航；
  4. 三态统一：空状态/加载态/错误态全局规范。
- 每次修改后浏览器复验截图，与用户确认再继续。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `frontend/js/pages/settings.js` | 分组保存按钮 + dirty-only 收集 + 组内错误标红 |
| `frontend/js/pages/search.js` | bug 1/2/3 修复，内联 onclick 清理 |
| `frontend/js/pages/documents.js` | bug 4/5 修复 + 轮询 + console 清理 |
| `frontend/js/pages/agent.js` | 流式渲染节流 + console 清理 |
| `frontend/js/pages/pipeline.js` | 假进度条/timeline 修复 + 渲染统一 |
| `frontend/js/api.js` | API_BASE 推导 + 上传 XHR 进度支持 |
| `frontend/js/auth.js` | 删除（+ index.html 移除引用） |
| `frontend/js/utils.js`（新） | 统一 `_renderMarkdown` / `_escapeHtml` |
| `frontend/index.html` | 脚本引用调整 |

## 5. 前后对比

| 维度 | 当前 | 整改后 |
|---|---|---|
| 配置提交 | 全量收集一次提交 | 分组保存 + 仅 dirty 项 |
| 保存失败定位 | toast 提示数量 | 组内联标红到具体 key |
| 上传 | 无进度、串行无反馈 | 真实进度条 + 状态轮询 |
| 功能 bug | 4 处确定 bug | 清零且消除同类隐患（事件绑定化） |
| 流式渲染 | 每 token 全量重渲 | 节流渲染 |
| 死代码/调试残留 | auth.js 重复 + 20+ console.log | 清除 |

## 6. 验证方式

1. **配置**：改 A 组 2 项 → 只提交这 2 项（Network 面板确认 payload）；故意填非法值 → 该组标红，其他组不受影响。
2. **浏览器旅程复跑**：3.2 的完整旅程重走一遍，前后截图对比，控制台零报错。
3. **流式性能**：长回答（2000+ 字）流式过程帧率无明显卡顿（Performance 面板或体感 + 截图）。
4. **回归**：登录、上传、处理、检索、对话、设置六条主路径全绿。

## 7. 阶段划分（2026-08-19 用户评审确认：UI/UX 优化后置到最后）

### 05a：功能性修复（随各整改批次同步，小步快跑）

- 范围：问题 1-4（功能 bug）、6（console 清理）、7（死代码）、8（API_BASE）、10（流式渲染节流）+ A 部分配置分组保存——这些与后端整改无冲突，越早修越避免新整改叠在旧 bug 上。
- 时机：穿插在总体规划（文档 00）Stage 1-2 期间，作为独立小批次提交。

### 05b：UI/UX 整体优化（最后整合阶段，独立 Stage）

- 入口条件：文档 01-04、06、07 全部落地并验收通过。
- 范围：3.3 美化方向全部内容 + 新功能 UI 适配 + 主题/比例/页面重构 + 问题 9（假进度条重构；其中 timeline embed 字段依赖文档 04）+ 问题 5（上传进度/轮询，若前序批次未做）。
- 执行方式：先重跑 3.2 浏览器实测旅程刷新问题清单（旧 bug + 新功能体验问题合并），再按「信息架构 → 主题比例 → 细节打磨」三层推进，每层截图对比、用户确认。

## 8. 风险与备注

- **美化是主观项**：先修 bug（客观），美化部分每步截图与用户确认，避免返工。
- **XHR 上传改造**注意保持现有鉴权头（Bearer token）与错误处理一致。
- 内联 onclick → addEventListener 的改造范围控制在 search/documents 两页，不全局重构（05b 页面重构时再统一）。
- 05b 期间冻结功能开发，只做 UI——避免边改 UI 边改功能导致反复适配。
