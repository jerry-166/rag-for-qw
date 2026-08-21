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


@router.get("/export")
async def export_audit_logs(
    format: str = "json",
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    kb_id: Optional[int] = None,
    request_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """导出审计日志（仅管理员；JSON/CSV，上限 10000 条）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可导出审计日志")
    from services.database import db as _db
    result = _db.query_audit_logs(
        user_id=user_id, action=action, resource_type=resource_type, kb_id=kb_id,
        request_id=request_id, start_time=start_time, end_time=end_time,
        page=1, page_size=10000,
    )
    items = result.get("items", [])
    if format == "csv":
        import csv, io
        from fastapi.responses import StreamingResponse
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "occurred_at", "user_id", "action", "resource_type",
                         "resource_id", "kb_id", "request_id", "client_ip", "detail"])
        import json as _json
        for it in items:
            writer.writerow([it.get("id"), it.get("occurred_at"), it.get("user_id"),
                             it.get("action"), it.get("resource_type"), it.get("resource_id"),
                             it.get("kb_id"), it.get("request_id"), it.get("client_ip"),
                             _json.dumps(it.get("detail"), ensure_ascii=False)])
        buf.seek(0)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=audit_export.csv"})
    return {"status": "success", "total": len(items), "items": items}


@router.get("/stats")
async def audit_stats(current_user=Depends(get_current_user)):
    """事件量分布概览（仅管理员；按 action 聚合 + 24h/7d 事件数）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看审计统计")
    try:
        by_action = db.fetchall('''
            SELECT action, COUNT(*) AS cnt
            FROM audit_log
            WHERE occurred_at >= now() - interval '7 days'
            GROUP BY action ORDER BY cnt DESC LIMIT 20
        ''')
        row_day = db.fetchone("SELECT COUNT(*) AS cnt FROM audit_log WHERE occurred_at >= now() - interval '24 hours'")
        row_total = db.fetchone("SELECT COUNT(*) AS cnt FROM audit_log")
        row_users = db.fetchone("SELECT COUNT(DISTINCT user_id) AS cnt FROM audit_log WHERE occurred_at >= now() - interval '24 hours'")
        return {
            "status": "success",
            "today_events": row_day["cnt"] if row_day else 0,
            "total_events": row_total["cnt"] if row_total else 0,
            "active_users_24h": row_users["cnt"] if row_users else 0,
            "top_actions_7d": by_action or [],
        }
    except Exception as e:
        logger.error(f"审计统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"审计统计失败: {e}")
