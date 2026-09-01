"""自进化记忆服务（文档 06，Stage 3 Phase 1）。

核心闭环：检索失败 → 用户补全 → 种 candidate → 命中累计热度 → 达阈值蒸馏升格 active → 直返。

关键机制：
- 召回：Milvus faq 集合按「可见 KB 范围」检索 → PG 查状态（PG 为权威）；
  active 直返（阈值 + LLM 二次确认），candidate 只累计命中不直返。
- 写入路径（GitHub 式 fork/PR）：
  自己的 KB（含克隆版）→ 直接种 candidate，阈值按归属快照（私有 2 / 自有共享 3）；
  他人共享 KB → 有直写权走阈值路径，无直写权创建 faq_pr 走库主审核。
- 全局入口补全永远落到用户默认私有 KB（DEFAULT_PERSONAL_KB_ID 语义：
  取 metadata.is_default_personal 的 KB，不存在则自动创建「我的知识库」）。
"""

from __future__ import annotations

import time
from typing import List, Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from config import settings, get_runtime, init_logger
from services.audit import audit
from services.database import db

logger = init_logger(__name__)

DEFAULT_PERSONAL_KB_NAME = "我的知识库"


class FAQService:
    def __init__(self):
        self._embedding = None
        self._chat = None

    # ---------- 懒加载模型（与 document_processor 同配置） ----------
    @property
    def embedding(self) -> OpenAIEmbeddings:
        if self._embedding is None:
            self._embedding = OpenAIEmbeddings(
                model=get_runtime("EMBEDDING_MODEL", settings.EMBEDDING_MODEL),
                api_key=get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY),
                base_url=get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL),
            )
        return self._embedding

    @property
    def chat(self) -> ChatOpenAI:
        if self._chat is None:
            self._chat = ChatOpenAI(
                model=get_runtime("DEFAULT_MODEL", settings.DEFAULT_MODEL),
                api_key=get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY),
                base_url=get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL),
                temperature=0,
                max_tokens=300,
            )
        return self._chat

    # ---------- 可见范围 ----------
    def visible_kb_ids(self, user_id: int) -> List[int]:
        """用户可见 KB（自有 + 被分享的），FAQ 全局检索的读取视野。"""
        kbs = db.get_user_knowledge_bases(user_id)
        return [k["id"] for k in kbs]

    def get_default_personal_kb_id(self, user_id: int) -> Optional[int]:
        """用户默认私有 KB（不存在则自动创建），全局入口补全的落点。"""
        rows = db.fetchall(
            "SELECT id, metadata FROM knowledge_base WHERE user_id = %s", (user_id,))
        for r in rows:
            meta = r.get("metadata") or {}
            if isinstance(meta, str):
                import json as _json
                try:
                    meta = _json.loads(meta)
                except Exception:
                    meta = {}
            if meta.get("is_default_personal"):
                return r["id"]
        # 创建默认私有 KB
        kb_id = db.add_knowledge_base(
            user_id, DEFAULT_PERSONAL_KB_NAME,
            description="全局检索补全的默认落点（自动创建）",
            metadata={"is_default_personal": True})
        if kb_id:
            logger.info(f"为用户 {user_id} 创建默认私有 KB: {kb_id}")
        return kb_id

    # ---------- 写入路径判定（fork/PR） ----------
    def resolve_write_path(self, user_id: int, kb_id: int) -> dict:
        """判定补全写入路径。

        返回 {"mode": "direct"|"pr", "threshold": int, "reason": str}
        - direct：自己的 KB（含克隆版）/ 他人共享但有直写权 → 阈值候选路径
        - pr：他人共享 KB 且无直写权 → 库主审核
        """
        kb = db.get_knowledge_base(kb_id)
        if not kb:
            return {"mode": "direct", "threshold": get_runtime(
                "FAQ_DISTILL_THRESHOLD_PRIVATE", settings.FAQ_DISTILL_THRESHOLD_PRIVATE),
                "reason": "kb_not_found_fallback"}
        if kb["user_id"] == user_id:
            # 自己的 KB：是否已分享出去（共享 KB 阈值更严）
            shared = bool(db.get_kb_shares(kb_id))
            threshold = get_runtime(
                "FAQ_DISTILL_THRESHOLD_SHARED", settings.FAQ_DISTILL_THRESHOLD_SHARED
            ) if shared else get_runtime(
                "FAQ_DISTILL_THRESHOLD_PRIVATE", settings.FAQ_DISTILL_THRESHOLD_PRIVATE)
            return {"mode": "direct", "threshold": threshold,
                    "reason": "own_shared" if shared else "own_private"}
        # 他人共享 KB
        if db.can_write_directly(user_id, kb_id):
            return {"mode": "direct",
                    "threshold": get_runtime("FAQ_DISTILL_THRESHOLD_SHARED",
                                             settings.FAQ_DISTILL_THRESHOLD_SHARED),
                    "reason": "shared_direct_write"}
        return {"mode": "pr", "threshold": 0, "reason": "shared_review_required"}

    # ---------- FAQ 召回（检索前置层） ----------
    async def try_faq_hit(self, query: str, user_id: int,
                          kb_id: Optional[int] = None) -> Optional[dict]:
        """FAQ 前置召回：命中 active 且通过二次确认 → 直返；命中 candidate → 累计热度不直返。

        返回 {"faq_id", "question", "answer", "score", "promoted": bool} 或 None。
        """
        from services.milvus_client import MilvusClient

        kb_ids = [kb_id] if kb_id else self.visible_kb_ids(user_id)
        if not kb_ids:
            return None

        try:
            query_vec = await self.embedding.aembed_query(query)
        except Exception as e:
            logger.warning(f"FAQ 召回 embedding 失败，跳过前置层: {e}")
            return None

        client = MilvusClient()
        hits = client.search_faq(query_vec, kb_ids, limit=3)
        if not hits:
            return None

        threshold = get_runtime("FAQ_HIT_THRESHOLD", settings.FAQ_HIT_THRESHOLD)
        best = hits[0]
        if best["score"] < threshold:
            return None

        faq = db.get_faq(best["pg_faq_id"])
        if not faq:
            return None

        # 命中即累计热度（candidate 与 active 都累计）
        half_life = get_runtime("FAQ_HEAT_HALF_LIFE_DAYS", settings.FAQ_HEAT_HALF_LIFE_DAYS)
        updated = db.increment_faq_hit(faq["id"], half_life)
        promoted = False

        if faq["status"] == "candidate":
            # candidate 不直返；达阈值 → 蒸馏升格
            if updated and updated["hit_count"] >= faq["distill_threshold"]:
                promoted = await self.distill_and_promote(faq["id"])
            logger.info(f"FAQ candidate 命中（id={faq['id']}，hit={updated and updated['hit_count']}），"
                        f"不直返{'，已升格' if promoted else ''}")
            return None

        # active：LLM 二次确认后直返
        if not await self._confirm_answer(query, faq["answer"]):
            logger.info(f"FAQ active 命中但二次确认未通过（id={faq['id']}），降级正常检索")
            return None

        audit.log("faq.hit", user_id=user_id, resource_type="faq",
                  resource_id=faq["id"], kb_id=faq["kb_id"],
                  detail={"question": query[:200], "score": round(best["score"], 4),
                          "hit_count": updated and updated["hit_count"]})
        return {"faq_id": faq["id"], "question": faq["question"],
                "answer": faq["answer"], "score": best["score"], "promoted": False}

    async def _confirm_answer(self, query: str, answer: str) -> bool:
        """二次确认：FAQ 答案是否准确回答了问题（短判断调用，宁漏勿错）。"""
        try:
            prompt = (
                "判断下面的候选答案是否准确、完整地回答了用户问题。\n"
                f"用户问题：{query}\n候选答案：{answer}\n"
                "只回答一个字：是 或 否。"
            )
            resp = await self.chat.ainvoke(prompt)
            text = resp.content if hasattr(resp, "content") else str(resp)
            return text.strip().startswith("是")
        except Exception as e:
            logger.warning(f"FAQ 二次确认调用失败（保守不直返）: {e}")
            return False

    # ---------- 补全写入 ----------
    async def supplement(self, question: str, answer: str, user_id: int,
                         kb_id: Optional[int] = None) -> dict:
        """用户补全入口（全局或 KB 级）。

        返回 {"action": "created"|"merged"|"pr_submitted"|"promoted", ...}。
        """
        from services.milvus_client import MilvusClient

        # 目标 KB：未指定 → 默认私有 KB（全局入口永不直接写共享 KB）
        if kb_id is None:
            kb_id = self.get_default_personal_kb_id(user_id)
            if kb_id is None:
                return {"action": "error", "message": "无法确定默认私有知识库"}

        path = self.resolve_write_path(user_id, kb_id)

        # PR 路径：他人共享 KB 且无直写权 → 提交审核，不直接写库
        if path["mode"] == "pr":
            pr_id = db.create_faq_pr(
                source_faq_id=None, source_kb_id=None, target_kb_id=kb_id,
                submitted_by=user_id, question=question, answer=answer)
            # P1-2：PR 创建失败（返回 None）时明确报错，不再伪成功
            if pr_id is None:
                logger.error(f"隐式 PR 创建失败: user={user_id}, target_kb={kb_id}")
                return {"action": "error", "message": "知识条目提交失败（PR 创建失败），请稍后重试"}
            audit.log("faq_pr.submit", user_id=user_id, resource_type="faq_pr",
                      resource_id=pr_id, kb_id=kb_id,
                      detail={"question": question[:200]})
            return {"action": "pr_submitted", "pr_id": pr_id, "kb_id": kb_id,
                    "message": "已提交知识库所有者审核，通过后生效"}

        # 直写路径：判重（同 KB 相似 ≥0.95 → 聚合 hit_count）
        try:
            query_vec = await self.embedding.aembed_query(question)
        except Exception as e:
            logger.error(f"补全 embedding 失败: {e}")
            return {"action": "error", "message": str(e)}

        client = MilvusClient()
        dedup_threshold = get_runtime("FAQ_DEDUP_SIMILARITY", settings.FAQ_DEDUP_SIMILARITY)
        dup_hits = client.search_faq(query_vec, [kb_id], limit=1)

        if dup_hits and dup_hits[0]["score"] >= dedup_threshold:
            # 聚合到已有记忆
            faq = db.get_faq(dup_hits[0]["pg_faq_id"])
            if faq:
                half_life = get_runtime("FAQ_HEAT_HALF_LIFE_DAYS",
                                        settings.FAQ_HEAT_HALF_LIFE_DAYS)
                updated = db.increment_faq_hit(faq["id"], half_life)
                promoted = False
                if (faq["status"] == "candidate" and updated
                        and updated["hit_count"] >= faq["distill_threshold"]):
                    promoted = await self.distill_and_promote(faq["id"])
                audit.log("faq.aggregate", user_id=user_id, resource_type="faq",
                          resource_id=faq["id"], kb_id=kb_id,
                          detail={"hit_count": updated and updated["hit_count"],
                                  "promoted": promoted})
                # ── 文档 08：FAQ 聚合（热度变化可能触发升格）→ bump ──
                from services.cache import bump_kb_cache
                bump_kb_cache(kb_id, "faq_aggregate", user_id)
                return {"action": "promoted" if promoted else "merged",
                        "faq_id": faq["id"], "kb_id": kb_id,
                        "hit_count": updated and updated["hit_count"],
                        "message": "已有相似记忆，热度已累加" + ("，已升格为正式知识" if promoted else "")}

        # 新增 candidate
        kb = db.get_knowledge_base(kb_id)
        faq_id = db.add_faq(
            kb_id=kb_id, owner_id=kb["user_id"], submitter_id=user_id,
            question=question, answer=answer, source="supplement",
            status="candidate", distill_threshold=path["threshold"])
        if not faq_id:
            return {"action": "error", "message": "FAQ 写入失败"}
        client.insert_faq_vector(faq_id, kb_id, question, query_vec)

        audit.log("faq.candidate_create", user_id=user_id, resource_type="faq",
                  resource_id=faq_id, kb_id=kb_id,
                  detail={"question": question[:200], "threshold": path["threshold"],
                          "write_path": path["reason"]})
        # ── 文档 08：FAQ 补全写回 → bump ──
        from services.cache import bump_kb_cache
        bump_kb_cache(kb_id, "faq_writeback", user_id)
        return {"action": "created", "faq_id": faq_id, "kb_id": kb_id,
                "threshold": path["threshold"],
                "message": f"已记录（命中 {path['threshold']} 次后自动成为正式知识）"}

    # ---------- 蒸馏升格 ----------
    async def distill_and_promote(self, faq_id: int) -> bool:
        """candidate → active：LLM 将「用户补全原文 + 相关 chunk 上下文」蒸馏为结构化答案。"""
        faq = db.get_faq(faq_id)
        if not faq or faq["status"] != "candidate":
            return False
        try:
            # 相关 chunk 上下文（向量检索该 KB 原文，失败则不致命）
            context = ""
            try:
                from services.milvus_client import MilvusClient
                qv = await self.embedding.aembed_query(faq["question"])
                client = MilvusClient()
                chunks = client.query(faq["question"], limit=3,
                                      metadata_filter={"knowledge_base_id": faq["kb_id"]},
                                      retrieval_mode="native")
                if chunks:
                    context = "\n\n".join(
                        (c.get("chunk_text") or "")[:500] for c in chunks[:3])
            except Exception as ce:
                logger.warning(f"蒸馏取上下文失败（仅用原文蒸馏）: {ce}")

            prompt = (
                "你是知识蒸馏助手。把下面的用户补充内容整理为一条结构化、准确、可复用的知识问答。\n"
                "要求：答案完整准确、去除口语化表达、保留关键事实；如有相关上下文请核对一致性。\n"
                f"问题：{faq['question']}\n"
                f"用户补充的原始答案：{faq['answer']}\n"
                + (f"相关知识库上下文：\n{context}\n" if context else "")
                + "只输出蒸馏后的答案文本，不要输出其他内容。"
            )
            resp = await self.chat.ainvoke(prompt)
            distilled = resp.content if hasattr(resp, "content") else str(resp)
            distilled = distilled.strip() or faq["answer"]

            old_answer = faq["answer"]
            ok = db.promote_faq(faq_id, answer=distilled)
            if ok:
                audit.log("faq.promote", user_id=faq.get("submitter_id"),
                          resource_type="faq", resource_id=faq_id,
                          kb_id=faq["kb_id"],
                          detail={"via": "threshold", "hit_count": faq["hit_count"],
                                  "before": old_answer[:300], "after": distilled[:300]})
                # ── 文档 08：FAQ 升格（答案蒸馏变化）→ bump ──
                from services.cache import bump_kb_cache
                bump_kb_cache(faq["kb_id"], "faq_promote", faq.get("submitter_id"))
            return ok
        except Exception as e:
            logger.error(f"FAQ 蒸馏升格失败: {e}")
            return False

    # ---------- PR 审核 ----------
    async def merge_pr(self, pr_id: int, reviewer_id: int, note: str = None) -> dict:
        """库主合并 PR：问答以 active 直接生效（人工审核 > 阈值闸门）。"""
        pr = db.get_faq_pr(pr_id)
        if not pr or pr["status"] != "open":
            return {"action": "error", "message": "PR 不存在或已处理"}
        kb = db.get_knowledge_base(pr["target_kb_id"])
        if not kb or kb["user_id"] != reviewer_id:
            return {"action": "error", "message": "只有知识库所有者可审核"}

        if not db.resolve_faq_pr(pr_id, "merged", reviewer_id, note):
            return {"action": "error", "message": "PR 状态更新失败"}

        faq_id = db.add_faq(
            kb_id=pr["target_kb_id"], owner_id=reviewer_id,
            submitter_id=pr["submitted_by"], question=pr["question"],
            answer=pr["answer"], source="pr_merge", status="active",
            distill_threshold=1)  # active 不再走阈值
        if faq_id:
            try:
                from services.milvus_client import MilvusClient
                qv = await self.embedding.aembed_query(pr["question"])
                MilvusClient().insert_faq_vector(faq_id, pr["target_kb_id"],
                                                 pr["question"], qv)
            except Exception as e:
                logger.warning(f"PR 合并后向量插入失败（可重建）: {e}")

        audit.log("faq_pr.merge", user_id=reviewer_id, resource_type="faq_pr",
                  resource_id=pr_id, kb_id=pr["target_kb_id"],
                  detail={"submitted_by": pr["submitted_by"], "faq_id": faq_id,
                          "note": note})
        # ── 文档 08：PR 合并生效（新 FAQ 写入目标 KB）→ bump ──
        from services.cache import bump_kb_cache
        bump_kb_cache(pr["target_kb_id"], "faq_pr_merge", reviewer_id)
        return {"action": "merged", "pr_id": pr_id, "faq_id": faq_id}

    def reject_pr(self, pr_id: int, reviewer_id: int, note: str = None) -> dict:
        pr = db.get_faq_pr(pr_id)
        if not pr or pr["status"] != "open":
            return {"action": "error", "message": "PR 不存在或已处理"}
        kb = db.get_knowledge_base(pr["target_kb_id"])
        if not kb or kb["user_id"] != reviewer_id:
            return {"action": "error", "message": "只有知识库所有者可审核"}
        if not db.resolve_faq_pr(pr_id, "rejected", reviewer_id, note):
            return {"action": "error", "message": "PR 状态更新失败"}
        audit.log("faq_pr.reject", user_id=reviewer_id, resource_type="faq_pr",
                  resource_id=pr_id, kb_id=pr["target_kb_id"],
                  detail={"submitted_by": pr["submitted_by"], "note": note})
        return {"action": "rejected", "pr_id": pr_id}

    # ---------- KB 克隆（fork） ----------
    def clone_kb(self, source_kb_id: int, user_id: int,
                 new_name: str = None) -> dict:
        """快照克隆：PG 全量复制 + Milvus 向量搬运。"""
        result = db.clone_knowledge_base(source_kb_id, user_id, new_name)
        if not result:
            return {"action": "error", "message": "克隆失败（源知识库不存在或复制出错）"}
        new_kb_id = result["kb_id"]

        vector_report = {}
        try:
            from services.milvus_client import MilvusClient
            vector_report = MilvusClient().clone_kb_vectors(
                source_kb_id, new_kb_id, result["doc_map"],
                result["chunk_map"], result["faq_map"])
        except Exception as e:
            logger.warning(f"克隆向量搬运失败（PG 数据完整，可重建）: {e}")

        # BM25 关键词索引：克隆的 chunk 需入内存索引（PG 有数据但
        # load_from_database 只在启动时执行，克隆后关键词检索会空）
        try:
            from services.bm25_client import get_search_client
            chunks = db.get_document_chunks_by_ids(list(result["chunk_map"].values()))
            owner = db.get_knowledge_base(new_kb_id) or {}
            for ch in chunks:
                ch.setdefault("user_id", owner.get("user_id", user_id))
                ch.setdefault("knowledge_base_id", new_kb_id)
            get_search_client().bulk_index_chunks(chunks)
            logger.info(f"克隆 BM25 索引完成: kb={new_kb_id}, {len(chunks)} 条 chunk")
        except Exception as e:
            logger.warning(f"克隆 BM25 索引失败（重启后由 PG 加载兜底）: {e}")

        audit.log("kb.clone", user_id=user_id, resource_type="knowledge_base",
                  resource_id=new_kb_id, kb_id=new_kb_id,
                  detail={"source_kb_id": source_kb_id, "new_name": new_name,
                          "docs": len(result["doc_map"]), "chunks": len(result["chunk_map"]),
                          "faqs": len(result["faq_map"]), "vectors": vector_report})
        return {"action": "cloned", "kb_id": new_kb_id,
                "source_kb_id": source_kb_id, "vectors": vector_report}


faq_service = FAQService()
