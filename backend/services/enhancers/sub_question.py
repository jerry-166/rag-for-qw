"""子问题增强器（单开路径）：复用合并 prompt，只取子问题字段。

质量对照实验（文档 03 §7）结论：C 组独立精简 prompt
子问题相关性 -0.50、有用性 -0.43，超 0.3 门槛未达标；
按 §7 回退方案，单开路径复用 CombinedEnhancer 合并 prompt，
生成后只取启用的子问题字段（多花摘要 token 但保质量）。
"""

from __future__ import annotations

from typing import List

from config import init_logger
from services.enhancers.base import Enhancer
from services.enhancers.combined import CombinedEnhancer

logger = init_logger(__name__)


class SubQuestionEnhancer(Enhancer):
    name = "sub_question"
    output_fields = ("sub_question",)

    def __init__(self, chat_model):
        # 回退（03§7）：委托 CombinedEnhancer（合并 prompt），生成后只取子问题
        self._combined = CombinedEnhancer(chat_model)

    async def enhance_batch(self, chunks: List[str]) -> List[dict]:
        results = await self._combined.enhance_batch(chunks)
        # 统一结果结构：summary 恒为空（未启用）
        return [{"subqs": r["subqs"], "summary": ""} for r in results]
