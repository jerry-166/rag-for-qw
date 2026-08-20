"""审计中心查询 API（文档 07 基础版）

- GET /api/audit：分页查询审计日志；
- 权限：管理员（role=admin）全量；普通用户仅 user_id=自己。
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

from config import init_logger
from services.database import db
from services.auth import get_current_user

logger = init_logger(__name__)
router = APIRouter()

MAX_PAGE_SIZE = 200


@router.get("")
async def query_audit_logs(
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    kb_id: Optional[int] = None,
    request_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(get_current_user),
):
    """分页查询审计日志（管理员全量；普通用户仅自己的记录）"""
    try:
        # 权限过滤：非管理员强制只查自己
        is_admin = current_user.get("role") == "admin"
        if not is_admin:
            if user_id is not None and user_id != current_user["id"]:
                raise HTTPException(status_code=403, detail="无权限查询其他用户的审计记录")
            user_id = current_user["id"]

        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

        result = db.query_audit_logs(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            kb_id=kb_id,
            request_id=request_id,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
        )
        return {"status": "success", **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询审计日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询审计日志失败: {e}")
