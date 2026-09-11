# 设计文档 02：切割策略适配器（Chunking Strategy Adapter）

> 状态：待审阅 | 日期：2026-08-18
> 关联：与文档 03（增强生成适配器）共用同一套「接口 + 注册表」模式；配置粒度遵循用户决策「全局默认 + 知识库覆盖」

## 1. 现状诊断

切割逻辑在 `backend/services/document_processor.py:92-165` `DocumentProcessor.split_document()`：

```python
# document_processor.py:98-101 —— 策略选择由文档内容隐式决定，用户无法选择
has1 = bool(re.match(r"^#\s+", markdown_content, re.MULTILINE))
has2 = bool(re.match(r"^##\s+", markdown_content, re.MULTILINE))
if has1 and has2:
    # MarkdownHeaderTextSplitter 按 #/## 切 + 超长二次切割 + 过短合并（101-151 行）
else:
    # RecursiveCharacterTextSplitter(separators=["\n\n","\n"], 400/50)（152-159 行）
```

问题：
1. **无策略抽象**——单方法 if/else，新增策略必须改这个方法。
2. **无选择权**——策略由内容自动探测，用户/知识库无法指定。
3. **阈值散落**——`MAX_CHUNK_SIZE`/`MIN_CHUNK_SIZE`/`CHUNK_SIZE`/`CHUNK_OVERLAP` 通过 `get_runtime()` 热读（110-118 行），但语义切割等新策略的参数无处安放。

## 2. 目标

1. 切割策略可插拔：新增策略 = 新增一个文件 + 注册一行。
2. 三级策略解析：**请求参数 > 知识库配置 > 全局默认（auto）**。
3. 现有行为完全保留为 `auto` 策略（默认），回归零风险。
4. 为后续语义切割等新策略预留扩展位。

## 3. 设计

### 3.1 目录结构与接口

```
backend/services/chunking/
├── __init__.py       # 导出 registry 与公共类型
├── base.py           # Chunk 数据类 + ChunkStrategy 抽象基类
├── markdown.py       # MarkdownHeaderStrategy（迁移现有 101-151 行逻辑）
├── recursive.py      # RecursiveStrategy（迁移现有 152-159 行逻辑）
├── auto.py           # AutoStrategy（内容探测 → 委托 markdown/recursive，= 现有默认行为）
└── registry.py       # 注册表 + get_strategy(name)
```

**base.py**：

```python
@dataclass
class Chunk:
    text: str
    metadata: dict  # 保留标题层级等切割附加信息（现有 markdown 切割的 header metadata）

class ChunkStrategy(ABC):
    name: str  # 注册名，如 "markdown" / "recursive" / "auto"

    @abstractmethod
    def split(self, text: str, params: ChunkParams) -> list[Chunk]: ...

    def default_params(self) -> dict:
        """声明该策略可暴露到设置页/KB 配置的参数及默认值"""
        return {}
```

`ChunkParams`：从「KB 覆盖 → 全局 runtime 配置」合并后的参数包（chunk_size、overlap、min/max 等），由调用方组装，策略只消费不读取全局态——**策略无外部依赖，可单测**。

### 3.2 注册表

```python
# registry.py
_STRATEGIES: dict[str, type[ChunkStrategy]] = {}

def register(cls): _STRATEGIES[cls.name] = cls; return cls

def get_strategy(name: str | None) -> ChunkStrategy:
    return _STRATEGIES.get(name or "auto", _STRATEGIES["auto"])()

def list_strategies() -> list[dict]:  # 供设置页/前端展示可选策略
    return [{"name": c.name, "params": c.default_params()} for c in _STRATEGIES.values()]
```

启动时在 `chunking/__init__.py` import 各策略模块触发 `@register`，与现有 agent registry（registry.py:788-832）风格一致。

### 3.3 策略解析链（三级）

```
split 请求进入（api/processing.py）
  └─ resolve_chunk_strategy(kb_id, request_override) 
       1. request_override（API 显式传 strategy=xx，pipeline 页可选）
       2. KB 表 chunk_strategy 字段（建库/编辑时设置）
       3. 全局配置 CHUNK_STRATEGY（默认 "auto"）
```

### 3.4 存储与配置改动

**KB 表**（database.py knowledge_base 相关表）新增列：

```sql
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS chunk_strategy VARCHAR(32) DEFAULT NULL;
ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS enhancers JSONB DEFAULT NULL;  -- 文档03使用，本次一并迁移
```

`NULL` = 跟随全局。

**全局配置**（config.py + runtime_config.py `WRITABLE_CONFIGS`）：

| 配置 | 默认 | 说明 |
|---|---|---|
| `CHUNK_STRATEGY` | `auto` | enum：auto / markdown / recursive（后续扩展 semantic） |

**API**：`knowledge_bases.py` 建库/更新接口接收 `chunk_strategy`；`processing.py` split 接口接收可选 `strategy` 覆盖参数；settings GET 返回 `list_strategies()` 供前端渲染下拉。

### 3.5 迁移映射（行为保持）

| 现有分支 | 迁移到 |
|---|---|
| document_processor.py:101-151（markdown 切割+后处理） | `MarkdownHeaderStrategy.split()`，阈值从 params 读 |
| document_processor.py:152-159（递归切割） | `RecursiveStrategy.split()` |
| document_processor.py:98-101（has1/has2 探测） | `AutoStrategy.split()`：探测后委托上述两者 |

`DocumentProcessor.split_document()` 改为：

```python
def split_document(self, content: str, strategy: str | None = None, **kb_params) -> list[Chunk]:
    s = get_strategy(strategy)          # None 时由调用方已解析好，或回落 auto
    return s.split(content, self._build_params(kb_params))
```

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `backend/services/chunking/*` | 新建 5 个模块（约 200 行，含从 document_processor 迁移的逻辑） |
| `backend/services/document_processor.py` | `split_document()` 瘦身为策略委托；删除内联 if/else |
| `backend/services/database.py` | KB 表加 2 列迁移 + CRUD 支持 |
| `backend/api/knowledge_bases.py` | 建库/更新接收 chunk_strategy |
| `backend/api/processing.py` | split 接口接收 strategy 覆盖 + 从 KB 解析默认 |
| `backend/services/runtime_config.py` | `CHUNK_STRATEGY` 入白名单（enum） |
| `frontend/js/pages/settings.js` | 设置页「文档切分」组渲染策略下拉（后端元数据驱动，改动小） |
| `frontend/js/pages/knowledge-bases.js` | 建库/编辑弹窗加策略选择 |

## 5. 前后对比

| 维度 | 当前 | 整改后 |
|---|---|---|
| 新增切割策略 | 改 `split_document()` 的 if/else，动核心文件 | 新文件 + `@register`，零侵入 |
| 策略选择 | 内容隐式探测，用户无感知无控制 | 请求/KB/全局三级解析，可显式指定 |
| 策略参数 | 全局阈值混用 | 策略自声明参数，KB 级可覆盖 |
| 可测试性 | 逻辑嵌在 Processor 里 | 策略纯函数，独立单测 |

## 6. 验证方式

1. **回归**：同一篇含 `#`/`##` 的文档 + 一篇纯文本，`auto` 策略切割结果与整改前逐条一致（快照对比）。
2. **显式指定**：对 markdown 文档强制 `recursive`，确认走递归分支。
3. **KB 覆盖**：两个 KB 配不同策略，同一文档分别处理，验证 chunk 结构不同。
4. **扩展演练**：新增一个 dummy 策略（如按句号切），验证不改任何现有文件即可注册生效。

## 7. 风险与备注

- **Chunk metadata 兼容**：现有 markdown 切割是否产出 header metadata 需在迁移时逐行对齐，保证下游（PG 存储、前端展示）不变。
- **YAGNI**：语义切割（semantic）**不在本期实现**，仅预留注册位；等大批量测试证明递归/markdown 不足时再加。
- 旧数据无需迁移（chunk_strategy NULL = auto = 现有行为）。
