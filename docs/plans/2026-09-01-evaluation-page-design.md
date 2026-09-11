# 测试集管理页面设计（C 前置）

> 日期：2026-09-01 | 状态：spec（待执行）
> 定位：方案 C 的质量基础设施——先有审核+导入，C 的 ground truth 才可信
> 排期顺序：B 轮1 → **本页面** → C 轮1
> 前置报告：`docs/plans/2026-08-31-rag-benchmark-comparison.md`、`docs/plans/2026-09-01-ragas-quality-evaluation-design.md`

---

## 一、目标与定位

为 RAGAS 评估提供可信的测试集管理闭环：**从 session 提取 → 待审状态 → 人工审核（含 LLM 辅助补 ground_truth）→ approved 入评估 → 支持外部公开集导入**。

没有这个闭环，`from-sessions` 提取的样本缺 ground_truth + answer 可能幻觉，C 的 RAGAS 分数（尤其 context_recall）不可信。

---

## 二、设计决策（已与用户确认）

| 决策点 | 选择 |
|---|---|
| 页面定位 | **C 前置**（B 轮1 → 本页面 → C 轮1） |
| 审核流程 | **待审状态流转**：提取后 status=pending，逐条审核通过转 approved，approved 才参与评估 |
| ground_truth 补充 | **LLM 辅助 + 人工确认**：页面上基于 contexts 一键调 LLM 生成 GT 草稿，人工改后保存 |
| 导入格式 | **兼容多格式**：本项目格式 + RAGAS 标准 + CRUD-RAG/NFCorpus 自动适配（带格式探测） |

---

## 三、现状摸底（已调研）

### 后端已有（`backend/api/evaluation.py` + `evaluation/` 模块）
- `POST /api/evaluation/dataset/from-sessions`（从 session 提取，但**无 status 字段、无审核流转、GT 留空**）
- `GET /api/evaluation/dataset/list`
- `POST /api/evaluation/fill/{name}`（填充 answer/contexts）
- `POST /api/evaluation/run`（异步跑 RAGAS 四指标）
- `GET /api/evaluation/reports`、`/reports/{filename}`
- 数据模型 `EvaluationSample`（`dataset.py:46`）：question/ground_truth/answer/contexts/metadata，**无 status 字段**

### 前端缺口
- `frontend/js/api.js` **0 处** evaluation 调用——前端从未接入
- `frontend/index.html` 9 个 nav-item（knowledge-bases/documents/search/agent/faq/settings/audit/cache）**无 evaluation 入口**
- 无 `js/pages/evaluation.js`
- 页面 JS 模式参考 `audit.js`：全局对象 `const XxxPage = {...}` + `async render()` 写 `#page-container` + 用 `glass/p5/mb4` 裸类（需 inline 兜底，见 MEMORY main.css 陷阱）

---

## 四、后端扩展

### 4.1 数据模型扩展（`evaluation/dataset.py`）
`EvaluationSample` dataclass 新增字段：
```python
status: str = "pending"  # pending | approved | rejected
```
- `from_session_history` 提取的样本默认 status=pending
- 手动标注（`add_manual`）默认 status=approved（人工写的直接可用）
- 导入的样本：本项目格式保留原 status；外部格式默认 pending（需审核）
- `is_complete()` 不变（仍看 question+answer+contexts）；新增 `is_evaluable()` = `is_complete() and status=="approved" and ground_truth`
- `load()` 兼容旧 JSON（无 status 字段时默认 pending）
- `save()` 写入 status

### 4.2 新增端点（`backend/api/evaluation.py`）

| 端点 | 方法 | 用途 | body/参数 |
|---|---|---|---|
| `/dataset/{name}/samples` | GET | 分页+status 过滤查样本 | query: status, page, page_size, source |
| `/dataset/{name}/sample/{idx}` | GET | 单条详情 | — |
| `/dataset/{name}/sample/{idx}` | PATCH | 改 answer/contexts/ground_truth/status | body: 任意字段 |
| `/dataset/{name}/sample/{idx}/approve` | POST | 一键通过 | — |
| `/dataset/{name}/sample/{idx}/reject` | POST | 驳回 | — |
| `/dataset/{name}/sample/{idx}/generate-gt` | POST | LLM 基于 contexts 生成 ground_truth 草稿 | — |
| `/dataset/import` | POST | 多格式导入 | multipart: file + query: format(auto/ours/ragas/crudrag/nfcorpus) |
| `/dataset/{name}` | DELETE | 删除测试集 | — |
| `/dataset/{name}/export` | GET | 导出 | query: format(ours/ragas) |

### 4.3 LLM 生成 GT 服务
新增 `evaluation/gt_generator.py`：
- 输入：question + contexts（检索到的文档片段）
- 调 litellm（`LLM_MODEL=gpt-4o` via `LITELLM_BASE_URL`），prompt：「基于以下检索到的上下文，为问题生成一个简洁准确的标准参考答案，仅依据上下文，不编造」
- 返回 ground_truth 草稿字符串
- 前端拿到后填入编辑框，人工改后 PATCH 保存

### 4.4 多格式导入适配器
新增 `evaluation/importers.py`：
- `detect_format(data) -> str`：探测 JSON 结构（看顶层 keys / sample keys）
  - 本项目格式：有 `samples[].question + .metadata.source`
  - RAGAS 标准：`[{question, answer, contexts, ground_truth}]` 或 `{examples:[...]}`（datasets 库格式）
  - CRUD-RAG：看其字段名（`query/answer/ctxs`）
  - NFCorpus：`{queries:{id:text}, qrels:{id:{docid:rel}}, corpus:{id:{text}}}` 需转换
- `convert_to_ours(data, fmt) -> List[EvaluationSample]`：归一化到本项目格式
- NFCorpus 特殊：无 answer/ground_truth，只有 qrel——导入时 answer/contexts 留空（待 fill），ground_truth 由 qrel 相关文档拼接

---

## 五、前端页面设计（`frontend/js/pages/evaluation.js`）

### 5.1 全局对象
```js
const EvaluationPage = {
  _datasets: [], _current: null, _samples: [], _page: 1, _pageSize: 20,
  _filters: { status: 'all', source: 'all' },
  async render() {...},
  // 方法：listDatasets, loadSamples, showSampleDetail, approve, reject,
  //       generateGt, saveEdit, importFile, exportDataset, runEval
}
```

### 5.2 布局（参考 audit.js，但容器用 inline style 兜底 main.css 裸类陷阱）
- 顶部：标题「测试集管理」+ 统计卡（total/pending/approved/with_gt/by_source）+ 「导入」「从 session 提取」「跑评估」按钮
- 左侧：测试集列表（name + count + 完整度）
- 右侧：选中测试集的样本表格
  - 列：question（截断）/ source / status（徽章：pending 黄/approved 绿/rejected 红）/ with_gt（✓/✗） / 操作
  - 操作：审核（弹浮层看详情）/ 通过 / 驳回 / 编辑（含「生成 GT」按钮）
- 浮层（fixed 全屏遮罩 + blur + z-index 60+）：样本详情 + 编辑框（question/answer/contexts/ground_truth）+ 「一键生成 GT」按钮（调 generate-gt 端点，showLoading 遮罩）

### 5.3 交互约定（按 MEMORY UI 铁律）
- 玻璃底 + 表单控件显式强化对比度：`accent-color: var(--accent)` + `outline: 1px var(--border-light)` + `:has(:checked)` 切 accent-soft
- 弹层用浮层（fixed 全屏遮罩），禁原生 confirm/prompt/alert，统一 `window.UI.confirm/prompt/alert`
- 长操作（生成 GT/导入/跑评估）用 `App.showLoading/hideLoading`（z-index 998），结束才 toast
- 改完 evaluation.js + index.html 必须 bump `?v=`

### 5.4 质量门控
- 「跑评估」按钮：approved 样本数 < 30 时禁用 + 提示「审核通过样本不足 30，无法保证评估统计显著性」
- 跑评估时后端 `/run` 也校验 approved 数（双保险）

---

## 六、index.html 挂载
- sidebar 加 `<a class="nav-item" data-page="evaluation" title="测试集">`（放 audit 后、cache 前）
- 底部加 `<script src="js/pages/evaluation.js?v=20260901c1"></script>`
- bump api.js / app.js 的 `?v=`（如有改动）

---

## 七、边界（不做的，YAGNI）

- ❌ 评估结果可视化图表（reports 列表保留，图表留后续）
- ❌ 多用户协作审核（单人审核，无锁）
- ❌ 实时流式审核
- ❌ 导入文件 > 10MB（前端校验拒绝）
- ❌ 改 `evaluator.py` 的 RAGAS 评估逻辑（保持不变）
- ❌ 改 `from_session_history` 的提取逻辑（只加 status 字段）

---

## 八、验收标准（端到端可测，四个「真实」）

1. **提取→审核闭环**：调 `/dataset/from-sessions` → 页面看到 pending 样本 → 点「通过」转 approved → 重新 load 确认 status 持久化
2. **LLM 生成 GT**：样本详情点「一键生成 GT」→ showLoading → 返回草稿填入编辑框 → 人工改 → 保存 → 重新 load 确认 ground_truth 已存
3. **多格式导入**：造一份 CRUD-RAG 样例 JSON（5 条）+ 一份 RAGAS 标准格式（5 条）+ 一份 NFCorpus 样例 → 分别上传 → 格式探测正确 → 入库为 pending 样本
4. **质量门控**：approved < 30 时「跑评估」按钮禁用 + 后端 /run 返回 400
5. **缓存验证**：改完 `getComputedStyle` 验证无 CSS 变量失效 + 浏览器硬刷新确认新版本生效
6. **真实合理**：from_session 的 answer 标注「Agent 生成，需审核」提示，不误导用户当标准答案

---

## 九、实现任务分解（子 agent 边界）

按用户要求「调用子 agent 保证上下文质量」，分 3 个子任务，主 agent 审阅：

### 子任务 A：后端（`superpower子agent`，主 agent 审阅）
- `evaluation/dataset.py`：加 status 字段 + `is_evaluable()` + load 兼容旧 JSON + save 写 status
- `evaluation/gt_generator.py`：新增 LLM 生成 GT 服务
- `evaluation/importers.py`：新增 detect_format + 4 个 convert_to_ours 适配器
- `backend/api/evaluation.py`：新增 9 个端点（samples 分页/sample 详情/PATCH/approve/reject/generate-gt/import/delete/export）+ `/run` 加 approved 数校验
- 自测：curl 每个端点确认 200 + 数据落盘

### 子任务 B：前端（依赖 A 完成，`superpower子agent`）
- `frontend/js/pages/evaluation.js`：全局对象 + render + 所有交互方法
- `frontend/index.html`：加 nav-item + script + bump ?v=
- `frontend/js/api.js`：加 evaluation 调用封装（如该项目有统一 api 层）
- 自测：浏览器走完提取→审核→生成GT→导入→跑评估全流程

### 子任务 C：验收脚本（`superpower子agent` 或主 agent）
- `work/evaluation-page/verify.py`：端到端跑验收标准 1-4
- 输出 `work/evaluation-page/verify_result.json`

---

## 十、风险与对策

| 风险 | 对策 |
|---|---|
| 旧测试集 JSON 无 status 字段导致 load 报错 | load() 兼容：无 status 默认 pending |
| LLM 生成 GT 质量不稳定 | 草稿模式 + 人工确认 + prompt 限定「仅依据上下文不编造」 |
| NFCorpus 格式特殊（qrel 无 answer） | 导入时 answer/contexts 留空待 fill，ground_truth 由 qrel 相关文档拼接 |
| 多格式探测误判 | detect_format 看多个特征 key + 用户可在 UI 手动指定 format 覆盖 |
| 前端裸类名布局崩 | 容器强制 inline style 声明 display/grid（MEMORY main.css 陷阱） |
| 缓存命中旧版 | 改完 bump ?v= + 硬刷新验证 |

---

## 十一、工期

- 子任务 A（后端）：1 天
- 子任务 B（前端）：1 天（依赖 A）
- 子任务 C（验收）：0.5 天（依赖 B）
- 合计 2.5 天，作为 C 轮1 前置
