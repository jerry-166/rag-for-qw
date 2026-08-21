# Stage 5 浏览器基线报告（Playwright 旅程）

> 日期：2026-08-21 | 脚本：work/stage-5/baseline/journey.spec.js（可重复执行，作回归脚本）
> 环境：后端 8003（FastAPI）、前端 8000（py http.server，静态）；账号 admin/admin123
> 最终通过率：15/15 | console error: 2（均为新发现） | 失败网络请求: 0

## 旅程结果

| 步骤 | 结果 | 备注 |
|---|---|---|
| 01 登录页渲染 | PASS | 截图 01-login-page.png |
| 02 登录→知识库列表 | PASS | |
| 03 新建测试 KB | PASS | 每次运行新建 `stage5-baseline-<时间戳>` KB |
| 04 文档页渲染 | PASS | |
| 05 上传 markdown | PASS | file_id=149，http=200 |
| 05b 进度接口轮询 | PASS | GET /api/process/progress/149（awaiting_split→done 全程可观测） |
| 06.1 pipeline 切割 | PASS | 点击「下一步」触发，进度接口确认 stage 推进 |
| 06.2 pipeline 生成 | PASS | generate 约 8s（LLM 增强 1 chunk） |
| 06.3 pipeline 导入 | PASS | stage=done，Milvus 入库成功 |
| 07 检索 vector/keyword/hybrid | PASS | 三模式均有结果（5/1/2 个节点） |
| 08 Agent SSE 对话 | PASS | 首块 30ms |
| 09 设置页渲染 | PASS | 分组保存按钮在位 |
| 10 审计页渲染 | PASS | |

截图目录：work/stage-5/baseline/shots/（01~10 全套 + pipeline 分步）。

## 文档 05 §1B 问题清单刷新

| # | 问题 | 状态 |
|---|---|---|
| 1 | search.js:284 `loadKnowledgeBables` 拼写 | 仍在（本次未触发失败路径，代码确认未改） |
| 2 | search.js:623 引号转义无效 | 仍在 |
| 3 | search-stats-card 双 style 属性 | 仍在 |
| 4 | 删除按文件名 key + onclick 注入 | 半修复：已改用 file_id 传参（documents.js:207-210），内联 onclick 模式仍在 |
| 5 | 上传无进度/无轮询 | 后端已就绪（新进度接口），前端 UI 未接 |
| 6 | console.log 调试残留 | 部分仍在 |
| 7 | auth.js 死代码 | 已修复（文件已删） |
| 8 | API_BASE 硬编码 | 已修复（origin 推导 + window.API_BASE 覆盖；8000→8003 推导实测有效） |
| 9 | 假进度条/timeline embed 'N/A' | 仍在；现可用真进度接口替换 |
| 10 | 每 token 全量 innerHTML 重渲 | 待长回答帧率专项确认 |

## 新发现问题（本次基线发现并处置）

| # | 问题 | 状态 |
|---|---|---|
| N1 | KB 创建必 422：后端 `chunk_strategy: str = None`（Pydantic v2 拒绝显式 null），前端新建 KB 默认传 null →「跟随全局配置」必失败 | 本轮已修：api/knowledge_bases.py 改 `Optional[str]`，复测创建成功 |
| N2 | pipeline step0 对 .md 文档也尝试 PDF.js 渲染 → `PDF.js渲染失败: InvalidPDFException`（有 fallback 不阻断，但污染控制台） | 未修，列入 05b |
| N3 | pipeline.js `loadStatsOverview` 在统计 DOM 未渲染时抛 `Cannot set properties of null (setting 'textContent')`（pipeline.js:1261） | 未修，列入 05b |

## 测试资源清单（本次运行产生）

- 知识库：`stage5-baseline-2026-08-21T06-19-23`（及试跑同前缀 KB：06-02-30 / 06-09-00 / 06-12-11 / 06-16-43）
- 文档：file_id 146-149（stage5-baseline.md，含向量入库）
- 账号：使用现有 admin（未新建用户）
