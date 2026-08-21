# Stage 5 前端重构 · 圈 3 报告：documents / pipeline / search 三页按线框 02/03/04 适配

> 日期：2026-08-21 | 分支：main | 结论：**达标收敛**

## 1. 改动内容

### 1.1 documents.js（线框 02）
- 上传区统一拖拽 dropzone（虚线玻璃框 + hover/drag 高亮 + 线性 SVG 上传图标），点击/拖放共用一条上传路径。
- 新增**「处理中」队列卡**：上传后把 file_id 入队，3s 轮询 `GET /api/process/{file_id}/progress`（api.js 新增 `getProgress` 方法，不改现有契约）；渲染真实进度条（`stage_progress.done/total`）、阶段徽章链（切割✓耗时 / ●生成中 / 导入·待执行，数据来自 `timing_ms`）、预计剩余（历史耗时×未完成比例外推，无历史时按已运行速度估计）；stage=done 出队 + toast + 列表刷新。
- 列表结构对齐线框：文件/知识库/状态/上传时间/操作五列；状态徽章六态（uploaded/chunk_done→生成中/generated→待入库/importing/completed/failed）；failed 行主按钮变「重试」、新文档变「开始处理」；删除改 **icon-btn（32px SVG 垃圾桶）**，全部事件改 addEventListener（去掉内联 onclick）。
- 顶栏 KB 过滤下拉（服务端过滤）；重进页面时把 chunk_done/importing 状态的存量文档自动纳入进度队列（断点可见性）。

### 1.2 pipeline.js（线框 03，问题 5/9 前端侧）
- 顶部新增「返回文档管理」+ 文件徽章 + `file_id · stage` mono 说明。
- **stepper 重构**：orb（done 金圈✓ / running 金底脉冲 / pending 灰）+ **连线内嵌真实进度**——`step-link > i` 的 `scaleX` 由 progress 接口的 stage/stage_progress 驱动（generating 时 = done/total 比例），彻底消灭假进度条。
- 新增**吞吐明细行**：当前阶段 · 进度 done/total · 历史耗时（切割/生成/导入，来自 `timing_ms`）+ 底部阶段进度条；failed 态显示 `last_error.message`。
- `refreshProgress()`：进入页面 + split/generate/import 各阶段完成后拉取，同步 steps done 标记（断点恢复：重进页面即点亮正确阶段）。
- Step2 假进度条（写死 width:100%）删除，改真实切割耗时显示；**timeline embed 字段 'N/A' 由真实 import_time 替代**（原「嵌入向量生成」「写入 Milvus」两行合并为一行）；`_fillImportStats` 同步修。
- missing-banner 对齐线框 warn 条样式：「检测到增强缺口 · N 个 Chunk 缺失（子问题 ×x、摘要 ×y）+ 一键补生成 + 忽略」；调用 `GET /generate/{id}/missing` + 补生成逻辑不变（红线保留）。

### 1.3 search.js（线框 04）
- 信息架构改 **Hero 命令面板**：大搜索框 + Enter 直接触发 + 第二行控件（seg 模式切换三段式 / 策略下拉 / Rerank switch / Top-K / KB 下拉）。
- **最近搜索改 hero 内 chips**（点击重搜 + 去重 + 清空按钮），历史 localStorage 契约不变。
- **横向召回漏斗（基础版，纯前端消费现有 API 返回）**：FAQ→实体图谱→向量分层→结果 四段条，分层计数来自结果项 `type` 字段（summary/subquestion/native→向量层，graph→实体层），命中层用 tokens 漏斗分层色（FAQ 金 `--layer-faq` / 实体紫 `--layer-entity` / 向量蓝 `--layer-vector` / 结果绿），未命中层灰显；底行内联统计（耗时/条数/Rerank/模式/策略）。不新增后端。
- 结果卡：双分数（rerank 主分 + RRF 小字）+ 分数条 + 分层色来源徽章（摘要/子问题向量蓝、实体紫、reranked 金、BM25 灰）。
- 三态保留（空/加载/错误），空态「尝试向量/混合检索」切换建议保留。

### 1.4 main.css
- 新增圈 3 块：`.glass-card`、dropzone、processing-card、stepper（orb/step-link/脉冲）、stepper-card、search-hero、seg、src-chip、funnel 系（funnel-h/layer/bar/arrow/stats-row）、结果卡右列双分数布局。沿用 tokens 变量，暗亮双套自动生效。
- index.html 资源缓存版本 `?v=20260821` → `?v=20260821c3`。

## 2. 冒烟中发现并修复的问题
- **search 按钮无 click 监听**（重构时遗漏绑定 `#search-btn`）：UI 点击不触发检索 → initEvents 补绑，修后三模式全部出结果。
- **上传落库目标错位**：页面 KB 下拉选中值未同步到 `currentKbId`，上传走了后端「第一个 KB」兜底 → uploadFiles 前同步下拉选中值；冒烟脚本同时修正 KB 选择方式（evaluate 设值绕过 option 加载时序）。
- 顺带清理：误传的 doc 155 + 陈旧 KB 19（circle2 残留）已删除。

## 3. 验证数据（客观命令结果）

- `node --check`：documents.js / pipeline.js / search.js / api.js 全 OK。
- **冒烟**（work/stage-5/circle3/smoke.js）：
  - documents：dropzone `border:dashed; radius:20px; cursor:pointer`；表头五列对齐线框；icon-btn 14 个；上传后处理中队列卡 visible（`circle3-smoke.md · 待切割 0/0 · 切割·待执行`）。
  - pipeline：stepper 连线 `scaleX(1)/scaleX(0)/scaleX(0)` 起始 → 切割后 detail「生成增强 · 进度 0/1 · 切割 169ms」→ 生成后「嵌入入库 · 进度 1/1 · 生成 4.0s」→ done；timeline 全真实值（upload 9.13ms / split 168.77ms / generate 3.99s / embed 26.63s，无 N/A）；**断点恢复**：重进 pipeline orbs 全 ✓、detail「全部完成 · 共 1 chunks · 历史：切割 169ms · 生成 4.0s · 导入 26.6s」。
  - search：vector 结果 4 条（漏斗：向量分层 4 → 结果 4，来源徽章「摘要向量/子问题向量」蓝色系）；hybrid 结果 1 条（漏斗向量 1 → 结果 1，徽章 reranked 金色）；keyword 0 条（漏斗灰显，MMIT 见 §4）；历史 chips 1。
  - **console error 1：仅基线固有的 PDF.js 对 .md 报 InvalidPDFException**（与圈 1/2 相同，非本次引入）。
- **journey.spec.js 全旅程：15/15 PASS，console errors/warnings 1（同上基线项），bad requests 0**。
- 截图：`work/stage-5/circle3/shots/`（冒烟 01-09 + 旅程全量 01-10）。
- 测试残留清理：4 个 `stage5-circle3-*` KB 全部 DELETE 200，复核 remaining=0；旅程 KB 按惯例保留。
- 结束后 8000/8003 已杀净（netstat 复核无 LISTENING）。

## 4. 已知非本次范围项（如实记录）
- **keyword 模式对新上传单 chunk 小文档返回 0 条**：直接复现 BM25Client 本地调用也 0 分——单文档桶 IDF 不足（rank_bm25 对只出现于全部文档的词打 0 分），属既有检索行为，非本次前端改动引入（旅程中 keyword 在多文档 KB 下 PASS）。
- FAQ/实体层当前恒 0：测试 KB 未启用 entity、无 FAQ 记录；漏斗层消费逻辑已就位（type=graph → 实体紫层），待 Stage 3 数据接入后自然点亮。

## 5. 行为红线核验

上传 ✓（冒烟 02 + 旅程 05）、四步流水线 ✓（旅程 06.1-06.3 全 stage=done）、断点恢复 ✓（冒烟 RESUME 重进全亮）、三模式检索 ✓（旅程 07 三模式均出结果）、补生成功能 ✓（missing-banner + missing 查询 + backfill 逻辑保留未动，旅程 generate 幂等路径覆盖）。

## 6. 提交清单

- `frontend/js/api.js`（新增 getProgress，不改现有签名）
- `frontend/js/pages/documents.js`（整页重构）
- `frontend/js/pages/pipeline.js`（stepper 真进度 + timeline 真值 + banner 样式）
- `frontend/js/pages/search.js`（整页重构）
- `frontend/css/main.css`（圈 3 样式块）
- `frontend/index.html`（缓存版本号）
- `work/stage-5/circle3-notes.md` + `work/stage-5/circle3/`（smoke.js、journey.spec.js、shots、日志）
