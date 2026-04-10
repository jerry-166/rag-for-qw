from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Optional
import shutil
from pathlib import Path

from config import init_logger, settings
from services.database import db
from services.auth import get_current_user
from services.storage import get_storage
from services.elasticsearch_client import es_client

logger = init_logger(__name__)
router = APIRouter()


@router.get("/pending")
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


@router.get("")
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
        storage = get_storage()
        for doc in docs:
            file_size = None
            if doc.get("file_path"):
                try:
                    # 从存储中获取文件大小
                    file_size = storage.get_file_size(doc["file_path"])
                except Exception as e:
                    logger.warning(f"获取文件大小失败，路径: {doc['file_path']}, 错误: {str(e)}")
            
            document_list.append({
                "file_id": doc["id"],
                "filename": doc["filename"],
                "file_size": file_size,
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


@router.get("/{file_id}/preview")
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
        storage = get_storage()
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
            "formulas_count": doc.get("formulas_count"),
            "upload_time": doc.get("upload_time"),
            "split_time": doc.get("split_time"),
            "generate_time": doc.get("generate_time"),
            "import_time": doc.get("import_time")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文档预览失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取文档预览失败: {str(e)}")


@router.delete("/{file_id}")
async def delete_document(file_id: str, request: Request, current_user=Depends(get_current_user)):
    """删除文档（统一调度：Milvus + ES + 文件存储 + temp/output + 数据库）"""
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

        # ---------- 1. 删除 Milvus 向量数据 ----------
        milvus_client = request.app.state.get('milvus_client')
        if milvus_client:
            milvus_client.delete_data_by_document(file_id)
            logger.info(f"Milvus 数据删除完成，文件ID: {file_id}")

        # ---------- 2. 删除 ES 索引 ----------
        try:
            es_client.delete_document_chunks(file_id, current_user["id"])
            logger.info(f"ES 索引删除完成，文件ID: {file_id}")
        except Exception as e:
            logger.warning(f"ES 索引删除失败（非致命）: {e}")

        # ---------- 3. 删除文件存储（doc_storage 下的文档目录） ----------
        storage = get_storage()
        if storage and doc.get("file_path"):
            # file_path 格式: "{user_id}/{kb_id}/{uuid}/original.pdf"
            # 提取文档目录前缀: "{user_id}/{kb_id}/{uuid}"
            parts = doc["file_path"].split("/")
            if len(parts) >= 3:
                doc_dir = "/".join(parts[:3])  # e.g. "1/2/abc-uuid"
                storage.delete_dir(doc_dir)
                logger.info(f"文件存储删除完成: {doc_dir}")
            else:
                # 兜底：逐个删文件
                if doc.get("file_path"):
                    storage.delete(doc["file_path"])
                if doc.get("enhanced_md_path"):
                    storage.delete(doc["enhanced_md_path"])

        # ---------- 4. 清理 temp 和 output 目录 ----------
        # temp 和 output 都用 UUID 命名，UUID 嵌入在 file_path 第3段
        # file_path 格式: "{user_id}/{kb_id}/{uuid}/original.pdf"
        if doc.get("file_path"):
            parts = doc["file_path"].split("/")
            if len(parts) >= 3:
                uuid_part = parts[2]
                # temp: "temp/{uuid}.pdf"
                temp_file = settings.TEMP_DIR / f"{uuid_part}.pdf"
                if temp_file.exists():
                    temp_file.unlink()
                    logger.info(f"临时文件删除完成: {temp_file}")
                # output: "output/{uuid}/"
                output_dir = settings.OUTPUT_DIR / uuid_part
                if output_dir.exists():
                    shutil.rmtree(output_dir)
                    logger.info(f"输出目录删除完成: {output_dir}")

        # ---------- 5. 删除数据库记录（子问题/摘要/chunk/document） ----------
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
