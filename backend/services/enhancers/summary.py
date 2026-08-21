"""摘要增强器（单开路径）：复用合并 prompt，只取摘要字段。

质量对照实验（文档 03 §7）结论：C2 组独立精简 prompt
摘要忠实度 -0.44，超 0.3 门槛未达标；
按 §7 回退方案，单开路径复用 CombinedEnhancer 合并 prompt，
生成后只取启用的摘要字段（多花子问题 token 但保质量）。
"""

from __future__ import annotations

from typing import List

from config import init_logger
from services.enhancers.base import Enhancer
from services.enhancers.combined import CombinedEnhancer

logger = init_logger(__name__)


class SummaryEnhancer(Enhancer):
    name = "summary"
    output_fields = ("summary",)

    def __init__(self, chat_model):
        # 回退（03§7）：委托 CombinedEnhancer（合并 prompt），生成后只取摘要
        self._combined = CombinedEnhancer(chat_model)

    async def enhance_batch(self, chunks: List[str]) -> List[dict]:
        results = await self._combined.enhance_batch(chunks)
        # 统一结果结构：subqs 恒为空（未启用）
        return [{"subqs": [], "summary": r["summary"]} for r in results]
