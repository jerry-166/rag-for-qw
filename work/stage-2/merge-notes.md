# Stage 2/3 修复合并记录（feature/stage-2-3-merge）

日期：2026-08-20 | 基线：main 336ab88 + feature/stage-2-3-adapters c5f7f0b
依据：work/review-stage23/report.md

## 冲突处理（4 文件 9 处）

- `backend/services/retrieval_strategies.py`、`frontend/js/pages/settings.js`（add/add）：实测 theirs 分支版为 main 侧的严格超集（diff 全为 theirs 新增：GraphStrategy、csv 多选组等），取 theirs 即并集。
- `frontend/css/main.css`：两侧各自新增不同样式块（HEAD=设置页样式，theirs=缺口提示条/csv 组），取并集（两侧全保留）。
- `backend/agent/claw_agent/rag_workflow.py`（2 处语义冲突）：
  - hybrid_retrieval 节点：保留分支的 FAQ 前置召回块 + main 的热读 `retrieval_mode = state.get("retrieval_mode") or get_runtime("DEFAULT_RETRIEVAL_MODE", settings.DEFAULT_RETRIEVAL_MODE)`（丢弃分支硬编码 "advanced"）。
  - 初始状态构建：同上保留热读，并加入分支的 `"user_id": user_id`。

## P0 修复

- **P0-1 logger NameError**：retrieval_strategies.py 文件头新增 `logger = init_logger(__name__)`（import 行同步加 init_logger）；删除 milvus_search 与 AdvancedStrategy 内两处局部 `init_logger(__name__)` 定义（安全：模块级已覆盖，行为等价）。验证：graph 模式实测 200，日志出现降级 native，NameError=0。

## P1 修复

- **P1-1 clone_kb_vectors subquestions**：**实测推翻审阅报告的猜想**——连 Zilliz describe 实测 `chunk_subquestions` PK 是 `subquestion_id`(auto_id=True)，`chunk_id` 是普通字段，显式赋值并不报错；真实 bug 是 `output_fields` 未包含 `chunk_id`，导致 `r.get("chunk_id", 0)` 恒为 0（关联丢失且未重映射）。修法：output 补查 `chunk_id`，插入值改为 `chunk_map.get(r.get("chunk_id"), r.get("chunk_id", 0))`。（summaries 的 PK chunk_id auto_id=True 分支与 chunks 分支本就未给 PK 赋值，无问题。）
- **P1-2 supplement 隐式 PR 判空**：faq_service.py `create_faq_pr` 返回 None 时返回 `{"action": "error", "message": "知识条目提交失败（PR 创建失败），请稍后重试"}`，不再 audit.log(resource_id=None) / 伪成功。
- **P1-3 FAQ 阈值锁定 COSINE**：选「config 描述注明」方案（简单可靠）。config.py FAQ_HIT_THRESHOLD 注释注明 score 按 COSINE 语义、MILVUS_METRIC_TYPE 改非 COSINE 会方向反转、FAQ 召回仅支持 COSINE。
- **P1-4 GraphStrategy 补 distance**：graph 结果新增 `"distance": round(1.0 - base, 4)`（score 0.9/0.75 → distance 0.1/0.25），与下游 rag_tools `1 - distance >= min_score` 过滤链对齐（0.9/0.75 均可通过默认 min_score=0.3）。阈值无实测校准数据，保留原降级逻辑与日志，代码注释注明。
- **P1-5 clone 事务/清理**：clone_knowledge_base 的 except 块新增尽力而为清理：`conn.rollback()`（丢弃未提交写入）+ `delete_knowledge_base(new_kb_id)` 删除已建残留 KB（失败仅 warning 提示手工处理）。
- **P1-6 仓库卫生**：合并时排除 .playwright-cli/(10 文件)、faq-page.png、backend/boot.log、backend/boot.err、backend/_diag_faq.py、home.yaml、playwright-cli.json；.gitignore 追加对应规则防再犯。
- **P1-7 list_prs N+1**：database.list_faq_prs 新增 `target_kb_ids` 参数（`pr.target_kb_id = ANY(%s)`，COUNT 查询同步加 pr 别名）；api/faq.py 无参分支改为单次 ANY 查询并透传 page/page_size，消除 N+1 与 page_size=100 截断。

## 验证证据

见 verify.log：py_compile 7 文件全过；node --check 6 js 全过；import app OK；登录 200；/api/audit 200；建/删带 chunk_strategy+enhancers 的 KB 200/200；/api/faq、/api/faq-pr（含无参 ANY 路径）200；/api/process/generate/14/missing 200（12 chunks, 0 缺口）；graph 检索 200 且降级 native、NameError=0。
