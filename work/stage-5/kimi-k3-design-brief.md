# Stage 5（05b）前端重构设计 Brief —— 致 kimi k3

> 日期：2026-08-21 | 依据：docs/plans/2026-08-18-05-config-and-ui-design.md（§1B/§3.3/§6）+ 本文件附带的浏览器基线实测刷新
> 产物位置：本文件 + work/stage-5/baseline/shots/（现状截图）+ work/stage-5/baseline/report.md（问题清单）

---

## 〇、设计主导声明（最高优先级）

**本次重构以你（kimi k3）的前端设计能力与业务逻辑理解为主。**

本 brief 提供的是：
- **上下文**（项目是什么、有哪些页面、流程如何运作、有什么约束）
- **硬约束**（不可破坏的接口契约、状态机、可访问性）
- **用户审美偏好**（方向性指引，非具体方案）

本 brief **不提供**的是：
- 具体设计手法（圆角多大、阴影怎么写、用什么配色组合）——这些由你自主决定
- 页面信息架构方案（怎么重构布局、用 wizard 还是仪表盘）——由你基于流程逻辑自主判断
- 视觉参数（间距梯度、字号梯度、动效曲线）——由你按设计系统最佳实践自主定义

**遇到本 brief 与你的专业判断冲突时，以你的专业判断为准，但需在 DESIGN.md 中说明理由。** 用户会审稿，不满意会反馈，但不会用 brief 条款束缚你。

---

## 〇.5、用户审美偏好（方向性指引）

- **首选风格**：Glassmorphism（毛玻璃）
- **次选风格**：macOS Big Sur 毛玻璃（更克制的透明度 + 强对比文字）、Notion 风（高留白 + 文档感 + 清晰层级）
- **期望程度**：希望"很大很好的改变"和"新的感官体验"，**不满足于现有布局基础上的视觉优化**
- **参考样本**：本机 `设计风格/glassmorphism-showcase/index.html`（用户提供的 glassmorphism 实现样本，建议先浏览提炼手法）
- **注意**：以上为方向指引，具体设计手法与重构方案由你自主决定。可融合三种风格的优点，也可在此基础上创新。

---

## 一、现状

### 技术栈
- 原生 HTML/CSS/JS，**无构建工具链**：入口 `frontend/index.html`，`<script>` 顺序加载 `js/api.js -> js/pages/*.js -> js/app.js`，页面对象全局挂 window。
- 样式集中在 `frontend/css/main.css`（约 84KB），**已有暗色主题为主 + light-mode 变量**（CSS custom properties）。
- 外部依赖仅 CDN：marked、pdfjs-dist。
- API 基地址：`window.API_BASE` 覆盖，否则 `location.origin.replace(/:\d+$/, ':8003')`（已修复硬编码）。
- 新增设计应继续走 CSS variables（design tokens 先行）。

### 页面清单（frontend/js/pages/）
| 页面 | 文件 | 说明 |
|---|---|---|
| 知识库 | knowledge-bases.js | KB CRUD + KB 级切割策略/增强器勾选（新功能已进表单） |
| 文档 | documents.js | 上传（pdf/markdown）、列表、删除、跳 pipeline |
| Pipeline | pipeline.js | 四步：切割→生成→导入→(完成/timeline)；含缺口提示条（missing-banner）与补生成 |
| 检索 | search.js | vector/keyword/hybrid 三模式 + 策略/topK 选择 + 历史 + 统计卡 |
| Agent | agent.js | 会话侧栏、SSE 流式、KB 选择条、多 Agent 对比、反馈 |
| FAQ | faq.js | FAQ 管理（候选/正式/PR 队列、KB 过滤） |
| 设置 | settings.js | 8 配置组、分组保存按钮已落地 |
| 审计 | audit.js | 审计事件查询页 |
| 全局壳 | app.js + index.html | 登录/注册双模板、侧栏导航、统计侧栏、主题切换 |

### 参考 API（不改契约）
`frontend/js/api.js` 是唯一 API 层；后端 FastAPI 8003，前缀 `/api`。

## 二、问题清单（文档 05 §1B 刷新版）

| # | 原状态 | 现状（基线实测 2026-08-21） |
|---|---|---|
| 1 | search.js:284 拼写错误 loadKnowledgeBables | 待回归确认（本次旅程未触发 KB 加载失败路径） |
| 2 | 内联 onclick 转义错误（search.js:623） | 仍在（代码未改） |
| 3 | search-stats-card 双 style 属性 | 仍在 |
| 4 | 删除按文件名做 key + onclick 注入 | 已改为 file_id 传参（documents.js:207-210 用 doc.file_id），注入面收窄但内联 onclick 仍在 |
| 5 | 上传无进度、无状态轮询 | **后端已就绪**：新 `GET /api/process/{file_id}/progress`（字段见 §四）；前端进度 UI 未接 |
| 6 | console.log 调试残留 | 部分仍在（agent.js/pipeline.js/documents.js） |
| 7 | auth.js 死代码 | 已删除 |
| 8 | API_BASE 硬编码 | 已修复（origin 推导 + window.API_BASE 覆盖） |
| 9 | 假进度条 width:100%、timeline embed 'N/A' | 仍在；现在可用真进度接口替换 |
| 10 | 每 token 全量 innerHTML 重渲 | 状态待确认（基线未测长回答帧率） |
| 新 | **KB 创建 422（已修）**：后端 `chunk_strategy: str = None` 在 Pydantic v2 拒绝显式 null，前端默认传 null 导致"跟随全局配置"必失败 → 已改 Optional（api/knowledge_bases.py），回归时验证 |
| 新 | 完整清单与截图证据见 work/stage-5/baseline/report.md |

## 三、整合清单（§3.3，本轮设计必须覆盖的新功能 UI）

1. **KB 级切割策略/增强器选择**（已有表单雏形，需要信息架构优化：默认"跟随全局"的语义展示）
2. **补生成提示条与按钮**（pipeline generate 步：missing-banner + 显性补生成，调用 `GET /api/process/{file_id}/missing` + `POST /api/process/{file_id}`）
3. **FAQ 管理页**（faq.js 已存在，需重设计：候选/正式/PR 队列三态、KB 过滤、手动升格/删除）
4. **KB 分享与克隆入口**（分享管理、"克隆此 KB"、"提交共享"按钮——后端已有对应 API）
5. **审计中心页面**（audit.js 已存在，重设计：事件流/筛选/资源维度聚合）
6. **检索漏斗可视化**（FAQ→实体→向量分层命中展示；检索响应已带分层来源数据）
7. 全局主题与比例：色彩体系统一（tokens）、间距/圆角/字号比例、响应式断点复查
8. 页面重构候选：pipeline 四步信息架构（用真进度接口做 timeline）、Agent 来源面板与补全引导融合、设置页分组导航
9. 三态统一：空/加载/错误态全局规范

## 四、进度接口契约（上传/处理进度 UI 的数据源）

`GET /api/process/{file_id}/progress`（需 Bearer token；404=文件不存在，403=无权限，401=未登录）

```json
{
  "file_id": "14",
  "document_status": "completed",       // uploaded|chunk_done|generated|importing|completed|failed
  "stage": "done",                       // awaiting_split|generating|awaiting_import|importing|done|failed
  "is_running": false,                   // chunk_done/importing 视为进行中
  "stage_progress": { "done": 12, "total": 12 },   // generate 阶段=已增强 chunk/需增强 chunk；其余阶段=chunk 总数口径
  "total_chunks": 12,
  "timing_ms": {
    "split_time": 311.0,                 // 各阶段历史耗时（ms，可空）
    "generate_time": 12914.2,
    "import_time": 25721.3
  },
  "updated_at": "2026-04-28T20:45:26",
  "last_error": null                     // 失败时 {operation, message, at}
}
```

设计要点：轮询间隔建议 2-5s；`timing_ms` 可用于"预计剩余时间"（按已完成比例外推）；`stage_progress` 驱动阶段内进度条；`last_error` 驱动失败态展示与重试入口。

## 五、关键流程上下文（设计参考，非约束）

> 以下是各页面的关键业务流程逻辑，供设计时参考。这些是**事实**，不是设计要求——你可以基于这些流程自主决定如何呈现。
> 理解这些流程有助于你做出更贴合业务的信息架构设计。

### 5.1 全局壳（app.js + index.html）

- 双模板：`tpl-auth`（登录/注册双 tab 切换）+ `tpl-app`（侧栏 + 顶栏 + page-container 动态内容区）
- 侧栏导航 7 项：知识库 / 文档管理 / 知识检索 / AI Agent / 知识记忆(FAQ) / 设置 / 审计中心
- 侧栏底部有"统计概览"折叠区（总文档/总 Chunk/总子问题/总摘要数，实时）
- 顶栏：移动端汉堡按钮 + 面包屑 + 主题切换按钮（🌙/☀️）+ 用户头像
- 主题切换机制：`body.light-mode` 类切换，CSS 变量整套切换暗/亮

### 5.2 知识库（knowledge-bases.js）

- KB 列表卡片，每个 KB 4 个操作图标：分享(🤝) / 克隆(📑) / 编辑(✏️) / 删除(🗑️)
- 创建/编辑弹窗含：
  - KB 级切割策略下拉：**跟随全局配置** / auto(自动探测) / markdown(Markdown标题切割) / recursive(递归字符切割)
  - KB 级增强器 checkbox 组：sub_question(子问题) / summary(摘要)；entity(实体) 在后端支持但前端未显式勾选
- 分享弹窗：输入用户名 + "允许直接写入"checkbox（不勾选则对方只能提交 PR，由 KB 主审核后生效）+ 已分享列表（含取消分享）
- 克隆操作：`prompt()` 输入名称 → 后端复制 PG 全量数据（文档/chunk/增强/FAQ 快照）+ 搬运 Milvus 向量
- 分享/克隆走 Stage 3 fork-PR 协作模型

### 5.3 文档管理（documents.js）

- 上传（支持 pdf / markdown）→ 文档列表 → 删除（已用 file_id 做 key）→ 跳转 pipeline
- 文档状态字段：uploaded / chunk_done / generated / importing / completed / failed

### 5.4 Pipeline（pipeline.js，1333 行，最复杂的页面）

- **四步固定流程**（steps 数组）：
  1. 上传 & 解析（upload & parse）
  2. 文档切割（chunk / split）
  3. 生成增强（generate：子问题 + 摘要 + 实体）
  4. 嵌入入库（import / embed）
- 每步有 status：pending / running / done / failed
- 每步有 timings（ms）：upload / split / generate / import
- 统计字段：chunksCount / subQuestionsCount / summariesCount / vectorCount / vectorDim
- **补生成提示条**（missing-banner）：Step 3 检测到缺口时显示，调用 `GET /api/process/{file_id}/missing` 查缺口 + `POST /api/process/{file_id}` 触发补生成
- **进度接口**（§四已详述）：驱动进度条、阶段内进度、预计剩余时间、失败态重试
- 当前问题：假进度条（写死 width:100%）、timeline embed 字段恒占 'N/A'，需用真进度接口替换

### 5.5 检索（search.js）

- **三种检索模式**（按钮组切换）：
  - vector（向量语义匹配）
  - keyword（BM25 关键词）
  - hybrid（RRF 融合 + Rerank 精排，全链路）
- **向量策略下拉**（vector/hybrid 模式下可选）：
  - advanced（摘要 + 子问题，Stage 2 默认）
  - native（原文匹配，无增强）
  - hybrid（三路融合）
- **Rerank 开关**：toggle，开启走 LLM 精排（显示"LLM Rerank"），关闭则"直接返回"
- **检索流水线可视化**（badge 串联，根据模式动态显示）：
  - 向量检索 → [关键词检索] → [RRF 融合] → LLM Rerank / 直接返回 → 结果
  - 只有 hybrid 模式显示全链路（含 keyword + fusion）；vector/keyword 模式只显示对应分支
- **结果卡片**：分数（RRF 分数 / rerank 分数双显示）、来源标签（向量/ES/reranked）、文档ID / Chunk#
- 搜索历史（localStorage 持久化）
- 统计卡：耗时 / 结果数 / Rerank 开关状态 / 当前模式
- 空态有"尝试向量/混合检索"切换建议
- **Stage 3 漏斗可视化**（待你设计）：FAQ 命中 → 实体命中 → 向量分层命中，检索响应已带分层来源数据可消费

### 5.6 Agent（agent.js，1273 行）

- 会话侧栏（多会话切换）+ KB 选择条 + 多 Agent 对比模式（平行卡片）
- **SSE 流式响应**：token 流 + typing 动画
- **SSE 事件类型**（Stage 3 关键逻辑，影响来源面板与补全引导）：
  - `retrieved`：原始检索候选（填充 rawSources）
  - `reranked`：精排后来源（填充 sources）
  - `sources_final`：最终来源（覆盖 sources）
  - `suggest_supplement` 标记：知识库未检索到时触发补全卡片
  - `faq_hit` 标记：FAQ 命中（可直返短路）
- **来源面板**（`_renderSourcesPanel`）：vector/keyword/reranked/unknown 四类来源图标，默认折叠态
- **引用文档卡片**（citations）：与来源面板并列
- **反馈机制**：消息级反馈按钮
- **FAQ 补全卡片**：双触发机制——
  1. SSE 收到 `suggest_supplement` 标记时
  2. 正则匹配回答内容"知识库中没有/未检索到"兜底（防标记在链路中丢失）
- 当前性能问题：每 token 全量 `innerHTML = marked.parse(fullContent)` 重渲（长回答卡顿，待优化）

### 5.7 FAQ 知识记忆（faq.js）

- **三 Tab**（不同状态、不同操作集）：
  - **正式知识**（active）：已蒸馏升格的 FAQ，可降级（demote）/删除
  - **候选记忆**（candidate）：显示命中进度（hit_count / distill_threshold），达阈值可升格（promote）/删除
  - **PR 审核**（pr）：我名下 KB 收到的协作 PR，可合并（mergePr，带 note）/拒绝（rejectPr，带 note）
- KB 过滤下拉（全部 / 指定 KB）
- 分页（pageSize 20）
- 操作 API 集合：promote / demote / remove / supplement / mergePr / rejectPr / shareKb / unshareKb / cloneKb

### 5.8 设置（settings.js）

- **8 个配置组**（固定顺序，groupOrder）：
  1. retrieval（检索）
  2. chunking（文档切分）
  3. llm（LLM 参数）
  4. session（会话与记忆）
  5. processing（文档处理）
  6. model（模型与 LLM）
  7. system（系统）
  8. api_keys（API Keys）
- 每组：标题 + "保存本组"按钮（带 dirty 数徽标，如 `保存本组 (3)`，无改动时禁用）+ 组内错误内联区
- 底部保留"全部保存"
- **字段类型**：text / password(密钥，留空=不修改) / csv(checkbox 组) / range(滑块)
- **分组保存 + dirty-only 提交**：只提交改动项，不收集全量
- partial_error 时按 key → 组映射，组内联标红到具体 key（比 toast 更可定位）
- 只读配置区（需重启）：单独一节，标记"只读"，修改需编辑 .env 文件并重启服务

### 5.9 审计中心（audit.js）

- **4 个筛选条件**：action(如 kb.create) / user_id / request_id / resource_type(kb/document/...)
- 查询 + 重置按钮
- 列表（表格形式）：动作 / 用户 / 资源类型:资源ID / kb_id / request_id(截断显示) / client_ip / 时间
- 分页（pageSize 50）
- **CSV 导出**（带鉴权头 fetch 下载）
- **管理员可见统计面板**（loadStats，非管理员隐藏）

---

## 六、硬性验收标准

1. **Design tokens 先行**：第一交付物为 tokens（CSS variables 文件或等价物：色彩/间距/圆角/字号/阴影/动效时长，含暗/亮两套），人工审核通过后才进入页面实现。
2. **三态规范**：空/加载/错误三态全局统一组件化（含进度接口的 failed 态），任何列表/卡片/流式区域不得缺失。
3. **响应式断点**：明确定义断点集并在主要页面验证（≥1440 / 1024-1439 / 768-1023 / <768），侧栏在小屏折叠行为明确。
4. **可访问性对比度**：正文文本对比度 ≥4.5:1，大字 ≥3:1（WCAG AA），暗亮两套都要过。
5. **浏览器旅程回归全绿**：work/stage-5/baseline/journey.spec.js 可重复执行（登录→建库→上传→pipeline→三模式检索→Agent SSE→设置→审计），控制台零 error。
6. 每层（信息架构→主题比例→细节）完成后截图对比，用户确认再继续。

## 七、产出要求与实现约束

- **流程**：先出设计稿（静态 HTML mock 或 .pen 均可）+ tokens → 人工审 → 通过后再实现。
- **实现红线**：
  1. 不改 `frontend/js/api.js` 的 API 契约（可加方法，不可改现有签名/行为）；
  2. SSE 流式消费逻辑与 pipeline 断点恢复逻辑不得破坏（幂等依赖状态机）；
  3. 保持无构建链：任何 JS/CSS 均为原生，直接被 `<script>`/`<link>` 引用；
  4. 暗亮主题必须同时维护（tokens 双套值）。
- 关键参考文件：frontend/index.html、frontend/css/main.css、frontend/js/app.js、frontend/js/api.js、frontend/js/pages/*.js；后端接口见 backend/api/（processing.py 进度/pipeline、faq.py、audit.py、search.py）。
- **产出物建议路径**（阶段 A 设计稿）：
  ```
  frontend/design/
  ├── tokens.css              # 设计 tokens（暗/亮双套，含玻璃风所需的 --glass-* 系列，由你自主定义）
  ├── preview.html             # 设计稿预览总览页（色板/tokens/组件三态/各页线框）
  ├── page-wireframes/         # 各页线框 HTML（按需分文件）
  └── DESIGN.md                # 设计说明（每个决策的理由、对应流程上下文、验收对照）
  ```
  路径仅为建议，可按你的习惯调整。阶段 B（审稿通过后）落地到 `frontend/css/main.css` 与各 `frontend/js/pages/*.js`。
