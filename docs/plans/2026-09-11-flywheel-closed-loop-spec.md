# 数据飞轮闭环 spec（从单向管道到自适应循环）

> 日期：2026-09-11 | 状态：spec（待执行，骨架先行 + `FLYWHEEL_ENABLED` 保持 false）
> 前置：飞轮 Step 1+2+3 已完成代码（`backend/services/data_flywheel.py` + `evaluator.py` + `step1_baseline_run.py`）
> 关联：`2026-09-01-sft-data-export-spec.md`（Step 4，重训路径，与本 spec 调参路径互补不冲突）
> 目标：把飞轮从"定时跑的单向评估管道"升级为"评估→调参→AB 验证→反馈→循环判定"的自适应闭环

---

## 一、为什么是 spec 不是实现

1. **数据量不够**：用户 2026-09-01 拍板飞轮暂不启用（session 量少抽不到有意义数据）。闭环是升级，复杂度更高，**数据没上来前先搭骨架**，`FLYWHEEL_ENABLED` 保持 false，等量够了开零代码改动（与之前定调一致）。
2. **三个缺口未补**：现状是单向管道（提取→GT→评估→建议），缺反馈消费、调整执行、AB 框架三块才能闭环。
3. **设计先行**：闭环涉及 prompt 重构 + contextvar 改造 + 新表，先把边界和异常定清楚再动手，避免返工。

---

## 二、现状基线（已实现到哪）

| 环节 | 代码位置 | 状态 |
|---|---|---|
| Session 增量提取 | `data_flywheel.py:107` `from_all_sessions` | ✓ |
| GT 生成 + 双维度 LLM 自评（覆盖度0-0.5 + 不编造0-0.5） | `data_flywheel.py:55-141` | ✓ |
| ≥0.8 approve / <0.8 pending | 同上 | ✓ |
| RAGAS 评估 | `evaluator.py:283` `evaluate()` | ✓ |
| 归因建议（三类：prompt/检索参数/KB） | `evaluator.py:93` `build_suggested_actions()` | ✓ 只输出文本，不执行 |
| 调度器 + 手动 trigger + 审计 | `data_flywheel.py:208` + `api/evaluation.py:784` | ✓ |
| **显式反馈采集**（点赞点踩） | `agent.py:691-782` `/api/agent/feedback` + `agent.js:458` | ✓ **已实现，双写 Langfuse score + 审计表** |

**关键事实**：项目**已有**完整的点赞点踩闭环——前端 UI（👍/👎 + 点踩评论框 + 取消 + 失败回滚）+ 后端端点（`langfuse.create_score(name="user-feedback", data_type="NUMERIC")` + `audit.log("feedback.like"/"feedback.dislike")`）。**不需要再建反馈表**。

所以现状是"单向管道 + 反馈已采但未被飞轮消费"。三个缺口集中在"消费反馈 + 执行调整 + AB 验证"。

---

## 三、三个缺口与补法

### 缺口 1（P0）：反馈消费通道——飞轮没读 Langfuse score

反馈已写入 Langfuse，但飞轮周期里没有一步去拉这些 score 喂给循环判定。

**补法**：飞轮周期开始时，先用 secret key 调 Langfuse API 拉 `user-feedback` score → 写本地快照表 → 后续循环判定只读本地快照，不依赖 Langfuse 在线。

**为什么不直接实时调 Langfuse**：
- 飞轮跑的时候不卡在 Langfuse 可用性/配额上
- Langfuse score 是"信号源 + 可视化"，但数据不在自己 PG 里，做循环判定要保证外部依赖降级时仍能跑

**新表**：`flywheel_feedback_snapshot`
```
id | cycle_id | trace_id | value(0/1) | comment | message_index | session_id | user_id | collected_at
```
字段对齐 `agent.py:770-773` 审计 detail，方便 join。

**降级**：Langfuse 不可用 → 快照为空 → 该周期循环判定退化为"仅看 RAGAS 指标 + 审计表 feedback.like/dislike"，不阻塞。

### 缺口 2（P1）：调整执行层——建议只输出文本不执行

`build_suggested_actions()` 输出 `"改 generate_response prompt"` / `"调大 top_k"` 这种文本，没有执行层。

**补法**：按调整类型分三层执行（见 §四边界决策）。

### 缺口 3（P2）：AB 框架——无 config 版本 + 无分流

`runtime_config` 是全局单实例，所有请求读同一份配置。要做 AB 需 config 快照 + 请求级分流 + 显著性检验 + 回滚。

**补法**：数据驱动查表 + contextvar 贴标签 + HTTP 中间件分流（见 §六）。

---

## 四、调整边界决策（核心，spec 的灵魂）

不同类型的调整，自动化程度和风险不同。**这是 spec 最重要的一节**。

| 调整类型 | 例子 | Agent 自动执行？ | 原因 |
|---|---|---|---|
| **标量参数** | `RETRIEVAL_TOP_K`/`RETRIEVAL_MIN_SCORE`/`LLM_TEMPERATURE_ANSWER`/`RRF_K`/`NUM_SUBQUESTIONS`/`MILVUS_NPROBE` | ✓ 全自动 | 改值不涉及代码，`runtime_config` apply 钩子热生效（`runtime_config.py:574` `_APPLY_HANDLERS`） |
| **prompt 类** | `generate_response` system prompt / `query_expansion` prompt | ✗ 半自动（人工改 + Agent 给建议） | ① 改 prompt = 改代码（f-string 拼接，变量名耦合，见 §五）② reward hacking 风险高 |
| **KB 内容** | `context_precision` 低 → 补文档 | ✗ 半自动 | 要爬取/上传文档，不是改配置 |

### 4.1 为什么 prompt 类必须人工把关（reward hacking 防护）

**reward hacking = 自我强化**：如果让 Agent 自己改 prompt，LLM 容易为了 faithfulness 指标好看，把"仅基于上下文答题"的约束悄悄放松或删掉，幻觉反而变多但指标虚高。这是 reward hacking 的一种，比调 `top_k` 危险得多。

**防护**：prompt 类走"Agent 出建议、人工确认"半自动。Agent 可以分析低分样本 + 给修改建议，但执行权在人工。spec 里明确：**只有标量参数类放权给 Agent 自动执行**。

### 4.2 Agent 自动调参的边界约束

即便标量参数允许 Agent 自动调，也要：
- **安全边界**：Agent 提议的值必须在 `WRITABLE_CONFIGS` 的 `min/max` 范围内（`runtime_config.py:38` 已有元信息），超界拒绝
- **变更审计**：每次 Agent 自动调参落审计 `config.auto_change`（key/old_value/new_value/reason/cycle_id）
- **回滚机制**：candidate 实验若 AB 验证反馈变差，回滚到 baseline 快照（见 §六）

---

## 五、prompt 三层架构（缺口 2 的 prompt 部分）

### 5.1 现状：f-string 拼接，散落多处，非模板系统

项目**没用** LangChain `ChatPromptTemplate`，所谓"占位符"是 f-string 局部变量名：

**位置1**：`rag_workflow.py:416-436` 回答生成
```python
system_prompt = "你是一个专业的 RAG 知识库助手，请基于以下检索到的文档内容回答用户问题。\n\n"
...
user_message = f"""请基于以下检索到的文档回答问题。

## 检索到的相关文档
{context_text}

## 用户问题
{query}

请直接回答用户问题，引用来源，如果文档中没有相关信息请明确说明。"""
```

**位置2**：`rag_workflow.py:527-535` greeting 分支

**位置3**：`rag_tools.py:348-360` 查询扩展
```python
prompt = f"""你是一个信息检索专家。请将用户的查询扩展为 {num_subquestions} 个更具体的子问题，
...
原始查询：{query}
...
只返回 JSON，不要包含其他文字。"""
```

还有 `enhancers/`（sub_question/summary 生成器）+ `advanced/`（entity_extractor/task_planner/intent_classifier）各自有 prompt。

### 5.2 关键澄清：调整对象 = system message

人机对话内容（`{query}`/`{context_text}`）是运行时数据（数据库查的/用户输入的），**不参与版本化**。调整对象只是 **system message 文案**（角色设定 + 行为约束）。

**重构动作**：把 `user_message` 里的固定文案（如"请直接回答用户问题，引用来源..."）**收编进 system_prompt**，让 human message 只剩 `{query}` + `{context_text}` 纯数据。这样模板外置只存 system_prompt 一个字段，最干净。

### 5.3 三层架构

| 层 | 存什么 | 例子 |
|---|---|---|
| 模板存储 | DB 表 `prompt_templates(name, version, system_tpl, variables_schema, status, updated_by)` | `generate_response` v1 |
| 渲染器 | 运行时按 name+version 取模板，用 `.format(**vars)` 或 LangChain `PromptTemplate` 插值 | 替换现在 f-string |
| 调用点 | `rag_workflow.py` / `rag_tools.py` / `enhancers` 各处改成"取模板→插值→构造 SystemMessage" | 6+ 处调用点 |

**variables_schema 的作用**：模板声明需要哪些变量（`["context_text", "query"]`），调用处必须提供这些变量，否则插值 `KeyError`。模板新增变量（如 `{user_role}`）→ 调用处要跟着提供 → **这就是 prompt 类永远半自动的根因**（改 prompt 必改调用处代码，哪怕模板外置）。

### 5.4 prompt 版本化与 AB 接入

- 模板按 `name + version` 存，`status` 字段标 `active`/`experiment`
- AB 时 baseline 用 `generate_response v1`，candidate 用 `v2`，通过 experiment_overrides 路由（见 §六）
- 回滚 = 把 `v2` status 改回 `draft`，`v1` 保持 `active`

---

## 六、AB 框架：数据驱动查表 + contextvar（缺口 3）

### 6.1 核心设计：三角色分工（节目单/前台/对讲机）

**不要用 `if exp == "candidate"` 硬编码分支**（违反开闭原则，每加一组改一次 get_runtime）。用数据驱动查表：

```python
import contextvars

# 当前请求所属实验组（默认 baseline）
_current_experiment = contextvars.ContextVar("experiment", default="baseline")

# 各实验组的配置覆盖（数据驱动，存 DB 表 experiment_configs）
_experiment_overrides: dict[str, dict] = {
    "baseline":  {},                                                    # 空 = 全用默认
    "candidate": {"RETRIEVAL_TOP_K": 20, "LLM_TEMPERATURE_ANSWER": 0.3,
                   "prompt_templates.generate_response": "v2"},        # 连 prompt 版本一起路由
    # 加新组只往这里加一条，不动 get_runtime 代码（开闭原则）
}

def get_runtime(key: str, default=None):
    # 1. 特殊 key 分支（保留原样，config.py:178-186）
    if key == "LITELLM_API_KEY" and key not in _runtime_overrides:
        ...  # 原逻辑
    # 2. experiment 组覆盖（新增，查表，零 if）
    exp = _current_experiment.get()
    exp_kv = _experiment_overrides.get(exp, {})
    if key in exp_kv:
        return exp_kv[key]
    # 3. 运行时覆盖（原有，config.py:187-188）
    if key in _runtime_overrides:
        return _runtime_overrides[key]
    # 4. settings 静态默认（原有，config.py:189）
    return getattr(settings, key, default)
```

**这是策略模式的轻量形态**：策略模式本质 = "封装可变算法 + 按 key 选实现"。当策略 = 取固定值时，dict 查表就是最简形态，零 if。

**三角色分工**：

| 角色 | 代码位置 | 干啥 | 类比 |
|---|---|---|---|
| `experiment_overrides` 字典 | DB 表 | 存"各组的配置覆盖值" | 节目单 |
| HTTP 中间件 | 1 个 middleware | 分流决策 + 贴标签 | 前台发对讲机 |
| `get_runtime` | 1 个函数 | 按当前标签查节目单念 | 对讲机按频道念 |

### 6.2 HTTP 中间件（就干一件事：分流 + 贴标签）

```python
@app.middleware("http")
async def ab_middleware(request, call_next):
    user_id = get_user_from_request(request)        # 从 JWT 取
    traffic_split = read_split_from_db()             # 比如 20（candidate 占 20%）
    # 分流：同一用户始终同组（避免体验跳变）
    group = "candidate" if hash(user_id) % 100 < traffic_split else "baseline"
    token = _current_experiment.set(group)           # 贴标签
    try:
        return await call_next(request)              # 放行，业务代码该干嘛干嘛
    finally:
        _current_experiment.reset(token)            # 请求结束撕标签，防泄漏
```

**中间件不念节目单，不并发跑两条，不获取多个内容**。它只做分流决策（需要 user_id，只有 HTTP 层拿得到），把决策结果塞 contextvar，业务代码（reranker/retrieval/agent）通过 `get_runtime(...)` 读到对应组的值。

**为什么分流放 HTTP 层不放 get_runtime 里**：分流需要 user_id（从 JWT），而 `get_runtime` 被业务代码调，业务层拿不到 user_id。分层：HTTP 层分流（有 user_id）→ contextvar 传标签 → 业务层 get_runtime 按标签取值。

### 6.3 侵入性收敛

| 侵入点 | 数量 | 改动 |
|---|---|---|
| `get_runtime` 函数体 | 1 处 | 加 3 行查表 |
| HTTP 中间件 | 1 处 | 新增 middleware |
| `experiment_configs` 表 | 1 张 | 新增 |
| 调用点代码（reranker/agent/...） | **0 处** | 不动 |

### 6.4 什么时候升级到真策略类

只有当某组取值是**逻辑不同**（不是固定值）时才写策略类。例如某组要求"top_k 按 query 长度动态算"：

```python
class DynamicTopKStrategy:
    def get(self, key, ctx):
        if key == "RETRIEVAL_TOP_K":
            return 10 if len(ctx["query"]) < 20 else 20
        return None
```

当前所有 AB 都是"值不同"，查表够。spec 留扩展点：`_experiment_overrides` 的值既可以是 dict 也可以是策略对象，加个 `isinstance` 判断即可。**不要过度设计写策略类**。

---

## 七、飞轮跑 candidate 评估的触发

飞轮后台任务默认走 baseline（`asyncio.create_task` 不传播 contextvar，见 §八异常1）。AB 验证时需要"让飞轮在 candidate 配置下跑一次评估"。

### 7.1 两种触发方式

| 方式 | 用途 | 触发 |
|---|---|---|
| 手动 `?experiment=candidate` | 调试/快速验证 candidate 效果 | `POST /api/evaluation/flywheel/trigger?experiment=candidate` |
| 自动（experiment 状态驱动） | 正式 AB 验证 | experiment_configs 表有 `status=running` 的候选时，飞轮周期自动双跑（baseline + candidate）对比出报告 |

### 7.2 后端改动（就这一处）

扩展 `api/evaluation.py:784` 的 trigger 接口：

```python
@router.post("/flywheel/trigger")
async def flywheel_trigger(experiment: str = "baseline", ...):
    async def _bg_task():
        # 关键：用 copy_context 显式设标签包住整个飞轮周期
        ctx = contextvars.copy_context()
        def _run_under():
            _current_experiment.set(experiment)
            return run_flywheel_cycle(triggered_by=f"manual:{user}({experiment})")
        summary = await ctx.run(_run_under)
        ...
```

**为什么必须 `copy_context().run()`**：`asyncio.create_task` 默认不拷贝 contextvar，直接 `_current_experiment.set("candidate")` 设的是当前任务上下文，飞轮周期跑在新 task 里读不到。`copy_context()` 复制一份，在新上下文里 set，包住整个 `run_flywheel_cycle`，周期里所有 `get_runtime` 调用（包括 fill_dataset 那次 Agent 调用）都读到 candidate 值。

### 7.3 自动模式（状态驱动）

experiment_configs 表加 `status` 字段（`draft`/`running`/`completed`/`rolled_back`）。飞轮周期开始时（`data_flywheel.py:87` `run_flywheel_cycle`）先查有没有 `running` 的候选：
- 有 → 跑两次评估（baseline context + candidate context），对比出 AB 报告
- 没有 → 只跑 baseline（现状）

这样 AB 验证是"实验状态驱动"——在表里把某 candidate 标成 running，下次飞轮自动对比，不用每次手动调。

---

## 八、边界异常附录（spec 必须覆盖）

### 异常1：asyncio 不传播 contextvar（最易踩坑）

`asyncio.create_task` **默认不拷贝** contextvar。意味着：
- 飞轮后台任务（`api/evaluation.py:817`）里 `_current_experiment.get()` 拿到 default `"baseline"`，不继承触发请求的 experiment 标签
- FastAPI `BackgroundTasks` 同理

**对飞轮日常运行是对的**（飞轮跑评估不分在线流量，默认 baseline 合理）。但 AB 评估时要"模拟 candidate 跑"，必须显式 `copy_context().run()` 包住（见 §七7.2）。

**spec 铁律**：所有后台任务若需要 AB 上下文，必须 `contextvars.copy_context().run(...)`，不能依赖 task 自动继承。否则会出现"明明设了 candidate，评估却跑 baseline 配置"的幽灵 bug，排查极难。

### 异常2：AB-eligible 白名单

候选 config 若触发组件重建（如改 `RERANKER_TYPE` 要重建 reranker 实例，单进程内两套实例共存吃内存），**不应纳入 AB**。

**AB-eligible 白名单**（只限标量参数）：
- `RETRIEVAL_TOP_K` / `RETRIEVAL_MIN_SCORE` / `RRF_K` / `NUM_SUBQUESTIONS`
- `LLM_TEMPERATURE_ANSWER` / `LLM_TEMPERATURE_GREETING` / `LLM_TEMPERATURE_DEFAULT`
- `MILVUS_NPROBE`
- `RERANK_MAX_CONCURRENCY` / `RERANK_TORCH_THREADS`（rerank 池可热重建，但谨慎）
- `prompt_templates.*`（版本路由，不重建组件）

**AB-ineligible 黑名单**（需重建组件，走灰度发布多实例，不在飞轮 AB 范畴）：
- `RERANKER_TYPE` / `DEFAULT_MODEL` / `EMBEDDING_MODEL` / `LITELLM_BASE_URL`
- `SEARCH_BACKEND` / `MILVUS_*` / `STORAGE_TYPE`

spec 校验：experiment_configs 写入时检查 key 是否在白名单，不在则拒绝并提示"该参数需走灰度发布"。

### 异常3：分流稳定性

同一 user_id 始终走同一组（避免体验跳变、避免同用户前后对比污染）→ 用 `hash(user_id) % 100 < traffic_split`。不要用随机数（每次请求不同组）。

### 异常4：fail-back

candidate config 跑崩（异常率超阈值，如 >5%）→ 自动回退该请求走 baseline，并标记 experiment 为 `degraded`。连续 N 个周期 degraded → 自动 `rolled_back`，告警人工介入。

### 异常5：样本量与显著性

现在 `/run` 有 30 条门控（`evaluation.py:234`），AB 需更严格。按效应量 + 显著性水平 + 功效算两组各需多少样本：

- α = 0.05（显著性水平）
- power = 0.8（功效）
- effect_size = 期望提升幅度（如 faithfulness +0.05）

用 statsmodels 的 `proportion_effectsize` + `NormalIndPower` 算样本量，spec 给默认值（如 effect=0.05 → 每组约 600 样本）。**不能拍脑袋**。

### 异常6：contextvar 泄漏防护

中间件 `finally: _current_experiment.reset(token)` 必须执行，否则标签泄漏到下个请求（复用连接池时）。spec 铁律：所有 set 必须配 reset，try/finally 包住。

### 异常7：Langfuse 不可用降级

飞轮周期拉 Langfuse score 失败（服务 down/配额超）→ 快照为空 → 循环判定退化为"仅看 RAGAS 指标 + 审计表 feedback.like/dislike"，不阻塞。spec 给降级日志 + 告警。

### 异常8：reward hacking 检测

Agent 自动调参后，若 faithfulness 上升但 answer_relevancy 下降（或 faithfulness 上升但点踩率上升），疑似 reward hacking → 标记 experiment 为 `suspicious`，强制人工复核。spec 给检测规则：`faithfulness Δ > 0` 且 `(answer_relevancy Δ < -0.05 或 feedback_dislike_rate Δ > 0.05)` → 触发告警。

### 异常9：调试标签

引入 contextvar 后，`get_runtime` 同一函数不同请求不同结果是隐式行为。**spec 铁律**：所有相关日志必须打 `[exp={_current_experiment.get()}]` 前缀，否则排查时会懵（"明明配置改了，怎么没生效"——其实是请求走了 baseline 频道）。

---

## 九、推进顺序与"暂时不启用"的兼容

```
P0 反馈消费通道（Langfuse score snapshot 表 + 飞轮周期拉取逻辑）
   ↓ 没这个，循环判定无依据
P1 调整执行层（标量参数：suggestion→set_runtime+apply_config_change 映射）
   + prompt 三层架构（§五，含 user_message 固定文案收编进 system_prompt 重构）
   ↓ 没这个，步骤 a 是空壳
P2 AB 框架（experiment_configs 表 + contextvar + HTTP 中间件 + 显著性检验 + 回滚）
   ↓ 没这个，灰度无从谈起
闭环判定逻辑（反馈聚合 → 好坏判定 → 进/退）
   ↓ 没这个，飞轮不自循环
```

四步里 **P0 是真正前置依赖**，P1/P2 可并行搭骨架但都依赖 P0 信号。

### 与"暂时不启用"的兼容

- 所有新代码默认不生效（`FLYWHEEL_ENABLED=false` 时调度器不启动，见 `data_flywheel.py:216`）
- AB 中间件加开关 `AB_ENABLED=false` 时跳过分流，所有请求走 baseline（零开销）
- 骨架先到位，开启时改 env 即可，**代码不用动**（与 2026-09-01 定调一致）

---

## 十、与 SFT Step 4 的关系（不冲突，层级不同）

- **本 spec**：调参路径——AB 验证的是"调参效果"（top_k/温度/prompt 版本）
- **SFT Step 4**（`2026-09-01-sft-data-export-spec.md`）：重训路径——验证的是"微调轻量组件"效果（query 改写器/reranker/意图分类器）

两者不冲突但层级不同：**AB 验证调参，SFT 验证重训**。不要混在一个实验里（调参 + 重训同时变，无法归因）。spec 铁律：一个 experiment 只改一类变量。

---

## 十一、验收口径（对齐用户验收原则）

每部分看四个"真实"：
1. **真实提高性能**：AB 验证 candidate 比 baseline 真实提升（RAGAS 指标 + 点踩率双升），未达标 → 暂停、带数据找用户，不硬凑数字
2. **真实优化架构**：三角色分工 + 查表零 if + contextvar 最小侵入，不是堆 if 分支
3. **真实可拓展**：加新实验组 = 往表里加一行（开闭原则），不动 get_runtime
4. **真实合理**：prompt 类人工把关防 reward hacking、AB-eligible 白名单防内存爆炸、显著性检验防假阳性

未达标 → 暂停，不擅自绕过或降级目标。
