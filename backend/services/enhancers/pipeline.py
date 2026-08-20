"""增强器流水线：按启用集装配执行 + 启用集三级解析（文档 03 §3.2/§3.3 + 06 Phase 2）。

装配规则：
  - {sub_question, summary} 双开  → CombinedEnhancer（合并 prompt，token 成本最优，= 迁移前默认行为）
  - 只开 summary                  → SummaryEnhancer（独立精简 prompt）
  - 只开 sub_question             → SubQuestionEnhancer（独立精简 prompt）
  - entity                        → EntityEnhancer（实体/关系抽取，06 Phase 2）
  - 全关                          → no-op（generate 阶段秒回，纯原文 RAG）

entity 与子问题/摘要正交：多个增强器并行 gather 执行，结果按 chunk 合并。

启用集三级解析：请求参数 > 知识库配置（kb.enhancers JSONB，NULL=跟随全局）> 全局配置。
"""

from __future__ import annotations

import asyncio
from typing import List, Optional, Set

from config import settings, get_runtime, init_logger
from services.enhancers.base import Enhancer
from services.enhancers.combined import CombinedEnhancer
from services.enhancers.sub_question import SubQuestionEnhancer
from services.enhancers.summary import SummaryEnhancer
from services.enhancers.entity import EntityEnhancer

logger = init_logger(__name__)

VALID_ENHANCERS = {"sub_question", "summary", "entity"}


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
    """按启用集装配增强器并执行（多增强器并行 + 结果按 chunk 合并）。"""

    def __init__(self, enabled: Set[str], chat_model):
        self.enabled = set(enabled)
        self.enhancers: List[Enhancer] = self._select(chat_model)

    def _select(self, chat_model) -> List[Enhancer]:
        enhancers: List[Enhancer] = []
        if {"sub_question", "summary"} <= self.enabled:
            enhancers.append(CombinedEnhancer(chat_model))
        else:
            if "summary" in self.enabled:
                enhancers.append(SummaryEnhancer(chat_model))
            if "sub_question" in self.enabled:
                enhancers.append(SubQuestionEnhancer(chat_model))
        if "entity" in self.enabled:
            enhancers.append(EntityEnhancer(chat_model))
        return enhancers

    @property
    def is_noop(self) -> bool:
        return not self.enhancers

    @property
    def enhancer(self) -> Optional[Enhancer]:
        """兼容旧接口：单增强器时返回它，多增强器时返回 None。"""
        return self.enhancers[0] if len(self.enhancers) == 1 else None

    async def run_batch(self, chunks: List[str]) -> List[dict]:
        """对一批 chunk 生成增强内容，返回与输入对齐的结果 dict 列表。

        结果键并集：'subqs' / 'summary' / 'entities' / 'relations'
        （未启用的字段返回空值）。
        """
        if not self.enhancers:
            return [{"subqs": [], "summary": "", "entities": [], "relations": []}
                    for _ in chunks]

        # 多增强器并行执行（共享下游 LLM 并发由 abatch 内部控制）
        results_per_enhancer = await asyncio.gather(
            *[e.enhance_batch(chunks) for e in self.enhancers])

        merged = []
        for i in range(len(chunks)):
            row = {"subqs": [], "summary": "", "entities": [], "relations": []}
            for res in results_per_enhancer:
                row.update(res[i])
            merged.append(row)
        return merged
