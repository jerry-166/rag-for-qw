# RAGFlow - 智能知识库系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

RAGFlow是一个基于Retrieval-Augmented Generation (RAG)技术的智能知识库系统，提供文档管理、知识库构建、智能检索和AI问答等功能。

## 功能展示

以下截图均取自真实运行的系统（Stage 5 玻璃风新前端，深色主题），按「文档接入 → 处理流水线 → 检索问答 → 工程化能力」的完整链路组织。

### 入口与知识库管理

| 登录页面 | 知识库管理 |
|:---:|:---:|
| ![登录页面](img/login.jpg) | ![知识库管理](img/knowledge_base.jpg) |

创建知识库时可按库配置切割策略（如 Markdown 标题切割）与增强生成开关；两者均不勾选时该库走纯原文检索，不消耗 LLM token：

![创建知识库](img/kb_create.jpg)

### 文档处理流水线

拖拽上传 PDF / Markdown（≤50MB），支持按知识库筛选与全文搜索，文档状态（已上传 / 已完成）全程可追踪：

![文档管理](img/upload.jpg)

进入流水线后每一步可视化。**Step 1**：PDF 解析为 Markdown，左右双栏实时对照预览：

![PDF解析](img/parse_show.jpg)

**Step 2**：按策略切分为语义 chunk（本例 360 个），逐块预览原文、token 数与来源：

![文档分块](img/chunks.jpg)

**Step 3**：LLM 为每个 chunk 生成子问题与摘要（约 146 字，压缩比 1.9x），作为 Advanced 检索的衍生向量：

![子问题与摘要生成](img/subq_summary.jpg)

**Step 4**：chunk / 子问题 / 摘要三路向量化导入 Milvus（360 chunks、360 vectors、1585 子问题、1024 维）：

![导入Milvus](img/import_milvus.jpg)

### 知识检索与 AI Agent

支持向量 / BM25 关键词 / 混合（RRF + Rerank）三种检索模式，检索管道（FAQ → 实体图谱 → 向量 → 结果）逐级可视化，命中结果带相关度评分与原文展开：

![知识检索](img/retrive.jpg)

AI Agent 问答带引用来源与相似度评分，能力标签（rag-workflow / hybrid-retrieval / rerank / sse-stream 等）可追溯：

![AI Agent](img/agent.jpg)

「对比」模式下可让 Simple / Advanced / Claw 三个 Agent 并行回答同一问题，横向对比回答质量、耗时与引用数：

![多Agent对比](img/agent_compare.jpg)

### 工程化能力

**知识记忆**：对话中沉淀的 FAQ 自动进入候选记忆，经「升级为正式知识」流转为正式知识，带命中数与热度统计，形成自进化闭环：

| 正式知识（FAQ） | 检索配置 |
|:---:|:---:|
| ![知识记忆](img/memory_faq.jpg) | ![检索配置](img/settings.jpg) |

检索配置支持相关度阈值、Top-K、Reranker 类型（cross_encoder）、RRF 平滑常数等参数，运行时热生效、无需重启：

**审计中心**：全量操作日志（今日事件、最高频动作、失败率）按动作 / 用户 / 请求 ID / 资源类型筛选，可下钻单次请求的 JSON 明细：

![审计中心](img/audit.jpg)

**缓存中心**：内存 LRU + PG 向量缓存的命中率统计与查询日志，写路径失败单独计数：

![缓存中心](img/cache.jpg)

**测试集管理**：从 Session 提取问答对、批量导入、人工审核（问题 / 回答 / 上下文 / Ground Truth 四栏对照），沉淀评测基准：

![测试集](img/testset.jpg)

## 项目简介

RAGFlow旨在通过先进的RAG技术，为用户提供高效、准确的知识检索和问答能力。系统支持PDF文档的解析、分割、向量化存储，并通过向量数据库和全文检索引擎实现智能搜索。

### 核心特性

- **多知识库管理**：创建和管理多个知识库，支持文档分类存储
- **完整文档处理流程**：PDF解析 → 文档分割 → 子问题生成 → 摘要生成 → 向量化存储
- **三层检索架构**：Native（chunk原文向量语义匹配）、Advanced（子问题/摘要向量匹配）、Hybrid（RRF算法三路融合）三种向量检索策略，结合全文检索（BM25/Elasticsearch），提供高精度、高召回的知识检索
- **多策略重排序**：支持Reranker对搜索结果进行精排优化
- **AI Agent问答**：基于LangGraph构建的智能问答Agent，支持多种意图识别和对话管理
- **多级记忆管理**：支持会话记忆和长期记忆的持久化存储
- **响应式设计**：支持暗黑/明亮模式切换，提供良好的用户体验

## 技术栈

### 后端技术

| 类别 | 技术 |
|------|------|
| 核心框架 | Python 3.9+ / FastAPI |
| 向量数据库 | Milvus 2.2+ |
| 全文检索 | Elasticsearch 7.17+ / BM25 |
| 关系数据库 | PostgreSQL 13+ / SQLite |
| LLM框架 | LangChain / LiteLLM |
| 工作流引擎 | LangGraph |
| 数据验证 | Pydantic v2 |

### 前端技术

| 类别 | 技术 |
|------|------|
| 页面结构 | HTML5 |
| 样式 | CSS3（支持暗黑模式） |
| 逻辑 | JavaScript (ES6+) |
| Markdown渲染 | Marked.js |
| PDF预览 | PDF.js |

## 项目结构

```
rag-for-qw/
├── backend/                     # 后端代码
│   ├── api/                    # API路由模块
│   │   ├── __init__.py         # API路由注册
│   │   ├── auth.py             # 认证相关API
│   │   ├── documents.py        # 文档管理API
│   │   ├── files.py            # 文件处理API
│   │   ├── knowledge_bases.py  # 知识库管理API
│   │   ├── processing.py       # 文档处理API
│   │   ├── search.py           # 搜索API
│   │   ├── stats.py            # 统计API
│   │   └── agent.py            # Agent API
│   ├── agent/                  # 智能代理模块
│   │   ├── base.py             # Agent基础抽象
│   │   ├── registry.py         # Agent注册中心
│   │   ├── retrieval.py        # 检索策略
│   │   ├── simple/             # 简单Agent实现
│   │   ├── advanced/            # 高级Agent（意图分类/任务规划）
│   │   └── claw_agent/          # Claw Agent（LangGraph工作流）
│   │       ├── memory/          # 记忆管理
│   │       │   ├── memory_manager.py   # 记忆管理器
│   │       │   └── session_store.py    # 会话存储
│   │       ├── tools/           # Agent工具
│   │       │   └── rag_tools.py # RAG工具集
│   │       └── rag_workflow.py  # RAG工作流定义
│   ├── services/               # 核心服务
│   │   ├── __init__.py
│   │   ├── agent.py            # Agent服务
│   │   ├── auth.py             # 认证服务
│   │   ├── database.py         # 数据库服务
│   │   ├── document_processor.py # 文档处理器
│   │   ├── elasticsearch_client.py # ES客户端
│   │   ├── milvus_client.py    # Milvus客户端
│   │   ├── pdf_parser.py       # PDF解析器
│   │   ├── reranker.py          # 重排序服务
│   │   ├── storage.py           # 存储服务
│   │   └── bm25_client.py       # BM25检索客户端
│   ├── scripts/                # 工具脚本
│   │   ├── reset_database.py    # 数据库重置脚本
│   │   ├── rebuild_documents.py # 文档重建脚本
│   │   └── verify_database_schema.py # 数据库验证脚本
│   ├── app.py                  # 应用入口
│   ├── config.py               # 配置管理
│   ├── requirements.txt        # 依赖管理
│   └── .env.example            # 环境变量示例
├── frontend/                   # 前端代码
│   ├── design/                 # 【Stage 5 新前端】玻璃风实现（详见下文“前端架构说明”）
│   │   ├── index.html          # 新前端入口（引入 tokens.css + wireframe.css，复用 ../js/）
│   │   ├── preview.html        # 设计稿预览页
│   │   ├── tokens.css          # 设计令牌（颜色/间距/字号变量）
│   │   ├── ui.js               # 全局 UI 工具（玻璃风 confirm/prompt/alert modal）
│   │   └── page-wireframes/    # 8 页线框设计稿 + wireframe.css + sidebar.js
│   ├── css/
│   │   └── main.css            # 旧主样式（历史，design/ 体系替代）
│   ├── js/
│   │   ├── api.js              # API调用封装（design 复用）
│   │   ├── app.js              # 应用入口（design 复用）
│   │   ├── auth.js             # 认证逻辑
│   │   └── pages/
│   │       ├── knowledge-bases.js # 知识库管理页面（design 复用）
│   │       ├── documents.js      # 文档管理页面（design 复用）
│   │       ├── pipeline.js       # 文档处理流程页面（design 复用）
│   │       ├── search.js         # 知识检索页面（design 复用）
│   │       └── agent.js          # AI Agent页面（design 复用）
│   └── index.html              # 旧主HTML入口（历史保留，访问 design/index.html 进入新前端）
├── img/                        # 项目截图（运行实拍）
│   ├── login.jpg               # 登录页面
│   ├── knowledge_base.jpg      # 知识库管理
│   ├── kb_create.jpg           # 创建知识库（切割策略/增强生成配置）
│   ├── upload.jpg              # 文档管理（拖拽上传）
│   ├── parse_show.jpg          # Step1 PDF解析（PDF/MD对照）
│   ├── chunks.jpg              # Step2 文档分块（chunk预览）
│   ├── subq_summary.jpg        # Step3 子问题与摘要生成
│   ├── import_milvus.jpg        # Step4 向量化导入Milvus
│   ├── retrive.jpg             # 知识检索（多策略+管道可视化）
│   ├── agent.jpg               # AI Agent对话（引用来源）
│   ├── agent_compare.jpg       # 多Agent对比模式
│   ├── memory_faq.jpg          # 知识记忆（FAQ沉淀）
│   ├── settings.jpg            # 检索配置
│   ├── audit.jpg               # 审计中心
│   ├── cache.jpg               # 缓存中心
│   └── testset.jpg             # 测试集管理
└── README.md                   # 项目说明
```

## 快速开始

### 前置条件

- Python 3.9+
- PostgreSQL 13+ (支持SQLite作为替代)
- Milvus 2.2+
- Elasticsearch 7.17+ (可选，支持BM25替代)
- Node.js 14+ (可选，用于前端开发)

### 安装步骤

1. **克隆项目**

```bash
git clone <repository-url>
cd rag-for-qw
```

2. **配置环境变量**

```bash
# 复制环境变量示例文件
cp backend/.env.example backend/.env

# 编辑.env文件，配置相关参数
# 主要包括数据库连接、Milvus连接、Elasticsearch连接、API密钥等
```

3. **安装后端依赖**

```bash
cd backend
pip install -r requirements.txt
```

4. **初始化数据库**

```bash
# 运行数据库初始化脚本
python scripts/reset_database.py
```

5. **启动后端服务**

```bash
python app.py
# 或使用uvicorn
uvicorn app:app --host 0.0.0.0 --port 8003
```

6. **启动前端服务**

```bash
# 在frontend目录下启动静态文件服务器
cd frontend
python -m http.server 8000
```

7. **访问系统**

打开浏览器，访问 `http://localhost:8000`

> **前端有两个入口**（同一静态服务下）：
> - `http://localhost:8000/` → 旧前端入口 `frontend/index.html`（历史保留）
> - `http://localhost:8000/design/index.html` → **Stage 5 新前端** `frontend/design/index.html`（玻璃风 UI，推荐访问）
>
> 新前端在 Stage 5 重构中落地：用 `design/` 下的 `tokens.css` + `page-wireframes/wireframe.css` 玻璃风样式体系替代旧 `css/main.css`，但**复用 `js/` 下的全部业务逻辑**（api.js/app.js/pages/*.js 不变），通过 `design/ui.js` + `design/bridge.js` 桥接新模板与旧逻辑。详见下文“前端架构说明”。

## 前端架构说明（Stage 5 后）

项目前端在 Stage 5 引入了 **`frontend/design/`** 作为新前端实现，与旧 `frontend/index.html` 并存于同一静态服务下：

| 维度 | 旧前端 `frontend/index.html` | 新前端 `frontend/design/index.html` |
|------|------------------------------|--------------------------------------|
| 样式 | `css/main.css`（历史） | `design/tokens.css` + `design/page-wireframes/wireframe.css`（玻璃风设计令牌体系） |
| HTML 模板 | index.html 内联 | index.html 内联 + `design/page-wireframes/0X-*.html` 8 页线框设计稿（标准答案） |
| UI 组件 | 原生 confirm/prompt/alert | `design/ui.js` 玻璃风 modal（confirm/prompt/alert 统一 Promise 包装） |
| 业务 JS | `js/api.js` + `js/app.js` + `js/pages/*.js` | **完全复用**（相对路径 `../js/`） |
| 桥接 | — | `design/bridge.js` + `design/page-wireframes/sidebar.js`（连接新模板与旧 App/Page 生命周期） |
| 访问 | `http://host:port/` | `http://host:port/design/index.html` |

**关键约定**：`design/page-wireframes/` 下的 8 个线框 HTML 是用户验证过的"标准答案"设计稿。落地生产页面时（`js/pages/*.js` 的 render 逻辑），HTML 结构与 class 名优先对齐线框稿，旧 `js/pages/*.js` 只负责注入真实数据与事件绑定。详见 `docs/plans/` 下 Stage 5 相关文档与 `.codebuddy/memory/MEMORY.md` 的"UI 实现约定"。

## 配置说明

### 环境变量配置

主要配置项位于 `backend/.env`：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DATABASE_URL` | PostgreSQL/SQLite数据库连接 | `sqlite:///./data.db` |
| `MILVUS_HOST` | Milvus服务地址 | `localhost` |
| `MILVUS_PORT` | Milvus服务端口 | `19530` |
| `MILVUS_CHUNKS_COLLECTION` | Milvus chunk原文向量集合名 | `chunk_vectors` |
| `ES_HOST` | Elasticsearch地址 | `localhost` |
| `ES_PORT` | Elasticsearch端口 | `9200` |
| `OPENAI_API_KEY` | OpenAI API密钥 | - |
| `JWT_SECRET_KEY` | JWT加密密钥 | - |
| `STORAGE_TYPE` | 存储类型(local/oss) | `local` |

详细配置请参考 `backend/config.py` 文件。

## API文档

### 认证API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/login` | 用户登录 |
| POST | `/api/auth/logout` | 用户登出 |

### 知识库API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/knowledge-bases` | 获取知识库列表 |
| POST | `/api/knowledge-bases` | 创建知识库 |
| GET | `/api/knowledge-bases/{kb_id}` | 获取知识库详情 |
| PUT | `/api/knowledge-bases/{kb_id}` | 更新知识库 |
| DELETE | `/api/knowledge-bases/{kb_id}` | 删除知识库 |

### 文档API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/documents` | 获取文档列表 |
| GET | `/api/documents/pending` | 获取待处理文档 |
| GET | `/api/documents/{doc_id}` | 获取文档详情 |
| DELETE | `/api/documents/{doc_id}` | 删除文档 |

### 文件API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/upload/pdf` | 上传PDF文件 |
| GET | `/api/markdown/{file_id}` | 获取Markdown内容 |
| GET | `/api/pdf/{file_id}` | 获取PDF内容 |

### 处理API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/process/split/{file_id}` | 分割文档 |
| POST | `/api/process/generate/{file_id}` | 生成子问题和摘要 |
| POST | `/api/process/import/{file_id}` | 导入到向量数据库 |
| POST | `/api/process/full/{file_id}` | 完整处理流程 |

### 搜索API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/milvus/query` | 向量检索（Milvus） |
| POST | `/api/elasticsearch/search` | 全文检索（ES） |
| POST | `/api/bm25/search` | BM25检索 |
| POST | `/api/hybrid/search` | 混合检索 |

### Agent API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/agent/chat` | Agent对话 |
| GET | `/api/agent/history/{session_id}` | 获取对话历史 |
| DELETE | `/api/agent/history/{session_id}` | 清除对话历史 |

### 统计API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/stats/overview` | 获取系统统计概览 |

## 前端功能

### 1. 知识库管理

- 创建和管理知识库
- 查看知识库列表和详情
- 编辑知识库名称和描述
- 删除知识库

### 2. 文档管理

- 上传PDF文档到指定知识库
- 查看文档列表和状态
- 处理文档（解析、分割、生成子问题和摘要）
- 删除文档

### 3. 文档处理流程

- **PDF解析**：将PDF文档转换为Markdown格式
- **文档分割**：将文档分割为多个语义chunk
- **子问题生成**：为每个chunk生成相关子问题
- **摘要生成**：为chunk内容生成摘要
- **向量化存储**：将chunk、子问题和摘要向量化并存储到Milvus
- **全文索引**：将内容索引到Elasticsearch/BM25

### 4. 知识检索

- 支持三种向量检索模式：
  - **Native 检索**：直接对 chunk 原文向量检索，信息保真度高，适合精确匹配场景
  - **Advanced 检索**：对子问题和摘要向量检索（默认），适合语义理解场景
  - **Hybrid 检索**：三路并行检索后 RRF 算法融合去重，召回最全面
- 结合全文检索（Elasticsearch/BM25）提供关键词匹配
- 使用 RRF 算法融合多路检索结果
- 支持 Reranker 精排优化（CrossEncoder）
- 查看检索结果和相关度评分

### 5. AI Agent

- 基于LangGraph构建的智能问答Agent
- 支持多种意图识别：
  - 问候意图
  - 澄清意图
  - RAG问答意图
- 完整RAG工作流：
  - 查询扩展（生成子问题）
  - 混合检索（Milvus + ES并行）
  - 交叉编码器重排序
  - LLM生成回答
- 多级记忆管理：
  - 会话级记忆
  - 长期记忆存储

### 6. 系统设置

- 暗黑/明亮模式切换
- 用户信息管理
- 系统统计概览

## 核心架构

### Agent系统架构

系统实现了三种不同级别的Agent：

```
┌─────────────────────────────────────────────┐
│              Agent Registry                  │
├─────────────┬─────────────┬─────────────────┤
│   Simple    │  Advanced   │      Claw       │
│   Agent     │   Agent     │   (LangGraph)   │
├─────────────┼─────────────┼─────────────────┤
│ • 基础检索   │ • 意图分类   │ • 完整工作流     │
│ • 简单问答   │ • 任务规划   │ • SSE流式输出    │
│             │ • 工具管理   │ • 多级记忆      │
└─────────────┴─────────────┴─────────────────┘
```

### 文档处理流程

```
PDF上传 → PDF解析 → 文档分割 → 子问题/摘要生成 → 向量化存储 → 全文索引
    │         │          │              │                 │          │
    ▼         ▼          ▼              ▼                 ▼          ▼
  文件存储   Markdown   Chunk列表    SubQ/Summary       Milvus      ES/BM25
                                    列表             3个集合：
                                                    ├ chunk_summaries（摘要向量）
                                                    ├ chunk_subquestions（子问题向量）
                                                    └ chunk_vectors（原文向量 ← 新增）
```

### 搜索流程

```
用户查询 ──→ 选择检索模式 ─────────────────────────────→ 重排序 → 返回结果
                │                                              │
      ┌─────────┼──────────────┐                        CrossEncoder
      ▼         ▼              ▼                               │
   native    advanced        hybrid                            │
      │         │              │                               │
  chunk_    summaries+      三路并行                           │
  vectors   subquestions    +RRF融合  ─────────────────────────┘
（原文匹配）（衍生内容匹配）（召回最全）
      └─────────┴──────────────┘
                +
             BM25/ES
           （关键词检索）
```

## 部署指南

### 开发环境

按照快速开始步骤部署即可。

### 生产环境

1. **使用Gunicorn + Uvicorn**

```bash
pip install gunicorn
cd backend
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app:app
```

2. **使用Nginx作为反向代理**

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /api/ {
        proxy_pass http://localhost:8003;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        root /path/to/frontend;
        index index.html;
        try_files $uri $uri/ /index.html;
    }
}
```

3. **配置HTTPS**

使用Let's Encrypt或其他SSL证书提供商配置HTTPS。

## 项目依赖

### Python依赖

主要依赖见 `backend/requirements.txt`，核心包括：

- fastapi>=0.104.0
- uvicorn>=0.24.0
- pydantic>=2.0.0
- langchain>=0.1.0
- langgraph>=0.0.20
- langchain-openai>=0.0.5
- pymilvus>=2.3.0
- elasticsearch>=8.0.0
- sqlalchemy>=2.0.0
- python-multipart>=0.0.6
- python-jose>=3.3.0
- passlib>=1.7.4

## 贡献指南

1. **Fork项目**
2. **创建分支**
3. **提交代码**
4. **创建Pull Request**

## 许可证

本项目采用MIT许可证。

---

*RAGFlow - 让知识检索更智能*
