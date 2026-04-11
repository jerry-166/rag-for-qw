# RAGFlow - 智能知识库系统

RAGFlow是一个基于Retrieval-Augmented Generation (RAG)技术的智能知识库系统，提供文档管理、知识库构建、智能检索等功能。

## 项目简介

RAGFlow旨在通过先进的RAG技术，为用户提供高效、准确的知识检索和问答能力。系统支持PDF文档的解析、分割、向量化存储，并通过向量数据库和全文检索引擎实现智能搜索。

### 核心特性

- **文档管理**：支持PDF文档上传、解析和管理
- **知识库构建**：创建和管理多个知识库，支持文档分类存储
- **智能检索**：结合向量检索和全文检索，提供高精度的知识检索
- **子问题生成**：自动为文档生成子问题，增强检索效果
- **摘要生成**：为文档内容生成摘要，提供快速内容概览
- **Reranker**：支持多种重排序策略，优化搜索结果
- **响应式设计**：支持黑夜/白天模式切换，提供良好的用户体验

## 技术栈

### 后端技术

- **Python 3.9+**：核心开发语言
- **FastAPI**：API框架
- **Milvus**：向量数据库，用于存储和检索向量嵌入
- **Elasticsearch**：全文检索引擎
- **PostgreSQL**：关系型数据库，用于存储元数据
- **LangChain**：LLM应用开发框架
- **LiteLLM**：统一的LLM接口
- **Pydantic**：数据验证

### 前端技术

- **HTML5/CSS3**：页面结构和样式
- **JavaScript (ES6+)**：前端逻辑
- **Marked.js**：Markdown渲染
- **PDF.js**：PDF预览

## 项目结构

```
rag-for-qw/
├── backend/                  # 后端代码
│   ├── api/                  # API路由模块
│   │   ├── __init__.py       # API路由注册
│   │   ├── auth.py           # 认证相关API
│   │   ├── documents.py      # 文档管理API
│   │   ├── files.py          # 文件处理API
│   │   ├── knowledge_bases.py # 知识库管理API
│   │   ├── processing.py     # 文档处理API
│   │   ├── search.py         # 搜索API
│   │   └── stats.py          # 统计API
│   ├── services/             # 核心服务
│   │   ├── __init__.py
│   │   ├── agent.py          # 智能代理
│   │   ├── auth.py           # 认证服务
│   │   ├── database.py       # 数据库服务
│   │   ├── document_processor.py # 文档处理器
│   │   ├── elasticsearch_client.py # ES客户端
│   │   ├── milvus_client.py  # Milvus客户端
│   │   ├── pdf_parser.py     # PDF解析器
│   │   ├── reranker.py       # 重排序服务
│   │   └── storage.py        # 存储服务
│   ├── scripts/              # 工具脚本
│   ├── app.py                # 应用入口
│   ├── config.py             # 配置管理
│   ├── requirements.txt      # 依赖管理
│   └── .env.example          # 环境变量示例
├── frontend/                 # 前端代码
│   ├── css/                  # 样式文件
│   │   └── main.css          # 主样式文件
│   ├── js/                   # JavaScript文件
│   │   ├── pages/            # 页面模块
│   │   │   ├── documents.js  # 文档管理页面
│   │   │   ├── knowledge-bases.js # 知识库页面
│   │   │   ├── pipeline.js   # 文档处理流程页面
│   │   │   └── search.js     # 搜索页面
│   │   ├── api.js            # API调用
│   │   ├── app.js            # 应用逻辑
│   │   └── auth.js           # 认证逻辑
│   └── index.html            # 主HTML文件
└── README.md                 # 项目说明
```

## 快速开始

### 前置条件

- Python 3.9+
- PostgreSQL 13+
- Milvus 2.2+
- Elasticsearch 7.17+
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

## 配置说明

### 核心配置项

- **存储配置**：支持本地存储和OSS存储
- **Milvus配置**：向量数据库连接信息
- **Elasticsearch配置**：全文检索引擎连接信息
- **PostgreSQL配置**：关系型数据库连接信息
- **模型配置**：嵌入模型和语言模型设置
- **Reranker配置**：重排序策略设置

详细配置请参考 `backend/config.py` 文件。

## API文档

系统提供以下主要API端点：

### 认证API
- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录

### 知识库API
- `GET /api/knowledge-bases` - 获取知识库列表
- `POST /api/knowledge-bases` - 创建知识库
- `GET /api/knowledge-bases/{kb_id}` - 获取知识库详情
- `PUT /api/knowledge-bases/{kb_id}` - 更新知识库
- `DELETE /api/knowledge-bases/{kb_id}` - 删除知识库

### 文档API
- `GET /api/documents` - 获取文档列表
- `GET /api/documents/pending` - 获取待处理文档
- `GET /api/documents/{doc_id}` - 获取文档详情
- `DELETE /api/documents/{doc_id}` - 删除文档

### 文件API
- `POST /api/upload/pdf` - 上传PDF文件
- `GET /api/markdown/{file_id}` - 获取Markdown内容
- `GET /api/pdf/{file_id}` - 获取PDF内容

### 处理API
- `POST /api/process/split/{file_id}` - 分割文档
- `POST /api/process/generate/{file_id}` - 生成子问题和摘要
- `POST /api/process/import/{file_id}` - 导入到向量数据库
- `POST /api/process/full/{file_id}` - 完整处理流程

### 搜索API
- `POST /api/milvus/query` - 向量检索
- `POST /api/elasticsearch/search` - 全文检索
- `POST /api/hybrid/search` - 混合检索

### 统计API
- `GET /api/stats/overview` - 获取系统统计概览

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

### 3. 知识检索
- 支持向量检索、全文检索和混合检索
- 查看检索结果和相关度
- 显示子问题和摘要
- 搜索历史记录

### 4. 文档处理流程
- PDF解析为Markdown
- 文档分割为Chunk
- 生成子问题和摘要
- 导入到向量数据库

### 5. 系统设置
- 黑夜/白天模式切换
- 用户信息管理
- 系统统计概览

## 核心流程

### 文档处理流程

1. **上传PDF**：用户上传PDF文档到指定知识库
2. **解析PDF**：系统将PDF解析为Markdown格式
3. **分割文档**：将文档分割为多个Chunk
4. **生成增强**：为每个Chunk生成子问题和摘要
5. **向量化存储**：将Chunk、子问题和摘要向量化并存储到Milvus
6. **全文索引**：将内容索引到Elasticsearch

### 搜索流程

1. **接收查询**：用户输入查询语句
2. **并行检索**：同时进行向量检索和全文检索
3. **结果融合**：使用RRF算法融合两种检索结果
4. **重排序**：使用Reranker对结果进行精排
5. **返回结果**：返回最终排序后的结果

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

## 贡献指南

1. **Fork项目**
2. **创建分支**
3. **提交代码**
4. **创建Pull Request**

## 许可证

本项目采用MIT许可证。

## 联系我们

如有问题或建议，请联系项目维护者。

---

*RAGFlow - 让知识检索更智能*