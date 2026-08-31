"""FAQ 记忆与知识协作 API（文档 06，Stage 3 Phase 1）。

- FAQ 管理：列表 / 升格 / 降级 / 删除
- 补全入口：全局（落默认私有 KB）或指定 KB（按 fork/PR 路径判定）
- KB 协作：分享 / 取消分享 / 克隆（fork）
- FAQ PR：提交 / 列表 / 库主审核（merge / reject）
"""

import asyncio
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List

from config import init_logger
from services.auth import get_current_user
from services.database import db
from services.faq_service import faq_service

logger = init_logger(__name__)
router = APIRouter()


# ---------- 请求模型 ----------
class SupplementRequest(BaseModel):
    question: str
    answer: str
    kb_id: Optional[int] = None      # None = 全局入口（落默认私有 KB）


class ShareRequest(BaseModel):
    kb_id: int
    username: str                    # 分享给哪个用户
    can_write_directly: bool = False


class UnshareRequest(BaseModel):
    kb_id: int
    username: str


class CloneRequest(BaseModel):
    new_name: Optional[str] = None


class PRSubmitRequest(BaseModel):
    target_kb_id: int
    question: str
    answer: str
    source_faq_id: Optional[int] = None   # 从我的 KB 里某条 FAQ 提 PR 回上游时携带


class PRReviewRequest(BaseModel):
    note: Optional[str] = None


def _check_kb_owner(kb_id: int, user_id: int):
    kb = db.get_knowledge_base(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="只有知识库所有者可执行此操作")
    return kb


# ---------- FAQ 管理 ----------
@router.get("/faq")
async def list_faqs(kb_id: Optional[int] = None, status: Optional[str] = None,
                    scope: Optional[str] = None, page: int = 1, page_size: int = 20,
                    current_user=Depends(get_current_user)):
    """FAQ 列表。scope=mine 看自己提交的；不传 kb_id 时看自己名下 KB 的。"""
    if kb_id is not None:
        if not db.check_kb_permission(current_user["id"], kb_id):
            raise HTTPException(status_code=403, detail="无权限访问该知识库")
        return db.list_faqs(kb_id=kb_id, status=status, page=page, page_size=page_size)
    if scope == "mine":
        return db.list_faqs(submitter_id=current_user["id"], status=status,
                            page=page, page_size=page_size)
    return db.list_faqs(owner_id=current_user["id"], status=status,
                        page=page, page_size=page_size)


@router.post("/faq/{faq_id}/promote")
async def promote_faq(faq_id: int, current_user=Depends(get_current_user)):
    """手动升格（显式触发路径）"""
    faq = db.get_faq(faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    _check_kb_owner(faq["kb_id"], current_user["id"])
    if not db.promote_faq(faq_id):
        raise HTTPException(status_code=500, detail="升格失败")
    from services.audit import audit
    audit.log("faq.promote", user_id=current_user["id"], resource_type="faq",
              resource_id=faq_id, kb_id=faq["kb_id"], detail={"via": "manual"})
    return {"status": "success"}


@router.post("/faq/{faq_id}/demote")
async def demote_faq(faq_id: int, current_user=Depends(get_current_user)):
    faq = db.get_faq(faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    _check_kb_owner(faq["kb_id"], current_user["id"])
    if not db.demote_faq(faq_id):
        raise HTTPException(status_code=500, detail="降级失败")
    from services.audit import audit
    audit.log("faq.demote", user_id=current_user["id"], resource_type="faq",
              resource_id=faq_id, kb_id=faq["kb_id"])
    return {"status": "success"}


@router.delete("/faq/{faq_id}")
async def delete_faq(faq_id: int, current_user=Depends(get_current_user)):
    faq = db.get_faq(faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    _check_kb_owner(faq["kb_id"], current_user["id"])
    if not db.delete_faq(faq_id):
        raise HTTPException(status_code=500, detail="删除失败")
    try:
        from services.milvus_client import MilvusClient
        MilvusClient().delete_faq_vector(faq_id)
    except Exception as e:
        logger.warning(f"FAQ 向量删除失败（PG 已删）: {e}")
    from services.audit import audit
    audit.log("faq.delete", user_id=current_user["id"], resource_type="faq",
              resource_id=faq_id, kb_id=faq["kb_id"],
              detail={"question": faq["question"][:200]})
    return {"status": "success"}


# ---------- 补全入口 ----------
@router.post("/faq/supplement")
async def supplement(req: SupplementRequest, current_user=Depends(get_current_user)):
    """检索失败后的知识补全（全局或 KB 级，写入路径由 fork/PR 规则判定）"""
    if not req.question.strip() or not req.answer.strip():
        raise HTTPException(status_code=400, detail="问题与答案均不能为空")
    if req.kb_id is not None and not db.check_kb_permission(current_user["id"], req.kb_id):
        raise HTTPException(status_code=403, detail="无权限访问该知识库")
    result = await faq_service.supplement(
        question=req.question.strip(), answer=req.answer.strip(),
        user_id=current_user["id"], kb_id=req.kb_id)
    if result.get("action") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


# ---------- KB 分享 / 克隆 ----------
@router.post("/kb/share")
async def share_kb(req: ShareRequest, current_user=Depends(get_current_user)):
    _check_kb_owner(req.kb_id, current_user["id"])
    target = db.fetchone("SELECT id FROM users WHERE username = %s", (req.username,))
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    if target["id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="不能分享给自己")
    if not db.share_kb(req.kb_id, target["id"], current_user["id"], req.can_write_directly):
        raise HTTPException(status_code=500, detail="分享失败")
    from services.audit import audit
    audit.log("kb.share", user_id=current_user["id"], resource_type="knowledge_base",
              resource_id=req.kb_id, kb_id=req.kb_id,
              detail={"shared_to": req.username,
                      "can_write_directly": req.can_write_directly})
    return {"status": "success"}


@router.post("/kb/unshare")
async def unshare_kb(req: UnshareRequest, current_user=Depends(get_current_user)):
    _check_kb_owner(req.kb_id, current_user["id"])
    target = db.fetchone("SELECT id FROM users WHERE username = %s", (req.username,))
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    if not db.unshare_kb(req.kb_id, target["id"]):
        raise HTTPException(status_code=500, detail="取消分享失败")
    from services.audit import audit
    audit.log("kb.unshare", user_id=current_user["id"], resource_type="knowledge_base",
              resource_id=req.kb_id, kb_id=req.kb_id, detail={"unshared_from": req.username})
    return {"status": "success"}


@router.get("/kb/{kb_id}/shares")
async def list_kb_shares(kb_id: int, current_user=Depends(get_current_user)):
    _check_kb_owner(kb_id, current_user["id"])
    return {"items": db.get_kb_shares(kb_id)}


@router.post("/kb/{kb_id}/clone")
async def clone_kb(kb_id: int, req: CloneRequest = None,
                   current_user=Depends(get_current_user)):
    """克隆（fork）KB 为我的私有副本——可读即可克隆"""
    if not db.check_kb_permission(current_user["id"], kb_id):
        raise HTTPException(status_code=403, detail="无权限访问该知识库")
    # 克隆 = PG 全量复制 + Milvus 向量搬运 + BM25 重建，大库可能耗时数十秒：
    # 放线程池执行，避免阻塞事件循环导致其他请求排队（参考 reranker.py run_in_executor 先例）
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, faq_service.clone_kb, kb_id, current_user["id"],
        req.new_name if req else None)
    if result.get("action") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


# ---------- FAQ PR ----------
@router.post("/faq-pr")
async def submit_pr(req: PRSubmitRequest, current_user=Depends(get_current_user)):
    """显式提交 FAQ 到共享 KB（走库主审核）"""
    if not db.check_kb_permission(current_user["id"], req.target_kb_id):
        raise HTTPException(status_code=403, detail="无权限访问目标知识库")
    target = db.get_knowledge_base(req.target_kb_id)
    if target["user_id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="自己的知识库请直接补全，无需 PR")
    pr_id = db.create_faq_pr(
        source_faq_id=req.source_faq_id, source_kb_id=None,
        target_kb_id=req.target_kb_id, submitted_by=current_user["id"],
        question=req.question, answer=req.answer)
    if not pr_id:
        raise HTTPException(status_code=500, detail="PR 创建失败")
    from services.audit import audit
    audit.log("faq_pr.submit", user_id=current_user["id"], resource_type="faq_pr",
              resource_id=pr_id, kb_id=req.target_kb_id,
              detail={"question": req.question[:200], "explicit": True})
    return {"status": "success", "pr_id": pr_id}


@router.get("/faq-pr")
async def list_prs(target_kb_id: Optional[int] = None, mine: bool = False,
                   status: Optional[str] = None, page: int = 1, page_size: int = 20,
                   current_user=Depends(get_current_user)):
    """PR 列表：mine=true 看我提交的；否则看我名下 KB 收到的"""
    if mine:
        return db.list_faq_prs(submitted_by=current_user["id"], status=status,
                               page=page, page_size=page_size)
    if target_kb_id is not None:
        _check_kb_owner(target_kb_id, current_user["id"])
        return db.list_faq_prs(target_kb_id=target_kb_id, status=status,
                               page=page, page_size=page_size)
    # 我名下所有 KB 收到的 open PR
    my_kbs = [k["id"] for k in db.get_user_knowledge_bases(current_user["id"])
              if k["user_id"] == current_user["id"]]
    if not my_kbs:
        return {"total": 0, "page": page, "page_size": page_size, "items": []}
    # P1-7：原实现逐 KB 查询（N+1）且 page_size=100 截断破坏分页，改为单次 ANY 查询
    return db.list_faq_prs(target_kb_ids=my_kbs, status=status or "open",
                           page=page, page_size=page_size)


@router.post("/faq-pr/{pr_id}/merge")
async def merge_pr(pr_id: int, req: PRReviewRequest = None,
                   current_user=Depends(get_current_user)):
    result = await faq_service.merge_pr(pr_id, current_user["id"],
                                        req.note if req else None)
    if result.get("action") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.post("/faq-pr/{pr_id}/reject")
async def reject_pr(pr_id: int, req: PRReviewRequest = None,
                    current_user=Depends(get_current_user)):
    result = faq_service.reject_pr(pr_id, current_user["id"],
                                   req.note if req else None)
    if result.get("action") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result
