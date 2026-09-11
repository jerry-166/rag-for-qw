# Stage 2 合并注意事项与未实现项记录

> 日期：2026-08-20 | 分支：`feature/stage-2-3-adapters`（worktree `d:\workspace\rag-for-qw-s23`，commit c308aaa）
> 用途：Stage 2 分支合回主工作区（feature/stage-1-perf-startup → main）时的冲突预案

## 一、明确的冲突文件（两侧都改过）

| 文件 | 主工作区（Claude Code / Stage 1） | worktree（Stage 2） | 合并策略 |
|---|---|---|---|
| `backend/services/document_processor.py` | 04 独立项（参数热读/O(n²)/嵌入并行/删死代码/审计埋点） | 在其基础上委托 chunking/enhancers 适配器 | worktree 已基于 Stage 1 最新提交 a10577e，理论上 fast-forward；若主工作区 Stage 1 有新提交则需 rebase |
| `backend/api/processing.py` | 审计埋点 + 参数热读 | + 三级解析/启用集/缺口检测接口 | 同上 |
| `frontend/js/pages/settings.js` | （主工作区未提交新文件） | 复制后追加 csv 类型支持 | 见下「未提交依赖」 |
| `frontend/js/api.js` | 可能有 Stage 1 改动 | KB API 签名扩展 | 合并时人工核对 |
| `backend/services/database.py` | 01-C tokenized 列 | + KB 策略列 + skip flags | 均为增量迁移，顺序无关 |
| `backend/services/milvus_client.py` | 01-B readiness | + 检索短路 | 分段不重叠，可自动合并 |

## 二、主工作区未提交依赖文件（已复制进 worktree 并提交）

这 3 个文件在主工作区是 **untracked**（被已提交代码引用，但从未 commit）：

- `backend/services/retrieval_strategies.py`
- `backend/api/settings.py`
- `frontend/js/pages/settings.js`

**后果**：worktree 分支已包含它们的提交；主工作区（或 Claude Code 侧）若再 `git add` 提交这 3 个文件，合并时 git 会按「两侧各自新增同名文件」报 add/add 冲突。

**解法**：主工作区侧对这 3 个文件**不要单独提交**；等合并 feature/stage-2-3-adapters 时直接采用 worktree 版本（内容 = 主工作区原版 + Stage 2 增强）。

## 三、未实现项（遗留）

| 项 | 原因 | 何时做 |
|---|---|---|
| **03 §7 质量对照实验（A/B/C 三组）** | 需真实 LLM 调用（Stage 1 限流中）；是切换 CombinedEnhancer 默认路径的**硬性准入门槛** | Stage 1 限流解除、服务可跑后；命令与基准集方案见文档 03 §7 |
| **05a 批次 2**（配置分组保存按钮 + dirty-only 提交、agent 流式渲染节流） | Stage 2 优先适配器主体 | 随 Stage 4 或 UI 阶段前补齐 |
| **检索质量回归测试**（02/03 改动后 hybrid/advanced 检索结果与整改前对比） | 需服务可跑 + Milvus 在线 | 与对照实验同批 |

## 四、Stage 2 自验结果快照

- 20 文件 py_compile 全过；策略注册/三级解析/auto 行为快照（4 chunks 与迁移前一致）/EnhancerPipeline no-op/循环导入/app 全量导入 OK
- 4 个前端 JS node --check 全过；lint error = 0
- **未做真实服务 E2E**（受限流影响）——合并后必须补一轮真实处理管线回归（上传→切割→生成→导入→检索）
