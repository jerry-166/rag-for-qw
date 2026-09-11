# 设计文档 06：自进化 RAG——新知识库策略（GraphRAG-lite on Milvus + 记忆闭环）

> 状态：待审阅 | 日期：2026-08-18（2026-08-19 三轮评审整版重写）
> 关联会话：CodeBuddy `ba351fe47878477b8fe33587ca522f59`（方案研讨的完整结论来源）
> 依赖：文档 03 的 Enhancer 适配器架构（EntityEnhancer 挂载点）；文档 02 的 KB 级配置机制

## 1. 方向确认（来自会话 ba351fe4 的研讨结论）

- **选定路线 A**：GraphRAG-lite on Milvus——不引入图数据库，实体描述与关系三元组向量化存入 Milvus 集合，检索时「实体相似度匹配 → 关系扩展 → 关联 chunk 召回」，用纯向量库逼近 GraphRAG 多跳关联效果。
- **产品灵魂**：自进化 RAG——「检索失败 → 人工/agent 补全 → 写回知识库 → 下次命中」的记忆闭环。知识是复利积累的资产，而非一次性加工。
- **与 B（个人知识管理系统）的关系**：B 是「事件驱动记忆」的元范式（hook 发现信号 → skill 规范动作 → 存储长期留存），本项目是该范式在业务 RAG 上的实例化：检索失败检测器 = hook，`save_*` 工具函数 = skill，Milvus entities/relations/FAQ = Obsidian。
- **写库必须是函数调用**而非模型自由文本（模型不会可靠遵守），触发信号 = 检索失败 + 用户愤怒/纠正，由逻辑强制触发。
- **提示词状态机**：命中 → 直接答；低置信 → "找到但不确定"；失败 → "我不会，请补充，我可成长"。

## 2. 分层存储模型

知识不是存一次就完，而是从原始材料逐层蒸馏为高价值、快命中形态：

| 层 | 内容 | 载体 | 作用 |
|---|---|---|---|
| L0 原始层 | 原文文档 / chunk | PG `document_chunk` | 证据溯源、永不丢 |
| L1 向量层 | chunk embedding | Milvus `chunk_vectors`（已有） | 语义相似检索 |
| L2 图谱层 | 实体 + 关系三元组 | Milvus `entities` / `relations`（新建） | 多跳关联、概念连接 |
| L3 结论层 | FAQ（Q-A 对，LLM 蒸馏产物） | PG + Milvus `faq` 集合（新建） | 高频问题确定性直返 |

L3 从「L0 + 用户补全」蒸馏而来（**不是原始口语记录**，必须有证据、结构化）；L2 从 L0 抽取而来。

### 集合 Schema（2026-08-19 三轮评审定案：删除 scope 字段，记忆条目只带 kb_id）

```
# Milvus 新增（复用现有三集合的创建模式，milvus_client.py create_collections 扩展）

entities:   entity_id(PK), kb_id, owner_id, name, type, description,
            embedding, source_chunk_ids(JSON), created_at
relations:  relation_id(PK), kb_id, owner_id, head_entity_id, relation_type,
            tail_entity_id, evidence, embedding, created_at
faq:        faq_id(PK), kb_id, owner_id, submitter_id, question, answer, embedding,
            hit_count, last_hit_time, heat_score, source, status(candidate|active|pending_review)

# PG 新增（KB 分享关系 + FAQ 权威表 + PR 队列）
kb_share:   share_id(PK), kb_id, shared_to_user_id, shared_by_user_id, shared_at,
            can_write_directly BOOL  -- 是否允许被分享者直接写 candidate（不克隆）
faq:        faq_id(PK, 与 Milvus 同), kb_id, owner_id, submitter_id, question, answer,
            hit_count, last_hit_time, heat_score, source, status, distill_threshold, created_at
faq_pr:     pr_id(PK), source_faq_id, target_kb_id, submitted_by, submitted_at,
             status(open|merged|rejected), reviewed_by, reviewed_at, review_note
```

PG 侧 `faq` 权威表含热度 + `distill_threshold`（每条记录自带阈值，升格时直接比对），Milvus `faq` 集合只放 question 向量用于召回——与现有「PG 权威 + Milvus 向量」三层架构一致。

**字段说明**：
- `kb_id`：记忆条目所属 KB。可见性完全由 KB 的分享关系决定，不在记忆条目上设 scope 字段。
- `owner_id`：KB 主人（用于审计与权限判定）。
- `submitter_id`：实际写入者（区别于 owner_id——共享 KB 的 candidate 可能由非库主提交）。
- `distill_threshold`：该条 candidate 升格所需 hit_count，写入时按 KB 归属自动赋值（见 §4.2）。
- `status`：`candidate`（待升格）/ `active`（已升格直返）/ `pending_review`（共享 KB 直接提交路径，等库主审核）。

### 记忆范围：KB 可见性驱动（2026-08-19 三轮评审定案）

**核心模型**：记忆条目只带 `kb_id`，不带 `scope` 字段。可见性完全跟 KB 的分享关系走——KB 私有则只有主人能读，KB 被分享则被分享者能读。**没有 global scope**——"全局"只是检索入口决定的读取视野，不是写入位置。

**KB 来源属性（维度 2）**：

| KB 来源 | 谁能读 | 谁能写 candidate |
|---|---|---|
| 我的私有 KB | 仅我 | 我（自动升格，阈值 2） |
| 我分享出去的 KB | 我 + 被我分享的人 | 我（自动升格，阈值 3）+ 被分享者（走 PR 审核，见下） |
| 别人分享给我的 KB | 我 + 库主 + 其他被分享者 | 走 §2.1 两条路径 |

**读取范围（由检索入口决定，维度 3）**：

| 检索入口 | 读取范围 |
|---|---|
| KB 级检索（指定某 KB） | 该 KB 的所有 active FAQ + entities + relations |
| 全局检索（不指定 KB） | 我可见的所有 KB（我的私有 + 我分享出去的 + 别人分享给我的）的 active 记忆 |

**检索过滤条件**（按当前用户与入口动态拼装）：
```sql
-- 全局入口
WHERE kb_id IN (我可见的 KB 集合 = 我的私有 KB ∪ 我分享出去的 KB ∪ 别人分享给我的 KB)
  AND status = 'active'
-- KB 级入口
WHERE kb_id = ? AND status = 'active'
```

### 2.1 写入路径：GitHub 式双路径（2026-08-19 三轮评审定案）

借鉴 GitHub fork/PR 模型。补全写入的目标 KB **必须是"我能写的私有 KB"**（默认 `DEFAULT_PERSONAL_KB_ID`，UI 可改"我的其他私有 KB"）。共享 KB 的写入只通过以下两条路径：

| 路径 | 写到哪 | 谁能立刻读到 | 升格机制 |
|---|---|---|---|
| **(a) 克隆后写**（fork） | 我克隆出来的私有 KB（快照克隆，一次性 copy，不追上游） | 只有我（克隆版是我的私有 KB） | 我自己说了算（私有 KB 阈值 2，自动升格） |
| **(b) 直接提交**（PR） | 上游共享 KB 的 `pending_review` 队列 | 全员都读不到（还在 pending_review） | 库主审核（不依赖阈值，人工兜底） |

**路径 (a) 的补丁回上游**：我在克隆版里把 candidate 升格为 active 后，可选「提交共享」→ UI 弹"选择目标共享 KB"（只能选我对其有权限的共享 KB）→ 提交后该共享 KB 的库主收到 PR（`faq_pr` 表 `status=open`）→ 库主 merge 则该 FAQ 进共享 KB 的 active（`faq_pr.status=merged`）；reject 则不进（`faq_pr.status=rejected`）。此步是**可选的显式动作**——只在自己克隆版里用，不回上游也行。

**写入规则矩阵（按检索入口 × KB 归属）**：

| 入口 | 当前检索的 KB 归属 | 补全写入位置 | 能否事后提 PR |
|---|---|---|---|
| KB 级检索 | 我的私有 KB | 当前 KB（candidate，阈值 2） | 不需要 |
| KB 级检索 | 我分享出去的 KB | 当前 KB（candidate，阈值 3） | 不需要 |
| KB 级检索 | 别人分享给我的 KB（有 `can_write_directly=true`） | 当前 KB 的 `pending_review` 队列 | 不需要（直接进 PR 队列） |
| KB 级检索 | 别人分享给我的 KB（只读 / `can_write_directly=false`） | **重定向到 `DEFAULT_PERSONAL_KB_ID`**（candidate，阈值 2），UI 提示"已写入你的私有 KB，可事后提 PR 到该共享 KB" | 可选 |
| **全局检索** | （混合多 KB 召回） | **`DEFAULT_PERSONAL_KB_ID`**（candidate，阈值 2），UI 可改"我的其他私有 KB" | 可选 |

**核心规则**：全局入口**永不直接写共享 KB**——因为全局入口下"目标 KB"歧义太大（同时搜了多个 KB）。共享 KB 的写入只通过 (1) KB 级检索且有写权限时直接进 `pending_review`，或 (2) 事后从私有 KB 显式提 PR。这避免了"全局补全误污染全员"的风险。

**去重策略**：同 KB 内按 question embedding 相似度 ≥0.95 判定为同一记忆条目 → hit_count 累加而非新插入（共享 KB 多人重复补全自然聚合为热度）。

## 3. 检索路由（自进化后的完整漏斗）

```
用户提问
  │
  ├─ 1. L3 FAQ 召回（阈值严格 ≥0.9 + LLM 二次确认"该答案是否回答了问题"）
  │     └─ 命中 → 直接返回（hit_count+1, last_hit_time 更新）
  │
  ├─ 2. 实体锚点检测（LLM/NER 提取问题中的实体）
  │     ├─ 有实体 → L2 entities 向量匹配 → 沿 relations 扩展 → 关联 chunk
  │     │         └─ 实体查不到（新实体）→ 降级 3
  │     └─ 无实体 → 直接 3
  │
  ├─ 3. L1 chunk 向量检索（现有 native/advanced/hybrid 策略）
  │     └─ 低置信 → 4
  │
  └─ 4. 检索失败 → 提示词状态机输出"我不会，请补充，我可成长"
        └─ 用户补全 → 信号检测器（逻辑判断，非模型自觉）
              ├─ save_* 工具函数强制写库：EntityEnhancer 抽实体/关系 → 写 L2
              └─ 种候选 FAQ（status=candidate 或 pending_review, hit_count=1）
                    → 热度达标后升格 status=active（蒸馏）/ 库主审核升格
```

**实体 vs 向量的路由依据**：不是"全局性 vs 知识点"的模糊二分，而是**"问题中有无可识别实体锚点"**——有实体走 L2，无实体走 L1，L2 查不到降级 L1。

## 4. 热度计算与蒸馏

### 4.1 热度公式（时间衰减 + 频次）

```
heat_score = hit_count × decay(now - last_hit_time)
decay(Δt) = 0.5 ^ (Δt / 半衰期)        # 半衰期默认 7 天，可配置
```

- hit_count 体现频率；衰减体现新鲜度——冷门问题不永占 FAQ 坑位。
- 每次命中时惰性更新（无后台定时任务，简单可解释）。

### 4.2 蒸馏三触发（OR）

| 触发 | 条件 | 动作 |
|---|---|---|
| 热度阈值（主，私有/自有共享 KB） | candidate FAQ 的 hit_count ≥ `distill_threshold`（写入时按 KB 归属自动赋值） | 升格 active，LLM 重新蒸馏答案（补全原文 + 相关 chunk 上下文 → 结构化 Q-A） |
| 库主审核（共享 KB 直接提交路径） | `pending_review` FAQ 经库主审核 merge | 升格 active（不依赖阈值，人工闸门） |
| 显式（兜底） | 用户说"记住这个" / 管理端手动标记 | 立即升格（低频但关键的问题） |
| 种子（每次补全） | 检索失败 + 用户补全 | 写 L2 + 种 candidate/pending_review（hit_count=1，**不立即蒸馏**，防污染） |

**阈值跟 KB 归属走（2026-08-19 三轮评审定案）**：阈值的本质决定因素是**该条 candidate 所在 KB 的可见范围（= 污染面）**——

| 候选 FAQ 所在 KB 归属 | `distill_threshold` | 理由 |
|---|---|---|
| 我的私有 KB（含克隆版） | 2（快速沉淀） | 只有我看见，错了只坑自己 |
| 我分享出去的 KB | 3（防污染） | 全员可见，错了全员遭殃 |
| 别人分享给我的 KB（直接提交路径） | 不走阈值，走库主审核 | 库主审核 = 人工门槛，比阈值更可控 |

实现：写入 candidate 时按 KB 归属查 `FAQ_DISTILL_THRESHOLD_PRIVATE`（默认 2）/ `FAQ_DISTILL_THRESHOLD_SHARED`（默认 3），赋给该记录的 `distill_threshold` 字段。共享 KB 直接提交路径写入 `status=pending_review`，不参与阈值升格。配置项仅微调默认数值，无需管理员手动匹配。

核心区分：**记录便宜（每次都做），蒸馏谨慎（热度/审核/显式达标才做）**。

### 4.3 蒸馏的源

FAQ 答案 = LLM 整合「用户补全 + 当时检索到的相关 chunk」，输出结构化 Q-A + 证据引用（doc_id）。禁止直接存原始口语补全。

## 5. 组件落地（挂接现有架构）

| 组件 | 落点 | 说明 |
|---|---|---|
| `EntityEnhancer` | services/enhancers/entity.py（文档 03 架构） | 从 chunk 抽实体+关系，注册进 EnhancerPipeline，KB 级可开关 |
| `save_entity / save_relation / save_faq_candidate` | agent/claw_agent/tools/ 新工具 | 受控写库函数，按 §2.1 矩阵决定写入位置；agent 工具集注册 |
| `clone_kb / submit_faq_pr / approve_faq_pr` | api/kb.py + agent tools | 克隆 KB、提 PR、审核 PR 的显式动作函数 |
| 检索失败检测器 | agent workflow（claw_agent/rag_workflow.py） | 检索结果置信度评估 → 状态机分支；信号由逻辑产生 |
| FAQ 召回 + 二次确认 | api/search.py / retrieval_strategies.py 前置层 | 阈值 + LLM 确认，命中短路 |
| 实体路由 | retrieval_strategies.py 新策略 `graph` | 实体锚点检测 → L2 扩展 → 降级 L1 |
| 前端 | agent.js 补全引导 UI + KB 设置项 + FAQ 管理页 | "帮助 agent 成长"输入入口；FAQ 管理页（候选/正式/PR 队列、手动升格/删除、KB 过滤）；KB 设置页"克隆此 KB"按钮、"提交共享"按钮 |
| 记忆写入/升格/PR 审计 | 文档 07 审计中心 | 每条记忆的写入、升格、PR 提交/合并/拒绝、删除均记入 audit_log——支撑共享模式的可信性 |

## 6. 分阶段实施

**Phase 1（FAQ 闭环，先见效）**：
PG `faq` / `kb_share` / `faq_pr` 表 + Milvus `faq` 集合 + 检索前置 FAQ 召回 + 失败检测 + 补全写回（含克隆/PR 双路径）+ 热度/阈值升格 + 库主审核升格。不依赖 L2，独立可用。

**Phase 2（实体图谱）**：
EntityEnhancer + entities/relations 集合 + graph 检索策略。依赖文档 03 适配器先落地。

Phase 1 是简历上"自进化 RAG"的最小完整故事；Phase 2 叠加"向量库实现 GraphRAG"。

## 7. 参数定案（2026-08-19 三轮评审整版更新）

| 参数 | 定案值 | 说明 |
|---|---|---|
| FAQ 命中阈值 | 0.9 + LLM 确认 | 宁漏勿错 |
| 热度半衰期 | 7 天（可配） | 知识时效 |
| 蒸馏 hit_count 阈值 | **按 KB 归属自动取值**：私有 KB → 2（快速沉淀）/ 自有共享 KB → 3（防污染）；均可配微调 | 阈值跟污染面（KB 可见范围）走，见 §4.2 |
| 共享 KB 直接提交路径 | 不走阈值，走库主审核（`pending_review` → merge） | 人工闸门比阈值更可控 |
| 记忆范围 | **KB 可见性驱动**：记忆条目只带 `kb_id`，无 `scope` 字段；可见性跟 KB 分享关系走 | 已定案，schema 删除 scope 字段 |
| 读取入口 | KB 级检索 → 该 KB；全局检索 → 我可见的所有 KB（私有+分享出去的+别人分享给我的） | "全局"只是检索入口，不是写入位置 |
| 写入路径 | GitHub 式双路径：克隆后写（fork，阈值 2）/ 直接提交（PR，库主审核） | 见 §2.1 |
| 全局入口写入 | 永远写到 `DEFAULT_PERSONAL_KB_ID`（我的私有 KB），UI 可改"我的其他私有 KB" | 全局入口永不直接写共享 KB，避免目标歧义与污染 |
| 克隆性质 | 快照克隆（一次性 copy，不追上游更新） | Phase 1 足够，符合"补全是我个人当时知识"场景 |
| 商业模式影响 | **只调配额（用户数/KB 数），不调机制** | 企业版/个人免费版同套 scope/阈值/PR 机制；个人版也有分享能力 |

## 8. 前后对比

| 维度 | 当前 | 整改后 |
|---|---|---|
| 检索失败 | 静默兜底/幻觉风险 | 一等公民事件，触发补全闭环 |
| 知识增长 | 只能重新上传文档 | 使用中自动积累（L2 图谱 + L3 FAQ） |
| 高频问题 | 每次全链路检索+生成 | FAQ 直返，亚秒级 |
| 多跳关联 | 不支持 | 实体→关系→chunk 扩展 |
| 知识形态 | 仅 chunk/子问题/摘要 | L0-L3 四层蒸馏 |
| 共享协作 | 无 | GitHub 式 fork/PR，私有补全可显式共享 |

## 9. 验证方式

1. **闭环 E2E**：提问一个库中不存在的事实 → agent 走"请补充"分支 → 补全 → 同问法再提问 → FAQ 直返。
2. **蒸馏时机（按 KB 归属）**：私有 KB 内同一问题问 2 次即升格直返；自有共享 KB 内问 2 次仍 candidate、第 3 次升格。
3. **热度衰减**：构造 last_hit_time 为 30 天前的 FAQ，heat_score 显著下降。
4. **KB 可见性隔离**：用户 A 私有 KB 的补全，用户 B 全局检索不可见；用户 A 分享 KB 给 B 后，B 全局检索可见该 KB 的 active FAQ；B 在该共享 KB 检索失败补全 → 走 PR 路径，A merge 前 B 与其他被分享者全局检索都不可见该条。
5. **共享聚合**：两个用户对同一共享 KB 同一问题的补全 → 相似度 ≥0.95 判重合并，hit_count 累加为 2。
6. **克隆路径**：用户 B 克隆 A 的共享 KB → 在克隆版补全 → B 自己的检索命中 → B 显式提 PR → A merge → 原 KB 全员可见。
7. **全局入口写入不污染**：全局检索下补全 → 验证写入 `DEFAULT_PERSONAL_KB_ID`，其他用户全局检索不可见。
8. **PR 审核闭环**：共享 KB 的 `pending_review` FAQ → 库主 merge → active 且 `faq_pr.status=merged`；库主 reject → 不进 active 且 `faq_pr.status=rejected`。
9. **实体扩展**（Phase 2）："A 和 B 什么关系"类问题，验证沿 relations 扩展召回关联 chunk。
10. **不误伤**：FAQ 阈值边界测试——相似但语义不同的问题不得误命中。
11. **审计联动**：补全写入、升格、PR 提交/合并/拒绝、删除在审计中心（文档 07）均有对应记录。

## 10. 风险与备注

- **FAQ 污染**：私有 KB 走阈值 2 自动闸门；自有共享 KB 走阈值 3 自动闸门；别人分享给我的 KB 走库主审核人工闸门。前端 FAQ 管理页提供人工删除/降级。
- **LLM 确认成本**：FAQ 命中多一次短判断调用，可用小参数模型或合并进 prompt，实现时评估。
- **克隆数据一致性**：快照克隆不追上游更新——上游修了错误 FAQ，克隆版仍保留旧版。Phase 1 接受（补全场景下"我个人的知识快照"是合理语义）；若未来出现"上游修正需同步下游"需求，再加"rebase"能力。
- **PR 堆积风险**：共享 KB 库主长期不审核 → `pending_review` 队列堆积。缓解：FAQ 管理页 PR 队列按提交时间排序+提醒；admin 可批量处理；超期未审核的 PR 自动通知库主。
- **商业模式与机制解耦**：企业版/个人免费版共用同一套 scope/阈值/PR 机制，商业模式只影响配额（用户数、KB 数、存储上限），不影响机制本身——避免维护两套逻辑。
- 本文档仅含机制设计；实体/关系抽取 prompt 设计、relation_type 词表、PR 审核 UI 细节在实施阶段细化。
