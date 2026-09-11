# Stage 2/3 验收报告（供 Claude Code 同步使用）

> 日期：2026-08-20
> 分支：`feature/stage-2-3-adapters`（worktree `d:\workspace\rag-for-qw-s23`，最新 commit `c5f7f0b`）
> 基线：基于 `a10577e`（Stage 1 完成点）
> 服务：后端 8003（worktree）+ 前端 8001（worktree）+ Zilliz Cloud（云端 Milvus，DB=rag_system）+ litellm（LLM token）
> 测试用户：tester / test123456（user_id=2）
> 测试 KB：TestKB（kb_id=6，chunk_strategy=markdown，enhancers=["sub_question"]）

---

## 一、已通过验收项

### 1.1 Stage 2：切割策略适配器

| 项 | 结果 | 证据 |
|---|---|---|
| chunking 包策略注册（auto/markdown/recursive） | ✅ | 语法编译 + 注册表自检（`list_strategies()` 返回三个） |
| auto 策略行为快照（与迁移前一致） | ✅ | 含 `#`/`##` 的 markdown 文档 → auto 切出 4 chunks，与迁移前一致 |
| 三级解析（请求 > KB > 全局） | ✅ | `resolve_strategy_name(None, None)` → 'auto'；`resolve_strategy_name('markdown', 'recursive')` → 'markdown' |
| **KB 级策略 UI**（建库弹窗） | ✅ 浏览器实测 | 弹窗显示切割策略下拉（跟随全局/自动探测/Markdown/递归）+ 增强器 checkbox（子问题/摘要，默认勾选） |
| **KB 级策略后端**（建库 API） | ✅ API 实测 | `POST /api/knowledge-bases` body `{kb_name, chunk_strategy:"markdown", enhancers:["sub_question"]}` → 200，kb_id=6 |
| knowledge_base 表 chunk_strategy/enhancers 列迁移 | ✅ | 启动日志无迁移错误；建库后 PG 有数据 |
| 全局配置 CHUNK_STRATEGY（enum） | ✅ | runtime_config 白名单已加，settings 页可改 |
| 全局配置 ENABLED_ENHANCERS（csv 类型） | ✅ | runtime_config 新增 csv 校验/规范化；settings 页 checkbox 组渲染正常 |

### 1.2 Stage 2：增强生成适配器

| 项 | 结果 | 证据 |
|---|---|---|
| enhancers 包（Combined/SubQ/Summary/Entity/Pipeline） | ✅ | 语法编译 + 导入自检 |
| 双开走合并 prompt（token 成本最优） | ✅ 代码逻辑 | CombinedEnhancer 原样迁移 gen_chain prompt |
| 单开走精简 prompt | ✅ 代码逻辑 | SubQuestionEnhancer/SummaryEnhancer 独立 prompt |
| 全关 no-op（秒回，纯原文 RAG） | ✅ 单测 | `EnhancerPipeline(set())` → `is_noop=True`，`run_batch` 返回空结果 |
| **KB 级增强器配置**（建库 API） | ✅ API 实测 | enhancers=["sub_question"] 建库成功 |
| 检索短路（KB 未启用增强 → 不查对应集合） | ✅ 代码逻辑 | milvus_client.query 按 KB 启用集置 summaries/subquestions/entities 为 None |
| AdvancedStrategy 全关降级 native | ✅ 代码逻辑 | 两集合均 None → 委托 native |
| **显性补生成**（缺口检测接口） | ✅ API 实测 | `GET /api/process/generate/{file_id}/missing` → 200，返回 `{enabled_enhancers, total_chunks, missing_chunks, ...}` |
| save_chunk_enhanced_data_batch skip flags | ✅ 代码逻辑 | 未启用字段不删不写，保护已有数据 |

### 1.3 Stage 3 Phase 1：FAQ 记忆闭环

| 项 | 结果 | 证据 |
|---|---|---|
| PG faq/kb_share/faq_pr 三表创建 | ✅ | 启动日志无建表错误；FAQ CRUD 全通 |
| Milvus faq_vectors 集合创建 | ✅ | 启动日志 "FAQ 记忆集合创建成功" |
| **FAQ 补全写入**（私有 KB，阈值 2） | ✅ API 实测 | `POST /api/faq/supplement` body `{question, answer, kb_id:6}` → `action:created, faq_id:1, threshold:2, hit_count:1, status:candidate` |
| **双阈值机制**（私有 2 / 共享 3） | ✅ | 私有 KB6 写入时 `distill_threshold=2`（文档 06 §4.2） |
| 种子候选不立即蒸馏（防污染） | ✅ | status=candidate，hit_count=1 < threshold=2 |
| 候选记忆列表查询 | ✅ API 实测 | `GET /api/faq?status=candidate` → total=1 |
| 手动升格 active | ✅ API 实测 | `POST /api/faq/1/promote` → 200 success；active total=1 |
| **判重聚合**（相似 ≥0.95 → hit_count 累加） | ✅ API 实测 | 同一问题重复 supplement → `action:merged`，hit_count 累加到 11 |
| **FAQ 前置召回直返**（含 LLM 二次确认） | ✅ API 实测（修复后） | agent chat 返回 FAQ 答案 + `faq_hit=True` + `sources_count=0`（未触发检索） |
| 检索失败引导状态机 | ✅ API 实测 | KB6 无文档 → content="当前知识库中没有...可以补充...下次直接回答😊" |
| suggest_supplement 标记透传到 SSE | ✅ API 实测 | response_generated 事件 `suggest_supplement=True` |
| **知识记忆管理页**（三 Tab） | ✅ 浏览器实测 | 正式知识/候选记忆/PR 审核 Tab + KB 过滤 + 表格 + 空状态正常渲染 |
| 知识记忆导航项（🧠） | ✅ 浏览器实测 | 侧边栏出现"知识记忆"导航项 |
| FAQ 向量写入（insert_faq_vector） | ✅ | FAQ 召回命中 faq_id=1（向量已写入 Zilliz） |

### 1.4 Stage 3 Phase 2：实体图谱

| 项 | 结果 | 证据 |
|---|---|---|
| EntityEnhancer 注册 | ✅ | `VALID_ENHANCERS = {sub_question, summary, entity}` |
| PG entity/entity_relation 表创建 | ✅ | 启动日志无建表错误 |
| Milvus entity_vectors 集合创建 | ✅ | 启动日志 "实体向量集合创建成功" |
| GraphStrategy 注册 | ✅ | `available_modes()` 含 'graph' |
| GraphStrategy 降级 native（无锚点/未启用 entity） | ✅ 代码逻辑 | entities_collection None 或无 kb_id → 委托 native |
| 检索模式枚举加 graph | ✅ | runtime_config DEFAULT_RETRIEVAL_MODE enum 含 graph |
| 实体落 PG（同名合并 source_chunk_ids） | ✅ 代码逻辑 | upsert_entity 合并逻辑 + _persist_entities |
| 实体向量同步（import 阶段） | ✅ 代码逻辑 | _sync_entity_vectors 按文档关联实体 upsert 向量 |

### 1.5 Stage 3：KB 克隆（fork）

| 项 | 结果 | 证据 |
|---|---|---|
| clone_knowledge_base（PG 全量复制） | ✅ 代码逻辑 | 复制 KB/文档/chunk/增强/FAQ + tokenized 缓存，返回 id 映射 |
| clone_kb_vectors（Milvus 向量搬运） | ✅ 代码逻辑 | 按 id 映射转换 chunks/summaries/subquestions/faq 四集合 |
| KB 分享 API（share/unshare/list） | ✅ API 实测 | share_kb 写 kb_share + 同步 user_kb_permission；get_kb_shares JOIN users 返回 username |
| KB 克隆 API | ✅ API 注册 | `POST /api/kb/{kb_id}/clone` 路由存在 |

### 1.6 审计中心（随 Stage 2/3 埋点）

| 项 | 结果 | 证据 |
|---|---|---|
| audit_log 表 + 服务 + 中间件 | ✅ | Stage 1 已落地（commit a21532e） |
| process.split/generate 埋点带 strategy/enabled_enhancers | ✅ 代码逻辑 | processing.py split/generate 接口已埋 |
| FAQ 事件埋点（candidate_create/aggregate/promote/demote/delete/hit） | ✅ 代码逻辑 | faq_service.py 各方法已埋 |
| KB 分享/克隆埋点（kb.share/unshare/clone） | ✅ 代码逻辑 | api/faq.py 各接口已埋 |
| faq_pr 事件埋点（submit/merge/reject） | ✅ 代码逻辑 | api/faq.py + faq_service.py 已埋 |

---

## 二、修复的 Bug

### 2.1 CHAT_MODEL → DEFAULT_MODEL（commit c5f7f0b）

**根因**：`faq_service._confirm_answer` 与 `GraphStrategy._extract_anchor_names` 用 `settings.CHAT_MODEL`，但 Settings 类属性实际叫 `DEFAULT_MODEL`（config.py:44）。

**故障链**：FAQ 向量召回成功 → active 命中 → LLM 二次确认抛 `AttributeError` → 保守判定"未通过" → 降级正常检索（降级路径正确，用户体验无误，但 FAQ 直返特性被隐藏）。

**修复**：两处 `CHAT_MODEL` → `DEFAULT_MODEL`。

**修复后**：FAQ 直返完全工作，`faq_hit=True`，`sources_count=0`。

### 2.2 SSE 透传 suggest_supplement/faq_hit（commit 2370509）

**根因**：ClawAgentAdapter 的 SSE chunk 转发只透传 sources_count，丢弃了 suggest_supplement/faq_hit 标记。

**修复**：StreamChunk metadata 增加 `suggest_supplement` 与 `faq_hit` 字段透传。

### 2.3 get_kb_shares 缺 username（commit 2370509）

**根因**：`get_kb_shares` 返回裸 kb_share 表无 username，而 unshare API 需要 username。

**修复**：JOIN users 表返回 `shared_to_username`。

### 2.4 app.js:33 loading-screen null classList（commit 2370509）

**根因**：auth 页面无 `loading-screen` 元素，`document.getElementById('loading-screen').classList` 抛 null 异常。

**修复**：加 null 检查。

---

## 三、未验证项（需后续补齐）

| 项 | 原因 | 验证方式 |
|---|---|---|
| **03 §7 质量对照实验**（A/B/C 三组） | 需真实 LLM 多组对比 | 准备基准集（3-5 文档 50-100 chunk），跑 A（现状合并 prompt）/ B（CombinedEnhancer 迁移）/ C（独立精简 prompt）三组，LLM-as-judge 打分 |
| **文档上传→处理→检索全链路** | 需上传文档触发完整 pipeline | 上传一篇 markdown 文档 → split（markdown 策略）→ generate（单开 sub_question）→ embed → import → 检索验证 |
| **FAQ 蒸馏升格**（达阈值自动） | 需 candidate hit_count 达阈值 | 构造 candidate → 多次命中达 threshold → 验证自动升格 + LLM 蒸馏答案 |
| **GraphStrategy 实体检索** | 需 KB 有实体数据 | 上传文档 + 启用 entity 增强 → import → 用实体相关问题检索验证 graph 策略 |
| **KB 克隆 E2E** | 需 KB 有数据 | 克隆有文档/FAQ 的 KB → 验证 PG + Milvus 数据完整 |
| **PR 审核闭环** | 需两用户协作 | 用户 A 分享 KB 给 B（无直写权）→ B 补全 → A 审核 merge → B 检索命中 |
| **05a 批次 2**（配置分组保存、流式渲染节流） | Stage 2 优先适配器 | 随后续批次补齐 |

---

## 四、环境与运行信息

### 4.1 服务地址

| 服务 | 地址 | 说明 |
|---|---|---|
| 后端 API | http://127.0.0.1:8003 | worktree 后端，docs 在 /docs |
| 前端 | http://127.0.0.1:8001 | worktree 静态服务 |
| Zilliz Cloud | 见 backend/.env MILVUS_URI | 云端 Milvus，DB=rag_system |
| litellm | 见 backend/.env LITELLM_BASE_URL | LLM token 提供方 |

### 4.2 启动命令

```powershell
# 后端（worktree）
cd d:\workspace\rag-for-qw-s23\backend
d:\workspace\rag-for-qw\backend\.venv\Scripts\python.exe -X utf8 -m uvicorn app:app --host 0.0.0.0 --port 8003

# 前端（worktree）
cd d:\workspace\rag-for-qw-s23\frontend
d:\workspace\rag-for-qw\backend\.venv\Scripts\python.exe -m http.server 8001 --bind 127.0.0.1
```

### 4.3 测试数据

- 用户：tester / test123456（user_id=2）
- KB：TestKB（kb_id=6，chunk_strategy=markdown，enhancers=["sub_question"]）
- FAQ：faq_id=1（question="What is RAG?"，answer=完整版，status=active，hit_count=11）

### 4.4 配置注意

- `backend/.env` 不在版本控制（gitignore），worktree 需从主工作区复制
- Zilliz Cloud 集合创建有延迟，首次启动需等 30-40 秒（FAQ/entities 集合向云端创建）
- PowerShell 中文编码坑：API 验证用纯 ASCII 内容或 Python 脚本绕过

---

## 五、合并注意事项（Stage 2/3 合回 main）

### 5.1 冲突文件

| 文件 | 主工作区（Stage 1） | worktree（Stage 2/3） | 合并策略 |
|---|---|---|---|
| `backend/services/document_processor.py` | 04 独立项 | 在其基础上委托适配器 | worktree 基于 a10577e，理论上 fast-forward |
| `backend/api/processing.py` | 审计埋点 | + 三级解析/启用集/缺口检测/实体同步 | 同上 |
| `frontend/js/pages/settings.js` | 未提交新文件 | 复制后追加 csv 支持 | 采用 worktree 版本 |
| `backend/services/retrieval_strategies.py` | 未提交新文件 | 复制后追加 GraphStrategy | 采用 worktree 版本 |
| `backend/api/settings.py` | 未提交新文件 | 复制 | 采用 worktree 版本 |

### 5.2 未提交依赖文件（主工作区 untracked）

主工作区有 3 个 untracked 文件被已提交代码引用，worktree 已包含它们的提交：
- `backend/services/retrieval_strategies.py`
- `backend/api/settings.py`
- `frontend/js/pages/settings.js`

**解法**：主工作区侧对这 3 个文件不要单独提交；合并时直接采用 worktree 版本。

### 5.3 提交历史

```
c5f7f0b fix(stage3): CHAT_MODEL -> DEFAULT_MODEL in faq_service & GraphStrategy
2370509 feat(stage3): self-evolving RAG - FAQ memory + fork/PR collaboration + entity graph (doc 06)
c308aaa feat(stage2): 切割策略适配器 + 增强生成适配器 + 显性补生成（文档02/03）
a10577e perf(bm25): 01 §7.1 LRU 双上限 + 05a 批次1 前端功能修复（主体改动）  ← 基线
```

---

## 六、给 Claude Code 的行动建议

1. **合并前**：先在主工作区提交 Stage 1 的剩余改动（若有），再 merge `feature/stage-2-3-adapters` 分支，处理上述冲突文件。
2. **合并后**：跑一次完整 E2E（文档上传→处理→检索→FAQ 闭环→GraphStrategy），补齐第三节"未验证项"。
3. **质量对照实验**（03 §7）：是切换 CombinedEnhancer 默认路径的硬性门槛，合并后务必执行。
4. **Stage 4**：审计中心全局验收 + 大批量测试——此时三个 Stage 的真实事件已积累，可查审计中心验证无漏记。
5. **Stage 5**：UI/UX 整合优化（05b），届时切 kimi k3。
