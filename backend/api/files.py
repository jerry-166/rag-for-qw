from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Response
from typing import Optional
import uuid
import time
import hashlib
import urllib.parse
from pathlib import Path
from pydantic import BaseModel

from config import init_logger, settings
from services.database import db
from services.auth import get_current_user
from services.pdf_parser import PDFParser
from services.storage import get_storage
from services.milvus_client import MilvusClient
from services.elasticsearch_client import es_client
import shutil

logger = init_logger(__name__)
router = APIRouter()

# 文档上传模型
class DocumentUpload(BaseModel):
    kb_id: int


@router.post("/upload/pdf")
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
        storage = get_storage()
        enhanced_md_path = f"{current_user['id']}/{kb_id}/{file_id}/enhanced.md"
        original_file_path = f"{current_user['id']}/{kb_id}/{file_id}/original.pdf"

        # 保存原始文件
        storage.save(original_file_path, file_content)
        logger.debug(f"原始文件保存成功")

        # 初始化PDF解析器
        parser = PDFParser()

        # 解析PDF（使用临时文件）
        temp_file_path = settings.TEMP_DIR / f"{file_id}.pdf"
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

        # 计算处理时间（毫秒）
        processing_time_ms = (time.time() - start_time) * 1000
        # 确保时间不为0，否则存储为NULL
        upload_time = processing_time_ms if processing_time_ms > 0.1 else None
        
        # 存储结果到数据库
        doc_id = db.add_document(
            filename=file.filename,
            file_path=original_file_path,
            enhanced_md_path=enhanced_md_path,
            status="uploaded",
            user_id=current_user["id"],
            knowledge_base_id=kb_id,
            file_hash=file_hash,
            upload_time=upload_time
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


@router.get("/markdown/{file_id}")
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
        storage = get_storage()
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


@router.get("/pdf/{file_id}")
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
        storage = get_storage()
        pdf_content = storage.read(doc["file_path"])
        if not pdf_content:
            logger.warning(f"PDF文件未找到，路径: {doc['file_path']}")
            raise HTTPException(status_code=404, detail="PDF文件未找到")

        logger.info(f"获取PDF文件成功，文件ID: {file_id}")
        # 对文件名进行URL编码，处理中文字符
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
