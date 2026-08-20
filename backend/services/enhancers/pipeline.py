"""增强器流水线：按启用集装配执行 + 启用集三级解析（文档 03 §3.2/§3.3）。

装配规则：
  - {sub_question, summary} 双开  → CombinedEnhancer（合并 prompt，token 成本最优，= 迁移前默认行为）
  - 只开 summary                  → SummaryEnhancer（独立精简 prompt）
  - 只开 sub_question             → SubQuestionEnhancer（独立精简 prompt）
  - 全关                          → no-op（generate 阶段秒回，纯原文 RAG）

启用集三级解析：请求参数 > 知识库配置（kb.enhancers JSONB，NULL=跟随全局）> 全局配置。
"""

from __future__ import annotations

from typing import List, Optional, Set

from config import settings, get_runtime, init_logger
from services.enhancers.base import Enhancer
from services.enhancers.combined import CombinedEnhancer
from services.enhancers.sub_question import SubQuestionEnhancer
from services.enhancers.summary import SummaryEnhancer

logger = init_logger(__name__)

VALID_ENHANCERS = {"sub_question", "summary"}


def _to_enabled_set(raw) -> Optional[Set[str]]:
    """把 str（逗号分隔）/ list / None 解析为启用集；None 表示未指定。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in raw if str(p).strip()]
    return {p for p in parts if p in VALID_ENHANCERS}


def resolve_enabled_enhancers(
    kb_id: Optional[int] = None,
    override=None,
) -> Set[str]:
    """启用集三级解析（文档 03 §3.3）。

    - override（请求级，显式传入，含空集）优先；
    - KB 表 enhancers 列非 NULL 时次之（空数组 = 该 KB 显式全关）；
    - 否则用全局配置 ENABLED_ENHANCERS（默认 "sub_question,summary"）。
    """
    enabled = _to_enabled_set(override)
    if enabled is not None:
        return enabled

    if kb_id is not None:
        try:
            from services.database import db
            kb = db.get_knowledge_base(kb_id)
            if kb is not None and kb.get("enhancers") is not None:
                enabled = _to_enabled_set(kb["enhancers"])
                if enabled is not None:
                    return enabled
        except Exception as e:
            logger.warning(f"读取 KB {kb_id} enhancers 配置失败，回落全局配置: {e}")

    enabled = _to_enabled_set(get_runtime("ENABLED_ENHANCERS", settings.ENABLED_ENHANCERS))
    return enabled if enabled is not None else set()


class EnhancerPipeline:
    """按启用集装配增强器并执行。"""

    def __init__(self, enabled: Set[str], chat_model):
        self.enabled = set(enabled)
        self.enhancer: Optional[Enhancer] = self._select(chat_model)

    def _select(self, chat_model) -> Optional[Enhancer]:
        if {"sub_question", "summary"} <= self.enabled:
            return CombinedEnhancer(chat_model)
        if "summary" in self.enabled:
            return SummaryEnhancer(chat_model)
        if "sub_question" in self.enabled:
            return SubQuestionEnhancer(chat_model)
        return None  # 全关：no-op

    @property
    def is_noop(self) -> bool:
        return self.enhancer is None

    async def run_batch(self, chunks: List[str]) -> List[dict]:
        """对一批 chunk 文本生成增强内容，返回与输入对齐的 {'subqs', 'summary'} 列表。"""
        if self.enhancer is None:
            return [{"subqs": [], "summary": ""} for _ in chunks]
        return await self.enhancer.enhance_batch(chunks)
