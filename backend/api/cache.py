"""缓存中心 API（文档 08 §3.1）— 仅管理员

可观测端点：stats / entries / entries/{key} / invalidate / clear
数据来源：CacheManager 进程内计数器（实时）+ PG query_embedding_cache（L1）。
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from services.auth import get_current_user
from services.database import db
from config import init_logger

logger = init_logger(__name__)
router = APIRouter()


def _require_admin(current_user):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看缓存中心")


@router.get("/stats")
async def cache_stats(current_user=Depends(get_current_user)):
    """各层计数器/命中率/内存估算/Redis INFO 摘要 + L1 PG 侧统计。"""
    _require_admin(current_user)
    from services.cache import get_cache_manager
    out = get_cache_manager().stats()
    try:
        row = db.fetchone(
            "SELECT COUNT(*) AS entries, COALESCE(SUM(hit_count),0) AS hits "
            "FROM query_embedding_cache")
        out["l1_entries"] = row["entries"] if row else 0
        out["l1_total_hits"] = row["hits"] if row else 0
    except Exception as e:
        out["l1_error"] = str(e)
    return {"status": "success", "stats": out}


@router.get("/entries")
async def cache_entries(layer: str = "mem", limit: int = 50,
                        current_user=Depends(get_current_user)):
    """条目明细（layer=mem/redis/l1）。"""
    _require_admin(current_user)
    from services.cache import get_cache_manager
    cm = get_cache_manager()
    if layer == "l1":
        try:
            rows = db.fetchall(
                "SELECT query_hash, left(query_text, 60) AS q, model, hit_count, last_hit_at "
                "FROM query_embedding_cache ORDER BY last_hit_at DESC LIMIT %s", (limit,))
            items = [{"query_hash": r["query_hash"], "query": r["q"],
                      "model": r["model"], "hits": r["hit_count"],
                      "last_hit_at": str(r["last_hit_at"])} for r in rows]
        except Exception as e:
            items = [{"error": str(e)}]
        return {"status": "success", "layer": "l1", "items": items}
    items = cm.entries(layer=layer, limit=limit)
    return {"status": "success", "layer": layer, "items": items}


@router.get("/entries/{key_hash}")
async def cache_entry_detail(key_hash: str, current_user=Depends(get_current_user)):
    """单条完整内容：Top-K chunk 明细 + 命中时间线。"""
    _require_admin(current_user)
    from services.cache import get_cache_manager
    detail = get_cache_manager().get_entry_detail(key_hash)
    if detail is None:
        raise HTTPException(status_code=404, detail="缓存条目不存在或已过期")
    return {"status": "success", "key": key_hash, **detail}


class InvalidateRequest(BaseModel):
    kb_id: int


@router.post("/invalidate")
async def cache_invalidate(body: InvalidateRequest,
                           current_user=Depends(get_current_user)):
    """按 KB 失效（bump cache_version，等于内容变更的手动版）。"""
    _require_admin(current_user)
    kb = db.get_knowledge_base(body.kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    new_v = db.bump_kb_cache_version(body.kb_id)
    from services.cache import get_cache_manager
    get_cache_manager().record_version_bump()
    from services.audit import audit
    audit.log("cache.invalidate", user_id=current_user["id"], kb_id=body.kb_id,
              detail={"via": "api", "new_version": new_v})
    return {"status": "success", "kb_id": body.kb_id, "new_version": new_v}


class ClearRequest(BaseModel):
    layer: str  # mem | redis | l1


@router.post("/clear")
async def cache_clear(body: ClearRequest, current_user=Depends(get_current_user)):
    """清空某层。"""
    _require_admin(current_user)
    if body.layer not in ("mem", "redis", "l1"):
        raise HTTPException(status_code=400, detail="layer 须为 mem/redis/l1")
    from services.cache import get_cache_manager
    get_cache_manager().clear(body.layer)
    from services.audit import audit
    audit.log("cache.clear", user_id=current_user["id"],
              detail={"layer": body.layer})
    return {"status": "success", "layer": body.layer}
