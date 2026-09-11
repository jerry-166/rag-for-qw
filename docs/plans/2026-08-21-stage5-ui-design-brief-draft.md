# Stage 5 (05b) UI 重构设计 Brief 草稿（CodeBuddy 侧）

> 状态：草稿（供与 Claude 产出的 brief 对照合并后交付 kimi k3）
> 日期：2026-08-21
> 用途：作为 CodeBuddy 切 kimi k3 出稿的输入上下文。Claude 在节点 1 也会产出一份 brief，最终以两份合并后的为准。
> 关联文档：`docs/plans/2026-08-18-05-config-and-ui-design.md`（§3.3 美化方向 + §7 阶段划分）、`2026-08-19-00-master-plan.md`

---

## 0. 给 kimi k3 的开场约束（强约束，不可违背）

1. **输出形式分两阶段**：
   - 阶段 A：先产出**设计稿预览**（独立 HTML 静态页 + design tokens 文件 + 每页信息架构图/线框），**不要直接改 frontend/main.css 与 js**。
   - 阶段 B：用户审稿通过后，再按稿落地到 `frontend/css/main.css` 与各 `frontend/js/pages/*.js`。
2. **保持暗色主题体系为默认**，light-mode 仍是切换态。不要推翻现有色彩家族，可微调与扩展。
3. **不改任何后端 API 契约**：所有数据字段、字段名、接口路径必须保持现状。
4. **框架约束**：纯原生 HTML/CSS/JS（无 React/Vue/构建工具）。marked.min.js、pdfjs-dist 已通过 CDN 引入。
5. **三态必须全覆盖**：每个列表/卡片/异步区域都要有空状态 / 加载态 / 错误态三种规范样式。
6. **响应式断点**：现有 900px / 600px 两个断点，复查并规范统一。
7. **可访问性**：颜色对比度达 WCAG AA，焦点态可见，按钮可键盘操作。

---

## 1. 项目现状（必读）

### 1.1 架构

- 单页应用，`index.html` 通过 `<template>` 定义两套骨架：`tpl-auth`（登录注册）和 `tpl-app`（主框架，含侧边栏+顶栏+page-container）。
- 路由由 `js/app.js` 的 `App` 类管理，通过侧边栏 nav-item 的 `data-page` 切换。
- 7 个业务页面（对应 7 个 js 文件）：
  1. `knowledge-bases` 知识库（管理 + KB 级切割策略/增强器选择）
  2. `documents` 文档管理（列表 + 上传 + 状态轮询）
  3. `search` 知识检索（三种检索模式 + rerank + 来源面板）
  4. `agent` AI Agent（流式回答 + 来源面板 + 反馈 + FAQ 补全卡片）
  5. `faq` 知识记忆（正式/候选/PR 三 Tab + KB 过滤 + 分页）
  6. `settings` 设置（8 组配置 + 主题切换）
  7. `audit` 审计中心（事件流/类型筛选/详情）
- pipeline 四步流程以模态/页面形式存在于 `pipeline.js`（1333 行，最重的一个）。

### 1.2 现有设计 Tokens（main.css :root）

色彩：
- bg `#0f1117` / surface `#1a1d27` / surface2 `#22263a` / surface3 `#2c3050`
- border `#2e3347` / border-light `#3d4260`
- accent `#6366f1`（主色，Indigo）/ accent2 `#818cf8`
- 状态色：green `#22c55e` / yellow `#f59e0b` / pink `#ec4899` / cyan `#06b6d4` / red `#ef4444`（均配套 `*-bg` 半透明底）
- 文本：text `#e2e8f0` / text2 `#94a3b8` / text3 `#64748b`

light-mode（body.light-mode）整套对应浅色版本，色相一致明度反转。

几何：
- radius `12px` / radius-sm `8px` / radius-xs `6px`
- shadow `0 4px 24px rgba(0,0,0,0.4)` / shadow-sm `0 2px 8px rgba(0,0,0,0.3)`
- sidebar-width `220px` / sidebar-collapsed `60px` / topbar-height `56px`
- transition `0.2s ease`

字体：`'Inter', 'PingFang SC', 'Microsoft YaHei', -apple-system, sans-serif`，根字号 14px，行高 1.6。

响应式断点：900px（侧边栏转抽屉式）、600px（栅格转单列）。

### 1.3 按钮/输入系统

按钮：`.btn` 基类 + primary/secondary/danger/ghost/success 五种语义 + sm/lg/full 尺寸 + `.btn-icon` 圆角图标按钮。
输入：input/textarea/select 共享暗色 surface2 底 + border + focus 态 accent 描边 + glow。
`.form-field` 是 label+input 的标准组合。

---

## 2. 问题清单（来自文档 05 §1.B，10 项已分类）

| # | 问题 | 归属（设计/逻辑） | 设计侧关注点 |
|---|---|---|---|
| 1 | `loadKnowledgeBables()` 拼写错误 | 逻辑（Claude 修） | — |
| 2 | `.replace(/'/g, "\'")` 转义错 | 逻辑（Claude 修，改事件绑定） | — |
| 3 | 同一 div 两个 style 属性 | 逻辑（Claude 修） | — |
| 4 | 删除按文件名做 key | 逻辑（Claude 修） | — |
| 5 | 上传无进度条 + 无状态轮询 | 逻辑+设计 | **进度条样式、轮询指示、空/加载/错误态** |
| 6 | 调试 console.log 残留 | 逻辑（Claude 清） | — |
| 7 | auth.js 死代码 | 逻辑（Claude 删） | — |
| 8 | API_BASE 硬编码 | 逻辑（Claude 改） | — |
| 9 | 假进度条（写死 100%）+ timeline `embed:'N/A'` 恒占位 | 逻辑+设计 | **真进度条样式、阶段文字、空态** |
| 10 | 流式每 token 全量 innerHTML 重渲 | 逻辑（Claude 修） | — |

**设计侧重点**：5、9 的视觉呈现（进度条/timeline/阶段卡），三态规范（覆盖所有列表/卡片）。

---

## 3. 05b 整合阶段 UI 工作清单（文档 05 §3.3）

### 3.1 新功能 UI 适配（必做，每个都要有规范样式）

1. **KB 级切割策略选择**：knowledge-bases 页弹窗内的策略下拉/卡片（auto/markdown/recursive）
2. **KB 级增强器选择**：csv checkbox 组（sub_question/summary/entity）
3. **补生成提示条 + 按钮**：pipeline Step 3 黄色提示条 + 文件级 `GET /api/process/generate/{file_id}/missing` 触发按钮
4. **FAQ 管理页**：正式/候选/PR 三 Tab + KB 过滤下拉 + 分页 + 手动升格/删除/合并/reject 按钮
5. **KB 分享与克隆入口**：分享管理弹窗 + 「克隆此 KB」「提交共享」按钮
6. **审计中心**：事件流时间轴 + 类型筛选 + 详情抽屉/模态
7. **检索漏斗可视化**：FAQ 命中 → 实体命中 → 向量分层命中展示（search 结果页侧面板）

### 3.2 全局主题与比例

- 色彩体系统一：检查现有 5 个状态色是否够用、是否需要扩展（如审计按级别 INFO/WARN/ERROR 配色）
- 间距/圆角/字号梯度规范化：定义 `--space-1/2/3/4/6/8/12/16/24`、`--fs-xs/sm/base/lg/xl/2xl` 等 token 体系
- 响应式断点复查：900/600 是否够，是否需要 1200/768

### 3.3 页面重构候选（评估，不一定全改）

1. **pipeline 四步流程信息架构**：当前 pipeline.js 1333 行，可能信息密度过高，考虑分步引导式 or 仪表盘式
2. **Agent 页来源面板与补全引导的融合**：来源面板当前如何呈现、FAQ 补全卡片如何不打断对话
3. **设置页分组导航**：8 组配置是否需要左侧分组导航 + 右侧内容区

### 3.4 三态统一

空状态 / 加载态 / 错误态 全局规范组件（`.empty-state` / `.loading-state` / `.error-state`），所有列表/卡片/异步区域统一引用。

---

## 4. 验收标准（硬指标，非"好看"）

1. **Design tokens**：产出一套完整的 token 文件（CSS variables），含色彩/间距/圆角/字号/阴影/动效时长，dark+light 双套。
2. **三态组件**：`.empty-state` / `.loading-state` / `.error-state` 三个通用组件，每个业务页至少引用一次。
3. **信息架构图**：7 个业务页每个一张线框图（可 HTML+CSS 静态实现，标注区块功能）。
4. **响应式**：900/600 断点下布局不破，关键页面（search/agent/knowledge-bases）在 375px 仍可用。
5. **可访问性**：暗色与浅色模式下文字对比度均达 WCAG AA（4.5:1 正文，3:1 大字）。
6. **不破坏现有 API 契约**：所有 fetch 调用的字段名、路径不变。
7. **新功能 UI 全覆盖**：§3.1 七项每一项在稿中都有可视呈现。
8. **代码质量**：无内联 onclick（改 addEventListener 或 data-* 委托），无 console.log，无死代码。

---

## 5. 产出物清单（阶段 A 必须产出）

1. `frontend/design/tokens.css` — 完整 design tokens（dark+light）
2. `frontend/design/preview.html` — 设计稿预览总览页（含所有组件三态、色板、字号梯度、7 页线框）
3. `frontend/design/page-wireframes/` — 每页一张线框 HTML（7 张）
4. `frontend/design/DESIGN.md` — 设计说明（每个决策的理由、对应文档 05 章节、验收对照）

**阶段 B（审稿通过后）**：按稿改 `frontend/css/main.css` + 各 `frontend/js/pages/*.js`，期间冻结后端 API 改动。

---

## 6. 不在本次范围（明确排除）

- 后端 API 改动（进度接口由 Claude 在节点 1 补，kimi k3 只消费字段）
- 文档 05 §1.B 问题 1/2/3/4/6/7/8/10 的逻辑修复（Claude 在节点 1 修完）
- 性能优化（流式渲染节流等）
- 国际化、多语言

---

## 7. 交接方式

1. 本草稿与 Claude 节点 1 产出的 brief 对照合并 → 最终 brief
2. 用户在 CodeBuddy 切 kimi k3 模型
3. 把最终 brief + `frontend/` 目录现状喂给 kimi k3
4. kimi k3 按阶段 A 产出 → 用户审稿 → 通过 → 阶段 B 落地
5. 完成后通知 Claude 跑双门验收（Playwright 截图对比 + 五项功能回归）
