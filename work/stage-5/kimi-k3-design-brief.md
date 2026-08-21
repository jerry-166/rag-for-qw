# Stage 5（05b）前端重构设计 Brief —— 致 kimi k3

> 日期：2026-08-21 | 依据：docs/plans/2026-08-18-05-config-and-ui-design.md（§1B/§3.3/§6）+ 本文件附带的浏览器基线实测刷新
> 产物位置：本文件 + work/stage-5/baseline/shots/（现状截图）+ work/stage-5/baseline/report.md（问题清单）

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

## 五、硬性验收标准

1. **Design tokens 先行**：第一交付物为 tokens（CSS variables 文件或等价物：色彩/间距/圆角/字号/阴影/动效时长，含暗/亮两套），人工审核通过后才进入页面实现。
2. **三态规范**：空/加载/错误三态全局统一组件化（含进度接口的 failed 态），任何列表/卡片/流式区域不得缺失。
3. **响应式断点**：明确定义断点集并在主要页面验证（≥1440 / 1024-1439 / 768-1023 / <768），侧栏在小屏折叠行为明确。
4. **可访问性对比度**：正文文本对比度 ≥4.5:1，大字 ≥3:1（WCAG AA），暗亮两套都要过。
5. **浏览器旅程回归全绿**：work/stage-5/baseline/journey.spec.js 可重复执行（登录→建库→上传→pipeline→三模式检索→Agent SSE→设置→审计），控制台零 error。
6. 每层（信息架构→主题比例→细节）完成后截图对比，用户确认再继续。

## 六、产出要求与实现约束

- **流程**：先出设计稿（静态 HTML mock 或 .pen 均可）+ tokens → 人工审 → 通过后再实现。
- **实现红线**：
  1. 不改 `frontend/js/api.js` 的 API 契约（可加方法，不可改现有签名/行为）；
  2. SSE 流式消费逻辑与 pipeline 断点恢复逻辑不得破坏（幂等依赖状态机）；
  3. 保持无构建链：任何 JS/CSS 均为原生，直接被 `<script>`/`<link>` 引用；
  4. 暗亮主题必须同时维护（tokens 双套值）。
- 关键参考文件：frontend/index.html、frontend/css/main.css、frontend/js/app.js、frontend/js/api.js、frontend/js/pages/*.js；后端接口见 backend/api/（processing.py 进度/pipeline、faq.py、audit.py、search.py）。
