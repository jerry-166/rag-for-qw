"""子问题增强器（单开路径）：独立精简 prompt，只生成子问题。

质量对照实验（文档 03 §7）C 组的实现载体；
仅当启用集中只有 sub_question 时由 pipeline 选用。
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel

from config import init_logger
from services.enhancers.base import Enhancer, parse_llm_raw, call_llm_batch, build_chain

logger = init_logger(__name__)


class SubQuestionsOnly(BaseModel):
    subqs: list[str]


SUBQUESTION_TEMPLATE = (
    "你是一个专业的文档解析助手，负责为给定的文档段落生成子问题。\n"
    "请根据以下文档段落，生成3~5个相关的子问题。\n"
    "文档段落：{document_text}\n"
    "请严格按照以下JSON格式返回结果：{{'subqs':['subq1', 'subq2', ...]}}，请至少生成1条子问题"
)


class SubQuestionEnhancer(Enhancer):
    name = "sub_question"
    output_fields = ("sub_question",)

    def __init__(self, chat_model):
        self.chain = build_chain(chat_model, SUBQUESTION_TEMPLATE, SubQuestionsOnly)

    async def enhance_batch(self, chunks: List[str]) -> List[dict]:
        inputs = [{"document_text": doc[:3000]} for doc in chunks]
        raw_results = await call_llm_batch(self.chain, inputs, "子问题批次")
        # 统一结果结构：summary 恒为空（未启用）
        return [
            {"subqs": parsed["subqs"], "summary": ""}
            for parsed in (parse_llm_raw(raw, "子问题批次") for raw in raw_results)
        ]
