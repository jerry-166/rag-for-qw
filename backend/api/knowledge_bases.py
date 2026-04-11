from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from config import init_logger, settings
from services.database import db
from services.auth import get_current_user
from services.milvus_client import MilvusClient
from services.elasticsearch_client import es_client
from services.storage import get_storage
import shutil

logger = init_logger(__name__)
router = APIRouter()

# 知识库相关模型
class KnowledgeBaseCreate(BaseModel):
    kb_name: str
    description: str = None
    metadata: dict = None

class KnowledgeBaseUpdate(BaseModel):
    kb_name: str = None
    description: str = None

class KnowledgeBaseResponse(BaseModel):
    id: int
    kb_name: str
    user_id: int
    metadata: dict
    created_at: str


@router.post("")
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


@router.get("")
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


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: int, req: Request, current_user=Depends(get_current_user)):
    """删除知识库（统一调度：Milvus + ES + 文件存储 + temp/output + 数据库）"""
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

        # ---------- 1. 获取知识库下所有文档 ----------
        docs_query = "SELECT id, file_path, enhanced_md_path, user_id FROM document WHERE knowledge_base_id = %s"
        docs = db.fetchall(docs_query, (kb_id,))

        # ---------- 2. 删除 Milvus 向量数据 ----------
        milvus_client = req.app.state.get('milvus_client')
        if milvus_client:
            milvus_client.delete_data_by_knowledge_base(kb_id)
            logger.info(f"Milvus 数据删除完成，知识库ID: {kb_id}")

        # ---------- 3. 删除 ES 索引 ----------
        for doc in docs:
            try:
                # 使用文档实际 owner 的 user_id 作为 routing
                es_client.delete_document_chunks(doc["id"], doc["user_id"])
            except Exception as e:
                logger.warning(f"ES 索引删除失败（非致命），文档ID: {doc['id']}: {e}")
        logger.info(f"ES 索引删除完成，知识库ID: {kb_id}")

        # ---------- 4. 删除文件存储 ----------
        storage = get_storage()
        if storage:
            # 知识库的文件存储路径模式: "{user_id}/{kb_id}/{uuid}/..."
            # 可以直接删除整个 "{user_id}/{kb_id}/" 目录
            kb_storage_dir = f"{kb['user_id']}/{kb_id}"
            storage.delete_dir(kb_storage_dir)
            logger.info(f"文件存储删除完成: {kb_storage_dir}")

        # ---------- 5. 清理 temp 和 output 目录 ----------
        for doc in docs:
            if doc.get("file_path"):
                parts = doc["file_path"].split("/")
                if len(parts) >= 3:
                    uuid_part = parts[2]
                    # temp
                    temp_file = settings.TEMP_DIR / f"{uuid_part}.pdf"
                    if temp_file.exists():
                        temp_file.unlink()
                    # output
                    output_dir = settings.OUTPUT_DIR / uuid_part
                    if output_dir.exists():
                        shutil.rmtree(output_dir)

        # ---------- 6. 删除数据库记录 ----------
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


@router.put("/{kb_id}")
async def update_knowledge_base(kb_id: int, kb_update: KnowledgeBaseUpdate, current_user=Depends(get_current_user)):
    """更新知识库（名称和描述）"""
    logger.info(f"开始更新知识库，知识库ID: {kb_id}")
    try:
        # 获取知识库信息
        kb = db.get_knowledge_base(kb_id)
        if not kb:
            logger.warning(f"知识库未找到，知识库ID: {kb_id}")
            raise HTTPException(status_code=404, detail="知识库未找到")

        # 验证用户权限（只有知识库创建者可以更新）
        if kb["user_id"] != current_user["id"] and current_user["role"] != "admin":
            logger.warning(
                f"用户无权限更新知识库，用户: {current_user['username']}, 知识库ID: {kb_id}")
            raise HTTPException(status_code=403, detail="无权限更新该知识库")

        # 更新知识库
        update_data = {}
        if kb_update.kb_name is not None:
            update_data["kb_name"] = kb_update.kb_name
        if kb_update.description is not None:
            update_data["description"] = kb_update.description

        if update_data:
            result = db.update_knowledge_base(kb_id, update_data)
            if result:
                logger.info(f"知识库更新成功，知识库ID: {kb_id}")
                return {
                    "status": "success",
                    "message": "知识库更新成功"
                }
            else:
                raise HTTPException(status_code=500, detail="更新知识库失败")
        else:
            return {
                "status": "success",
                "message": "没有需要更新的内容"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新知识库失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新知识库失败: {str(e)}")
