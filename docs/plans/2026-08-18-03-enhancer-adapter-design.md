# 设计文档 03：增强生成适配器（Enhancer Adapter）

> 状态：待审阅 | 日期：2026-08-18
> 关联：与文档 02 共用「接口 + 注册表」模式；是文档 06（自进化 RAG）中 EntityEnhancer 的挂载点；配置粒度「全局默认 + 知识库覆盖」

## 1. 现状诊断

增强生成在 `backend/services/document_processor.py`：

- `gen_chain`（document_processor.py:82-90）：**一个 prompt 同时生成 3-5 个子问题 + 摘要**，返回 `{'subqs': [...], 'summary': '...'}`。
- **每条 chunk 一次 LLM 调用，无任何开关**——只想要摘要也得付子问题的 token。
- 增量模式：`/api/process/generate/{file_id}`（api/processing.py:155）先查 PG，只对缺失的 chunk 调 LLM（document_processor.py:252-292）。
- 存储关联：PG 为权威源（`save_chunk_enhanced_data_batch`，document_processor.py:379-389）；Milvus 三集合 `chunk_summaries` / `chunk_subquestions` / `chunk_vectors`（milvus_client.py:114-219）；BM25/ES 只索引原文。

问题：
1. 子问题与摘要**耦合在一个 prompt**，无法单独启用/禁用。
2. 新增增强类型（关键词、HyDE 假设性问题、实体抽取……）无处安放。
3. 检索侧假设子问题/摘要恒存在，关闭任一会导致空集合被无效检索。

## 2. 目标

1. 每种增强是一个可插拔 Enhancer，可按知识库选择性启用（如只开摘要、全关走纯原文 RAG）。
2. 新增增强类型 = 新文件 + 注册一行（为文档 06 的 EntityEnhancer 铺路）。
3. 存储/检索侧按启用情况优雅降级（未启用的增强不产生空检索分支）。
4. 现有「子问题+摘要全开」行为作为默认配置，回归零风险。

## 3. 设计

### 3.1 目录结构与接口

```
backend/services/enhancers/
├── __init__.py
├── base.py           # Enhancer 抽象基类 + EnhanceResult
├── sub_question.py   # SubQuestionEnhancer（现有 prompt 的子问题部分拆出）
├── summary.py        # SummaryEnhancer（摘要部分拆出）
└── pipeline.py       # EnhancerPipeline：按启用列表组合执行 + 并发调度
```

**base.py**：

```python
@dataclass
class EnhanceResult:
    chunk_id: int | None      # 入库前为 None，由 pipeline 回填
    chunk_text: str
    sub_questions: list[str] | None = None
    summary: str | None = None
    # 扩展字段（文档 06：entities/relations）通过 extras 透传
    extras: dict = field(default_factory=dict)

class Enhancer(ABC):
    name: str                       # "sub_question" / "summary" / ...
    output_fields: tuple[str, ...]  # 该 enhancer 填充 EnhanceResult 的哪些字段

    @abstractmethod
    async def enhance_batch(self, chunks: list[str]) -> list[dict]:
        """对一批 chunk 文本生成增强内容，返回 {field: value} 列表，与输入对齐。"""
```

enhance_batch 内部沿用现有两级并发（Semaphore + gather / abatch），**并发参数从 `get_runtime()` 热读**（修掉 document_processor.py:518 的硬编码，与文档 04 协同）。

### 3.2 组合执行策略（token 成本优化点）

现状「一次调用同时产出子问题+摘要」其实比「两次独立调用」省 token（输入文本只传一次）。拆成两个 Enhancer 后若简单并行，输入 token 翻倍。因此 pipeline 支持**组合执行**：

```python
class EnhancerPipeline:
    def __init__(self, enhancer_names: list[str]):
        self.enhancers = [get_enhancer(n) for n in enhancer_names]

    async def run(self, chunks: list[Chunk]) -> list[EnhanceResult]:
        # 同开 sub_question+summary 时，走合并 prompt（一次调用出两者）
        # 只开其一时，走各自的独立 prompt
        # 未来 EntityEnhancer 独立 prompt，与前两者并行 gather
```

- `sub_question + summary` 同开 → 复用现有合并 prompt（**默认路径，行为与现状一致**）。
- 只开其一 → 各自的精简 prompt。
- 实现方式：`CombinedEnhancer`（内部持有合并 prompt，声明 `output_fields=("sub_questions","summary")`），pipeline 按启用集合选择 combined 或独立 enhancer。

### 3.3 启用配置解析（三级，与文档 02 同构）

```
ENABLED_ENHANCERS 全局配置（默认 "sub_question,summary"）
  ← KB 表 enhancers JSONB 列覆盖（文档 02 已加迁移）
  ← API 请求级覆盖（pipeline 页可选）
解析结果：set[str]，如 {"sub_question", "summary"}
```

### 3.4 存储与检索侧适配

**写入侧**（milvus_client.py `import_data`，226-371）：

- `chunk_summaries`：仅当 result.summary 非 None 时写入（现有 264 行已有此判断，保留）。
- `chunk_subquestions`：仅当 sub_questions 非空时写入。
- 新增：PG 侧 `document_chunk` 或元数据记录该 chunk 已启用过哪些 enhancer（`enhanced_with JSONB`），供增量模式判断「缺失」时**按当前启用集而非全量字段**判断。

**增量模式改造——补生成显性化**（document_processor.py:252-292）：

判断「缺失 sub_questions/summary」改为「缺失**当前启用集中**的字段」。全关时 generate 阶段直接跳过（秒回）。

**关键原则（2026-08-19 用户评审补充）：绝不隐性补生成**。启用集变更（如先只开摘要、后改双开）导致的存量缺口，不在正常处理流程中自动补齐，而是由用户通过显式操作触发——既不拖累正常进度，也保证补生成动作可感知、可审计：

- 缺口检测与补生成拆为两个动作：
  - `GET /api/process/generate/{file_id}/missing`：轻量检测接口，只读 PG 统计「哪些 chunk 缺当前启用集中的哪些字段」，**不触发任何 LLM/embedding 调用**。
  - `POST /api/process/generate/{file_id}`：接收 `only_missing: bool`，显式补生成缺失字段（已有字段不重复生成、不重复计费）。
- 正常 pipeline 流程（新文档处理）永远只按当前启用集一次性生成，不做任何存量回补。

**检索侧降级**（retrieval_strategies.py / agent 检索路径）：

- 按 KB 的 enhancers 配置决定检索分支：KB 未启用 summary → 不查 `chunk_summaries` 集合；未启用 sub_question → 不查 `chunk_subquestions`。
- 全关 → 纯 `chunk_vectors` 原文检索（Native 策略），自动成立。
- RRF 融合权重在无某分支时自动归一（现有逻辑若假设三分支恒在，需补缺失分支的短路）。

### 3.5 前端

- 建库/编辑弹窗：增强选项多选框（子问题 / 摘要 / 后续：实体抽取）。
- pipeline 页 Step 3：按启用集展示进度项（只开摘要时只显示摘要进度）。
- **补生成显性入口**（用户评审补充）：Step 3 完成后调用缺口检测接口，若存在「启用集 > 已生成集」的存量缺口，显示黄色提示条（如「检测到 N 个 chunk 缺失子问题增强」）+「补生成缺失增强」按钮——用户显式点击才执行，正常流程不被拖累。
- 设置页「文档处理」组：`ENABLED_ENHANCERS` 全局默认多选。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `backend/services/enhancers/*` | 新建 4 个模块；从 document_processor 迁移 prompt 与解析逻辑 |
| `backend/services/document_processor.py` | 生成逻辑委托 EnhancerPipeline；增量判断按启用集 |
| `backend/services/milvus_client.py` | `import_data` 按 EnhanceResult 字段存在性写入（微调） |
| `backend/services/retrieval_strategies.py` | 检索分支按 KB enhancers 配置短路 |
| `backend/services/database.py` | chunk 增强状态记录（`enhanced_with` 或复用现有查询按启用集过滤） |
| `backend/api/processing.py` | generate 接口接收/解析启用集 |
| `backend/api/knowledge_bases.py` | enhancers 字段 CRUD |
| `backend/services/runtime_config.py` | `ENABLED_ENHANCERS` 入白名单 |
| `frontend/js/pages/knowledge-bases.js` / `pipeline.js` / `settings.js` | 多选 UI + 进度展示适配 |

## 5. 前后对比

| 维度 | 当前 | 整改后 |
|---|---|---|
| 增强项 | 子问题+摘要强制全开 | 按 KB 任意组合，可全关 |
| token 成本 | 每 chunk 必付两者 | 按需；同开时合并 prompt 不增加成本 |
| 新增增强类型 | 改 gen_chain prompt + 存储 + 检索多处 | 新 Enhancer 文件 + 注册 |
| 检索鲁棒性 | 假设三分支恒在 | 按启用集短路，支持纯原文 RAG |
| 并发参数 | 硬编码 16/8 | get_runtime 热读（协同文档 04） |

## 6. 验证方式

1. **回归**：默认配置（双开）处理同一文档，子问题/摘要数量与结构与整改前一致。
2. **只开摘要**：处理新文档 → Milvus `chunk_subquestions` 无新增、`chunk_summaries` 有新增；检索该 KB 走 summary+native 两分支。
3. **全关**：generate 阶段秒回零 LLM 调用；检索走纯 native。
4. **显性补生成**：先只开摘要处理，后改为双开 → 正常流程不自动补；缺口检测接口返回子问题缺口统计；显式点击「补生成」→ 仅生成子问题，摘要不重复生成（token 不重复计费）。
5. **降级**：KB 无子问题数据时检索不报错、无空分支拖低 RRF 分数。
6. **质量对照实验**：见第 7 节，组合执行策略切换的准入门槛，必须通过。

## 7. 质量对照实验（2026-08-19 用户评审补充：组合执行策略切换的准入门槛）

**背景**：CombinedEnhancer 一次调用产出子问题+摘要，必须用对照实验证明迁移后质量无回退；单开路径的新精简 prompt 也需证明不劣于合并 prompt 的对应部分。**实验通过是切换默认路径的硬性准入条件。**

**三组对照设计**：

| 组 | 生成方式 | 目的 |
|---|---|---|
| A（基线） | 现状 `gen_chain` 合并 prompt（整改前代码产出） | 对照基准 |
| B | CombinedEnhancer（合并 prompt 原样迁移） | 验证迁移无事故，预期与 A 一致 |
| C | 拆分后的独立精简 prompt（单开路径将采用） | 验证新 prompt 质量不劣化 |

- **基准集**：从已处理文档抽取 3-5 个文档、50-100 个 chunk（覆盖长/短 chunk、中英文、代码块），固定随机种子保证可复现。
- **指标**：
  1. 结构指标：子问题数量分布（均值/方差/越界率 vs 3-5 个约束）、摘要长度分布、JSON 解析成功率；
  2. 质量抽评：每组抽 20 条，LLM-as-judge 打分（1-5 分）：子问题与 chunk 相关性、摘要忠实度（无幻觉）；三组同题对比；
  3. 人工复判：用户复判 LLM 打分可疑的样本（预期 ≤5 条）。
- **通过标准**：B vs A 结构指标一致且打分差 ≤0.3（防迁移事故）；C vs A 允许风格差异但平均分不低于 A − 0.3（不劣化）。
- **未通过的回退方案**：C 组 prompt 迭代重试；或单开路径也复用合并 prompt、只取所需字段（多花输出 token 但保质量）。
- **产出**：实验报告（数据表 + 结论）存 `docs/plans/`，作为切换准入证据与简历量化素材（「A/B/C 对照实验保证架构重构质量零回退」）。

## 8. 风险与备注

- **合并 prompt 的解析**：OutputFixingParser 现有对 `{'subqs','summary'}` 的容错逻辑需原样迁入 CombinedEnhancer，防止回归。
- **历史数据**：已处理的 chunk 视为「双开已增强」，`enhanced_with` 回填脚本可选（scripts/ 下加一次性迁移）。
- **EntityEnhancer（文档 06）**落地时直接注册进本架构，无需再改 pipeline。
- 补生成缺口检测接口必须保持轻量（纯 PG 查询），禁止在检测路径触发任何 embedding/LLM 调用。
