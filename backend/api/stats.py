from fastapi import APIRouter, HTTPException, Depends
import time

from config import init_logger
from services.database import db
from services.auth import get_current_user

logger = init_logger(__name__)
router = APIRouter()


@router.get("/overview")
async def get_stats_overview(current_user=Depends(get_current_user)):
    """获取统计概览"""
    try:
        start_time = time.time()
        logger.info(f"开始获取统计概览，用户: {current_user['username']}")
        
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
