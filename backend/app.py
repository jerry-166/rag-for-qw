import uuid
import time
from pathlib import Path
from datetime import timedelta
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from config import settings, init_logger
from services.document_processor import DocumentProcessor
from services.milvus_client import MilvusClient
from services.pdf_parser import PDFParser
from services.database import db
from services.auth import get_password_hash, verify_password, create_access_token, get_current_user, check_permission
from services.storage import get_storage
from services.elasticsearch_client import es_client

# 初始化日志记录器
logger = init_logger(__name__)

# 应用状态，用于存储全局实例
app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("正在初始化应用...")

    # 初始化Milvus客户端
    app_state['milvus_client'] = MilvusClient()
    logger.info("Milvus客户端初始化完成")

    # 初始化存储实例
    app_state['storage'] = get_storage()
    logger.info(f"存储实例初始化完成，存储类型: {settings.STORAGE_TYPE}")

    yield

    # 关闭时
    logger.info("正在关闭应用...")
    # 这里可以添加清理逻辑
    logger.info("应用已关闭")


app = FastAPI(lifespan=lifespan)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的前端地址
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 临时存储目录
TEMP_DIR = settings.TEMP_DIR
TEMP_DIR.mkdir(exist_ok=True)

# 输出目录
OUTPUT_DIR = settings.OUTPUT_DIR
OUTPUT_DIR.mkdir(exist_ok=True)


# 支持metadata过滤
class QueryRequest(BaseModel):
    query: str
    limit: int = 5
    metadata_filter: dict = None
    knowledge_base_id: int = None


# 用户注册模型
class UserRegister(BaseModel):
    username: str
    email: str
    password: str


# 用户登录模型
class UserLogin(BaseModel):
    username: str
    password: str


# 令牌模型
class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int = None
    username: str = None
    role: str = None


# 令牌数据模型
class TokenData(BaseModel):
    username: str | None = None
    user_id: int | None = None
    role: str | None = None


@app.post("/api/auth/register")
async def register(user: UserRegister):
    """用户注册"""
    logger.info(f"开始用户注册，用户名: {user.username}")
    try:
        # 检查用户名是否已存在
        existing_user = db.get_user_by_username(user.username)
        if existing_user:
            logger.warning(f"用户名已存在: {user.username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在"
            )

        # 检查邮箱是否已存在
        existing_email = db.get_user_by_email(user.email)
        if existing_email:
            logger.warning(f"邮箱已存在: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已存在"
            )

        # 密码加密
        password_hash = get_password_hash(user.password)

        # 添加用户
        db.add_user(user.username, user.email, password_hash)

        logger.info(f"用户注册成功，用户名: {user.username}")
        return {
            "status": "success",
            "message": "注册成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")


@app.post("/api/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """用户登录"""
    logger.info(f"开始用户登录，用户名: {form_data.username}")
    try:
        # 查找用户
        user = db.get_user_by_username(form_data.username)
        if not user:
            logger.warning(f"用户不存在: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 验证密码
        if not verify_password(form_data.password, user["password_hash"]):
            logger.warning(f"密码错误，用户名: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 创建访问令牌，包含用户ID和角色
        access_token_expires = timedelta(minutes=30)
        access_token = create_access_token(
            data={"sub": user["username"], "user_id": user["id"], "role": user["role"]},
            expires_delta=access_token_expires
        )

        logger.info(f"用户登录成功，用户名: {form_data.username}")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user["id"],
            "username": user["username"],
            "role": user["role"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")


# 知识库相关模型
class KnowledgeBaseCreate(BaseModel):
    kb_name: str
    description: str = None
    metadata: dict = None


class KnowledgeBaseResponse(BaseModel):
    id: int
    kb_name: str
    user_id: int
    metadata: dict
    created_at: str


# 文档上传模型
class DocumentUpload(BaseModel):
    kb_id: int


@app.post("/api/knowledge-bases")
async def create_knowledge_base(kb: KnowledgeBaseCreate, current_user=Depends(get_current_user)):
    """创建知识库"""
    logger.info(f"开始创建知识库，名称: {kb.kb_name}")
    try:
        # 创建知识库
        kb_id = db.add_knowledge_base(
            user_id=current_user["id"],
            kb_name=kb.kb_name,
            description=kb.description,
            metadata=kb.metadata or {}
        )

        logger.info(f"知识库创建成功，ID: {kb_id}")
        return {
            "status": "success",
            "kb_id": kb_id,
            "message": "知识库创建成功"
        }
    except Exception as e:
        logger.error(f"创建知识库失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建知识库失败: {str(e)}")


@app.get("/api/knowledge-bases")
async def get_knowledge_bases(current_user=Depends(get_current_user)):
    """获取用户的知识库列表"""
    logger.info("开始获取知识库列表")
    try:
        # 获取用户的知识库
        kbs = db.get_user_knowledge_bases(current_user["id"])

        # 构建响应
        kb_list = []
        for kb in kbs:
            kb_list.append({
                "id": kb["id"],
                "kb_name": kb["kb_name"],
                "description": kb.get("description"),
                "created_at": kb["created_at"]
            })

        logger.info(f"获取知识库列表成功，共 {len(kb_list)} 个知识库")
        return {
            "status": "success",
            "knowledge_bases": kb_list
        }
    except Exception as e:
        logger.error(f"获取知识库列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取知识库列表失败: {str(e)}")


@app.post("/api/upload/pdf")
async def upload_pdf(file: UploadFile = File(...), kb_id: int = Form(None), current_user = Depends(get_current_user)):
    """上传PDF文件"""
    logger.info(f"开始处理PDF上传请求，文件名: {file.filename}")
    start_time = time.time()
    try:
        # 验证知识库权限
        if kb_id:
            if not db.check_kb_permission(current_user["id"], kb_id):
                logger.warning(f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {kb_id}")
                raise HTTPException(status_code=403, detail="无权限访问该知识库")
        else:
            # 如果没有指定知识库，使用默认知识库
            # 这里可以根据实际需求调整逻辑
            kbs = db.get_user_knowledge_bases(current_user["id"])
            if not kbs:
                # 如果用户没有知识库，创建一个默认知识库
                kb_id = db.add_knowledge_base(
                    user_id=current_user["id"],
                    kb_name="默认知识库",
                    metadata={}
                )
            else:
                kb_id = kbs[0]["id"]

        # 读取文件内容
        file_content = await file.read()
        
        # 计算文件哈希值，用于判断是否为相同文档
        import hashlib
        file_hash = hashlib.md5(file_content).hexdigest()
        
        # 检查数据库中是否已存在相同的文档
        # 这里需要在database.py中添加相应的方法
        existing_doc = db.get_document_by_hash_and_kb(file_hash, kb_id)
        if existing_doc:
            logger.info(f"文档已存在，文件名: {file.filename}, 已存在的文件ID: {existing_doc['id']}")
            return {
                "file_id": existing_doc["id"],
                "status": "success",
                "message": "文档已存在，使用现有文件"
            }

        # 生成唯一文件ID
        file_id = str(uuid.uuid4())
        
        # 调整存储目录结构
        storage = app_state['storage']
        enhanced_md_path = f"{current_user['id']}/{kb_id}/{file_id}/enhanced.md"
        original_file_path = f"{current_user['id']}/{kb_id}/{file_id}/original.pdf"

        # 保存原始文件
        storage.save(original_file_path, file_content)
        logger.debug(f"原始文件保存成功")

        # 初始化PDF解析器
        parser = PDFParser()

        # 解析PDF（使用临时文件）
        temp_file_path = TEMP_DIR / f"{file_id}.pdf"
        with open(temp_file_path, "wb") as f:
            f.write(file_content)

        result = parser.parse_pdf(temp_file_path)
        logger.debug(f"PDF解析成功")

        # 读取生成的Markdown内容
        with open(result["markdown_path"], "r", encoding="utf-8") as f:
            markdown_content = f.read()

        # 保存增强MD文件到存储
        storage.save(enhanced_md_path, markdown_content)
        logger.debug(f"增强MD文件保存成功")

        # 存储结果到数据库
        doc_id = db.add_document(
            filename=file.filename,
            file_path=original_file_path,
            enhanced_md_path=enhanced_md_path,
            status="uploaded",
            user_id=current_user["id"],
            knowledge_base_id=kb_id,
            file_hash=file_hash
        )

        # 记录工作流日志
        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=doc_id,
            operation="upload_pdf",
            status="completed",
            message=f"PDF上传并解析成功，生成增强MD",
            knowledge_base_id=kb_id,
            processing_time=processing_time
        )

        logger.info(f"PDF上传并解析成功，文件ID: {doc_id}")
        return {
            "file_id": doc_id,
            "status": "success",
            "message": "PDF上传并解析成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        if 'file_id' in locals():
            db.add_workflow_log(
                document_id=file_id,
                operation="upload_pdf",
                status="failed",
                message=str(e),
                knowledge_base_id=kb_id if 'kb_id' in locals() else None
            )
        logger.error(f"上传失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@app.get("/api/markdown/{file_id}")
async def get_markdown(file_id: str, current_user=Depends(get_current_user)):
    """获取解析后的Markdown内容"""
    logger.info(f"开始获取Markdown内容，文件ID: {file_id}")
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该文档")

        # 只要文件不是处理失败状态，就可以获取Markdown内容
        if doc["status"] == "failed":
            logger.warning(f"文件处理失败，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件处理失败")

        # 使用存储接口读取文件
        storage = app_state['storage']
        content = storage.read(doc["enhanced_md_path"])
        if not content:
            logger.warning(f"Markdown文件未找到，路径: {doc['enhanced_md_path']}")
            raise HTTPException(status_code=404, detail="Markdown文件未找到")

        logger.info(f"获取Markdown内容成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "content": content,
            "status": "success"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Markdown失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取Markdown失败: {str(e)}")


@app.get("/api/pdf/{file_id}")
async def get_pdf(file_id: str, current_user=Depends(get_current_user)):
    """获取文档的PDF文件"""
    logger.info(f"开始获取PDF文件，文件ID: {file_id}")
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该文档")

        # 使用存储接口读取文件
        storage = app_state['storage']
        pdf_content = storage.read(doc["file_path"])
        if not pdf_content:
            logger.warning(f"PDF文件未找到，路径: {doc['file_path']}")
            raise HTTPException(status_code=404, detail="PDF文件未找到")

        logger.info(f"获取PDF文件成功，文件ID: {file_id}")
        # 对文件名进行URL编码，处理中文字符
        import urllib.parse
        encoded_filename = urllib.parse.quote(doc['filename'])
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={encoded_filename}; filename*=UTF-8''{encoded_filename}"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取PDF文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取PDF文件失败: {str(e)}")


@app.post("/api/process/split/{file_id}")
async def split_document(file_id: str, current_user=Depends(get_current_user)):
    """MD切割接口"""
    logger.info(f"开始切割文档，文件ID: {file_id}")
    start_time = time.time()
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 只要文件不是处理失败状态，就可以进行文档切割
        if doc["status"] == "failed":
            logger.warning(f"文件处理失败，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件处理失败")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        # 检查数据库中是否已经存在切割结果
        existing_chunks = db.get_document_chunks(file_id)
        if existing_chunks and len(existing_chunks) > 0:
            logger.info(f"文档已切割，直接返回数据库中的切割结果，文件ID: {file_id}")
            chunks = [chunk["content"] for chunk in existing_chunks]
            chunks_count = len(chunks)
            return {
                "file_id": file_id,
                "status": "success",
                "chunks": chunks,
                "chunks_count": chunks_count,
                "message": "文档已切割，直接返回数据库中的切割结果"
            }

        # 初始化文档处理器
        processor = DocumentProcessor()
        storage = app_state['storage']

        # 读取Markdown内容
        markdown_content = storage.read(doc["enhanced_md_path"])
        if not markdown_content:
            raise HTTPException(status_code=404, detail="Markdown文件未找到")

        # 切割文档
        process_result = processor.split_document(markdown_content)
        logger.debug(f"文档切割完成，生成 {len(process_result['chunks'])} 个段落")

        # 存储文档块到PostgreSQL并索引到Elasticsearch
        chunks = process_result['chunks']
        chunk_ids = []
        for i, chunk in enumerate(chunks):
            # 添加到PostgreSQL
            chunk_id = db.add_document_chunk(
                document_id=file_id,
                chunk_index=i,
                content=chunk,
                metadata={"source": doc["filename"]},
                knowledge_base_id=doc["knowledge_base_id"]
            )
            if chunk_id:
                chunk_ids.append(chunk_id)
                # 索引到Elasticsearch
                es_client.index_chunk(
                    chunk_id=chunk_id,
                    user_id=current_user["id"],
                    document_id=file_id,
                    knowledge_base_id=doc["knowledge_base_id"],
                    chunk_index=i,
                    content=chunk,
                    metadata={"source": doc["filename"]}
                )

        # 更新数据库中的文档状态
        db.update_document(
            file_id,
            status="chunk_done",
            es_indexed=True
        )

        # 记录工作流日志
        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=file_id,
            operation="split_document",
            status="completed",
            message=f"文档切割成功，生成 {len(chunks)} 个段落",
            knowledge_base_id=doc["knowledge_base_id"],
            processing_time=processing_time
        )

        chunks_count = len(process_result["chunks"])
        logger.info(f"文档切割成功，文件ID: {file_id}, 段落数: {chunks_count}")
        return {
            "file_id": file_id,
            "status": "success",
            "chunks": process_result["chunks"],
            "chunks_count": chunks_count,
            "message": "文档切割成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        doc = db.get_document(file_id)
        if doc:
            db.add_workflow_log(
                document_id=file_id,
                operation="split_document",
                status="failed",
                message=str(e),
                knowledge_base_id=doc["knowledge_base_id"]
            )
        logger.error(f"文档切割失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"文档切割失败: {str(e)}")


@app.post("/api/process/generate/{file_id}")
async def generate_sub_questions_and_summary(file_id: str, current_user=Depends(get_current_user)):
    """生成子问题和摘要接口"""
    logger.info(f"开始生成子问题和摘要，文件ID: {file_id}")
    start_time = time.time()
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 只要文件不是处理失败状态，就可以生成增强内容
        if doc["status"] == "failed":
            logger.warning(f"文件处理失败，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件处理失败")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        # 从数据库中获取文档块
        chunks = db.get_document_chunks(file_id)
        
        # 检查数据库中是否已经存在生成结果
        has_generated_data = False
        results = {}
        for chunk in chunks:
            sub_questions = db.get_sub_questions_by_chunk(chunk["id"])
            summary = db.get_chunk_summary(chunk["id"])
            if sub_questions or summary:
                has_generated_data = True
                chunk_index = chunk["chunk_index"]
                results[chunk_index] = {
                    "sub_questions": [sq["content"] for sq in sub_questions],
                    "summary": summary["content"] if summary else ""
                }
        
        if has_generated_data:
            logger.info(f"文档已生成增强内容，直接返回数据库中的结果，文件ID: {file_id}")
            return {
                "file_id": file_id,
                "status": "success",
                "results": results,
                "message": "文档已生成增强内容，直接返回数据库中的结果"
            }

        # 初始化文档处理器
        processor = DocumentProcessor()

        # 构建数据对象
        from services.document_processor import StoredData
        datas = []
        for i, chunk in enumerate(chunks):
            data = StoredData(
                id=f"doc_{chunk['id']}",
                chunk=chunk["content"],
                sub_questions=[],
                subq_embeddings=[],
                summary="",
                summary_embedding=[],
                metadata={"source": doc["filename"], "document_id": file_id}
            )
            datas.append(data)

        # 批量生成子问题和摘要
        await processor.generate_batches_async_concurrent(datas, batch_size=16, max_concurrency=8)

        # 批量生成嵌入向量
        await processor.generate_and_fill_embeddings(datas)

        # 存储子问题和摘要到数据库
        sub_questions_count = 0
        summaries_count = 0
        for i, chunk in enumerate(chunks):
            data = datas[i]

            # 存储子问题
            for subq in data.sub_questions:
                db.add_sub_question(
                    document_id=file_id,
                    chunk_id=chunk["id"],
                    content=subq,
                    metadata={"source": doc["filename"]},
                    knowledge_base_id=doc["knowledge_base_id"]
                )
                sub_questions_count += 1

            # 存储摘要
            if data.summary:
                db.add_chunk_summary(
                    document_id=file_id,
                    chunk_id=chunk["id"],
                    content=data.summary,
                    metadata={"source": doc["filename"]},
                    knowledge_base_id=doc["knowledge_base_id"]
                )
                summaries_count += 1

        # 更新数据库中的文档状态
        db.update_document(
            file_id,
            status="generated"
        )

        # 记录工作流日志
        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=file_id,
            operation="generate_sub_questions_and_summary",
            status="completed",
            message=f"生成子问题和摘要成功，生成 {sub_questions_count} 个子问题",
            knowledge_base_id=doc["knowledge_base_id"],
            processing_time=processing_time
        )

        logger.info(f"生成子问题和摘要成功，文件ID: {file_id}, 子问题数: {sub_questions_count}")
        return {
            "file_id": file_id,
            "status": "success",
            "summaries_count": summaries_count,
            "sub_questions_count": sub_questions_count,
            "message": "生成子问题和摘要成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        doc = db.get_document(file_id)
        if doc:
            db.add_workflow_log(
                document_id=file_id,
                operation="generate_sub_questions_and_summary",
                status="failed",
                message=str(e),
                knowledge_base_id=doc["knowledge_base_id"]
            )
        logger.error(f"生成子问题和摘要失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成子问题和摘要失败: {str(e)}")


@app.get("/api/stats/overview")
async def get_stats_overview(current_user=Depends(get_current_user)):
    """获取统计概览"""
    try:
        start_time = time.time()
        logger.info(f"开始获取统计概览，用户: {current_user['username']}")
        
        # 初始化数据库连接
        db = app_state['db']
        
        # 检查是否为admin用户
        is_admin = current_user.get('role') == 'admin'
        
        # 获取统计信息
        if is_admin:
            # Admin用户可以看到所有数据
            total_documents = db.get_total_documents()
            total_chunks = db.get_total_chunks()
            total_sub_questions = db.get_total_sub_questions()
            total_summaries = db.get_total_summaries()
            total_users = db.get_total_users()
        else:
            # 普通用户只能看到自己的数据
            total_documents = db.get_user_documents_count(current_user['id'])
            total_chunks = db.get_user_chunks_count(current_user['id'])
            total_sub_questions = db.get_user_sub_questions_count(current_user['id'])
            total_summaries = db.get_user_summaries_count(current_user['id'])
            total_users = 1  # 只统计自己
        
        processing_time = time.time() - start_time
        
        logger.info(f"获取统计概览成功，用户: {current_user['username']}")
        return {
            "status": "success",
            "message": "获取统计概览成功",
            "data": {
                "total_documents": total_documents,
                "total_chunks": total_chunks,
                "total_sub_questions": total_sub_questions,
                "total_summaries": total_summaries,
                "total_users": total_users if is_admin else 1,
                "is_admin": is_admin
            },
            "processing_time": f"{processing_time:.2f}s"
        }
    except Exception as e:
        logger.error(f"获取统计概览失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取统计概览失败")


@app.post("/api/process/import/{file_id}")
async def import_to_milvus(file_id: str, current_user=Depends(get_current_user)):
    """导入到Milvus"""
    logger.info(f"开始导入到Milvus，文件ID: {file_id}")
    start_time = time.time()
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        if doc["status"] not in ["generated", "completed"]:
            logger.warning(f"文件状态错误，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件尚未生成子问题和摘要")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        # 初始化文档处理器和Milvus客户端
        processor = DocumentProcessor()
        milvus_client = app_state['milvus_client']

        # 从数据库中获取文档块、子问题和摘要
        chunks = db.get_document_chunks(file_id)
        
        # 构建数据对象
        from services.document_processor import StoredData
        datas = []
        for i, chunk in enumerate(chunks):
            # 获取子问题
            sub_questions = db.get_sub_questions_by_chunk(chunk["id"])
            sub_questions_list = [sq["content"] for sq in sub_questions]
            
            # 获取摘要
            summary = db.get_chunk_summary(chunk["id"])
            summary_text = summary["content"] if summary else ""
            
            # 创建数据对象
            data = StoredData(
                id=f"doc_{chunk['id']}",
                chunk=chunk["content"],
                sub_questions=sub_questions_list,
                subq_embeddings=[],
                summary=summary_text,
                summary_embedding=[],
                metadata={"source": doc["filename"], "document_id": file_id}
            )
            datas.append(data)
        
        # 只有当文档状态不是completed时，才生成嵌入向量
        if doc["status"] != "completed":
            # 生成嵌入向量
            await processor.generate_and_fill_embeddings(datas)
        else:
            logger.info(f"文档状态已完成，跳过嵌入生成，直接导入到Milvus，文件ID: {file_id}")

        # 批量导入到Milvus
        import_result = milvus_client.import_data(
            datas,
            user_id=current_user["id"],
            knowledge_base_id=doc["knowledge_base_id"]
        )

        # 更新数据库中的文档状态
        db.update_document(
            file_id,
            status="completed"
        )

        # 记录工作流日志
        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=file_id,
            operation="import_to_milvus",
            status="completed",
            message="导入到Milvus成功",
            knowledge_base_id=doc["knowledge_base_id"],
            processing_time=processing_time
        )

        logger.info(f"导入到Milvus成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "status": "success",
            "message": "导入到Milvus成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        doc = db.get_document(file_id)
        if doc:
            db.add_workflow_log(
                document_id=file_id,
                operation="import_to_milvus",
                status="failed",
                message=str(e),
                knowledge_base_id=doc["knowledge_base_id"]
            )
        logger.error(f"导入到Milvus失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导入到Milvus失败: {str(e)}")


@app.post("/api/process/full/{file_id}")
async def full_process(file_id: str, current_user=Depends(get_current_user)):
    """一键式完整处理接口"""
    logger.info(f"开始一键式完整处理，文件ID: {file_id}")
    start_time = time.time()
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        # 步骤1: 切割文档（如果尚未切割）
        if doc["status"] == "uploaded":
            logger.info(f"开始切割文档，文件ID: {file_id}")
            # 调用切割接口
            split_response = await split_document(file_id, current_user)
            doc = db.get_document(file_id)  # 重新获取文档信息

        # 步骤2: 生成子问题和摘要（如果尚未生成）
        if doc["status"] == "chunk_done":
            logger.info(f"开始生成子问题和摘要，文件ID: {file_id}")
            # 调用生成接口
            generate_response = await generate_sub_questions_and_summary(file_id, current_user)
            doc = db.get_document(file_id)  # 重新获取文档信息

        # 步骤3: 导入到Milvus（如果尚未导入）
        if doc["status"] == "generated":
            logger.info(f"开始导入到Milvus，文件ID: {file_id}")
            # 调用导入接口
            import_response = await import_to_milvus(file_id, current_user)
            doc = db.get_document(file_id)  # 重新获取文档信息

        # 记录工作流日志
        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=file_id,
            operation="full_process",
            status="completed",
            message="一键式完整处理成功",
            knowledge_base_id=doc["knowledge_base_id"],
            processing_time=processing_time
        )

        logger.info(f"一键式完整处理成功，文件ID: {file_id}")
        # todo：一键处理也可展示所有中间结果呢
        return {
            "file_id": file_id,
            "status": "success",
            "message": "一键式完整处理成功",
            "document_status": doc["status"]
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        doc = db.get_document(file_id)
        if doc:
            db.add_workflow_log(
                document_id=file_id,
                operation="full_process",
                status="failed",
                message=str(e),
                knowledge_base_id=doc["knowledge_base_id"]
            )
        logger.error(f"一键式完整处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"一键式完整处理失败: {str(e)}")


@app.get("/api/process/result/{file_id}")
async def get_process_result(file_id: str, current_user=Depends(get_current_user)):
    """获取文档处理结果"""
    logger.info(f"开始获取文档处理结果，文件ID: {file_id}")
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该文档")

        if doc["status"] != "completed":
            logger.warning(f"文件尚未处理完成，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件尚未处理完成")

        # 从数据库中获取文档块、子问题和摘要
        chunks = db.get_document_chunks(file_id)

        # 构建结果
        chunks_list = []
        sub_questions_list = []
        summaries_list = []

        for chunk in chunks:
            chunks_list.append(chunk["content"])

            # 获取子问题
            sub_questions = db.get_sub_questions_by_chunk(chunk["id"])
            sub_questions_list.append([sq["content"] for sq in sub_questions])

            # 获取摘要
            summary = db.get_chunk_summary(chunk["id"])
            summaries_list.append(summary["content"] if summary else "")

        logger.info(f"获取文档处理结果成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "chunks": chunks_list,
            "sub_questions": sub_questions_list,
            "summaries": summaries_list,
            "status": doc["status"]  # 返回文档的实际处理状态
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取处理结果失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取处理结果失败: {str(e)}")


@app.post("/api/milvus/query")
async def query_milvus(request: QueryRequest, current_user=Depends(get_current_user)):
    """查询Milvus数据"""
    logger.info(f"开始查询Milvus数据，查询文本: {request.query}")
    try:
        # 使用全局Milvus客户端实例
        milvus_client = app_state['milvus_client']

        # 执行查询，传递用户权限信息
        # 构建metadata_filter，包含用户权限信息
        metadata_filter = request.metadata_filter or {}

        # 非管理员只能访问自己的文档和有权限的知识库
        if current_user["role"] != "admin":
            metadata_filter["user_id"] = current_user["id"]

        # 如果指定了知识库ID，添加到过滤条件
        if request.knowledge_base_id:
            metadata_filter["knowledge_base_id"] = request.knowledge_base_id

        results = milvus_client.query(
            query_text=request.query,
            limit=request.limit,
            metadata_filter=metadata_filter
        )

        logger.debug(f"查询完成，返回 {len(results)} 条结果")

        logger.info(f"查询Milvus数据成功")
        return {
            "status": "success",
            "query": request.query,
            "results": results
        }
    except Exception as e:
        logger.error(f"查询失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@app.get("/api/milvus/info")
async def get_milvus_info(current_user=Depends(get_current_user)):
    """获取Milvus集合信息"""
    logger.info("开始获取Milvus集合信息")
    try:
        # 只有管理员可以获取Milvus集合信息
        if current_user["role"] != "admin":
            logger.warning(f"非管理员用户尝试获取Milvus集合信息: {current_user['username']}")
            raise HTTPException(status_code=403, detail="无权限访问该接口")

        # 使用全局Milvus客户端实例
        milvus_client = app_state['milvus_client']

        # 获取集合信息
        info = milvus_client.get_collection_info()
        logger.debug(f"获取集合信息: {info}")

        logger.info("获取Milvus集合信息成功")
        return {
            "status": "success",
            "info": info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Milvus信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取Milvus信息失败: {str(e)}")


@app.post("/api/elasticsearch/search")
async def search_elasticsearch(request: QueryRequest, current_user=Depends(get_current_user)):
    """Elasticsearch关键词检索"""
    logger.info(f"开始Elasticsearch关键词检索，查询文本: {request.query}")
    try:
        # 构建filters，包含知识库ID
        filters = request.metadata_filter or {}
        if request.knowledge_base_id:
            filters["knowledge_base_id"] = request.knowledge_base_id
        
        # 执行关键词搜索
        results = es_client.search(
            query=request.query,
            user_id=current_user["id"],
            size=request.limit,
            filters=filters
        )

        logger.debug(f"搜索完成，返回 {len(results)} 条结果")

        logger.info("Elasticsearch关键词检索成功")
        return {
            "status": "success",
            "query": request.query,
            "results": results
        }
    except Exception as e:
        logger.error(f"搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


def rrf(rankings, k=60):
    """Reciprocal Rank Fusion算法"""
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            item_id = item['id'] if 'id' in item else item.get('chunk_id')
            if item_id not in scores:
                scores[item_id] = 0
            scores[item_id] += 1 / (k + rank)
    # 按分数排序
    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_items]


@app.post("/api/hybrid/search")
async def hybrid_search(request: QueryRequest, current_user=Depends(get_current_user)):
    """混合检索（关键词 + 向量）"""
    logger.info(f"开始混合检索，查询文本: {request.query}")
    try:
        # 并行执行检索
        import asyncio

        # 执行Elasticsearch关键词检索
        async def es_search():
            filters = request.metadata_filter or {}
            # 如果指定了知识库ID，添加到过滤条件
            if request.knowledge_base_id:
                filters["knowledge_base_id"] = request.knowledge_base_id
            return es_client.search(
                query=request.query,
                user_id=current_user["id"],
                size=request.limit * 2,  # 获取更多结果以提高RRF效果
                filters=filters
            )

        # 执行Milvus向量检索
        async def milvus_search():
            milvus_client = app_state['milvus_client']
            metadata_filter = request.metadata_filter or {}
            if current_user["role"] != "admin":
                metadata_filter["user_id"] = current_user["id"]
            # 如果指定了知识库ID，添加到过滤条件
            if request.knowledge_base_id:
                metadata_filter["knowledge_base_id"] = request.knowledge_base_id
            return milvus_client.query(
                query_text=request.query,
                limit=request.limit * 2,  # 获取更多结果以提高RRF效果
                metadata_filter=metadata_filter
            )

        # 并行执行两个检索
        es_results, milvus_results = await asyncio.gather(
            es_search(),
            milvus_search()
        )

        # 准备RRF输入
        rankings = []

        # 处理ES结果
        if es_results:
            rankings.append(es_results)

        # 处理Milvus结果
        if milvus_results:
            rankings.append(milvus_results)

        # 使用RRF合并结果
        if rankings:
            final_ids = rrf(rankings)
            # 限制返回结果数量
            final_ids = final_ids[:request.limit]

            # 从PostgreSQL获取完整的chunk信息
            if final_ids:
                chunks = db.get_document_chunks_by_ids(final_ids)
                # 构建结果列表，保持RRF排序
                final_results = []
                id_to_chunk = {chunk['id']: chunk for chunk in chunks}
                # 计算RRF分数
                scores = {}
                for ranking in rankings:
                    for rank, item in enumerate(ranking, 1):
                        item_id = item['id'] if 'id' in item else item.get('chunk_id')
                        if item_id not in scores:
                            scores[item_id] = 0
                        scores[item_id] += 1 / (60 + rank)

                for chunk_id in final_ids:
                    if chunk_id in id_to_chunk:
                        chunk = id_to_chunk[chunk_id]
                        # 使用RRF分数
                        chunk['score'] = scores.get(chunk_id, 0.0)
                        final_results.append(chunk)
            else:
                final_results = []
        else:
            final_results = []

        logger.debug(f"混合检索完成，返回 {len(final_results)} 条结果")

        logger.info("混合检索成功")
        return {
            "status": "success",
            "query": request.query,
            "results": final_results
        }
    except Exception as e:
        logger.error(f"混合检索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"混合检索失败: {str(e)}")


@app.get("/api/documents/pending")
async def get_pending_documents(current_user=Depends(get_current_user)):
    """获取待处理的文档列表（已解析但未切块或未生成子问题）"""
    logger.info("开始获取待处理文档列表")
    try:
        # 获取用户有权限的知识库
        user_kbs = db.get_user_knowledge_bases(current_user["id"])
        kb_ids = [kb["id"] for kb in user_kbs]

        # 获取待处理的文档
        pending_docs = db.get_pending_documents(kb_ids)

        logger.info(f"获取待处理文档列表成功，共 {len(pending_docs)} 个文档")
        return {
            "status": "success",
            "documents": pending_docs
        }
    except Exception as e:
        logger.error(f"获取待处理文档列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取待处理文档列表失败: {str(e)}")

@app.get("/api/documents")
async def get_documents(kb_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """获取文档列表，可选择按知识库ID过滤"""
    logger.info(f"开始获取文档列表，知识库ID: {kb_id}")
    try:
        # 获取用户有权限的知识库
        user_kbs = db.get_user_knowledge_bases(current_user["id"])
        user_kb_ids = [kb["id"] for kb in user_kbs]
        
        # 如果指定了kb_id，检查用户是否有权限
        if kb_id:
            if kb_id not in user_kb_ids:
                logger.warning(f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {kb_id}")
                raise HTTPException(status_code=403, detail="无权限访问该知识库")
            # 只查询指定知识库的文档
            query = "SELECT * FROM document WHERE knowledge_base_id = %s"
            docs = db.fetchall(query, (kb_id,))
        else:
            # 查询所有用户有权限的知识库的文档
            query = "SELECT * FROM document WHERE knowledge_base_id = ANY(%s)"
            docs = db.fetchall(query, (user_kb_ids,))

        # 构建文档列表
        document_list = []
        for doc in docs:
            document_list.append({
                "file_id": doc["id"],
                "filename": doc["filename"],
                "file_size": None,  # 暂时设为null，后续可以从文件系统获取
                "status": doc["status"],
                "created_at": doc["created_at"]
            })

        logger.info(f"获取文档列表成功，共 {len(document_list)} 个文档")
        return {
            "status": "success",
            "documents": document_list
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文档列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取文档列表失败: {str(e)}")


@app.get("/api/documents/{file_id}/preview")
async def get_document_preview(file_id: str, current_user=Depends(get_current_user)):
    """获取文档预览内容"""
    logger.info(f"开始获取文档预览，文件ID: {file_id}")
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该文档")

        # 使用存储接口读取文件
        storage = app_state['storage']
        content = storage.read(doc["enhanced_md_path"])
        if not content:
            logger.warning(f"Markdown文件未找到，路径: {doc['enhanced_md_path']}")
            raise HTTPException(status_code=404, detail="Markdown文件未找到")

        # 截取前500个字符作为预览
        preview_content = content[:500] + "..." if len(content) > 500 else content

        logger.info(f"获取文档预览成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "filename": doc["filename"],
            "preview": preview_content,
            "status": doc["status"],  # 返回文档的实际处理状态
            "file_size": doc.get("file_size"),
            "tables_count": doc.get("tables_count"),
            "formulas_count": doc.get("formulas_count")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文档预览失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取文档预览失败: {str(e)}")


@app.delete("/api/documents/{file_id}")
async def delete_document(file_id: str, current_user=Depends(get_current_user)):
    """删除文档"""
    logger.info(f"开始删除文档，文件ID: {file_id}")
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限删除该文档")

        # 从应用状态中获取Milvus客户端
        milvus_client = app_state.get('milvus_client')
        if milvus_client:
            # 删除Milvus中的对应数据
            milvus_client.delete_data_by_document(file_id)

        # 检查是否有workflow_log引用该文档
        # 由于workflow_log是审计日志，我们不删除它，而是直接删除文档
        # 但需要确保数据库表结构允许这样做（外键应该是可空的或级联删除的）
        # 暂时直接删除，看是否能成功
        result = db.delete_document(file_id)
        if result:
            logger.info(f"文档删除成功，文件ID: {file_id}")
            return {
                "status": "success",
                "message": "文档删除成功"
            }
        else:
            raise HTTPException(status_code=500, detail="删除文档失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文档失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除文档失败: {str(e)}")


@app.delete("/api/knowledge-bases/{kb_id}")
async def delete_knowledge_base(kb_id: int, current_user=Depends(get_current_user)):
    """删除知识库"""
    logger.info(f"开始删除知识库，知识库ID: {kb_id}")
    try:
        # 获取知识库信息
        kb = db.get_knowledge_base(kb_id)
        if not kb:
            logger.warning(f"知识库未找到，知识库ID: {kb_id}")
            raise HTTPException(status_code=404, detail="知识库未找到")

        # 验证用户权限（只有知识库创建者可以删除）
        if kb["user_id"] != current_user["id"] and current_user["role"] != "admin":
            logger.warning(
                f"用户无权限删除知识库，用户: {current_user['username']}, 知识库ID: {kb_id}")
            raise HTTPException(status_code=403, detail="无权限删除该知识库")

        # 从应用状态中获取Milvus客户端
        milvus_client = app_state.get('milvus_client')
        if milvus_client:
            # 删除Milvus中的对应数据
            milvus_client.delete_data_by_knowledge_base(kb_id)

        # 删除知识库及相关数据
        result = db.delete_knowledge_base(kb_id)
        if result:
            logger.info(f"知识库删除成功，知识库ID: {kb_id}")
            return {
                "status": "success",
                "message": "知识库删除成功"
            }
        else:
            raise HTTPException(status_code=500, detail="删除知识库失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除知识库失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除知识库失败: {str(e)}")


@app.get("/")
async def root():
    """根路径"""
    logger.info("访问根路径")
    return {"message": "RAG System API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
