"""组合增强器：一次 LLM 调用同时生成子问题 + 摘要（文档 03 §3.2）。

双开（sub_question + summary 同开）时的默认路径——
prompt 原样迁移自 document_processor.gen_chain，输入文本只传一次，token 成本最优。
"""

from __future__ import annotations

from typing import List

from config import init_logger
from services.enhancers.base import Enhancer, SubqAndSummary, parse_llm_raw, call_llm_batch, build_chain

logger = init_logger(__name__)

COMBINED_TEMPLATE = (
    "你是一个专业的文档解析助手，负责为给定的文档段落生成子问题和摘要。\n"
    "请根据以下文档段落，生成3~5个相关的子问题和摘要。\n"
    "文档段落：{document_text}\n"
    "请严格按照以下JSON格式返回结果：{{'subqs':['subq1', 'subq2', ...], 'summary':'摘要内容'}}，请至少生成1条子问题"
)


class CombinedEnhancer(Enhancer):
    name = "combined"
    output_fields = ("sub_question", "summary")

    def __init__(self, chat_model):
        self.chain = build_chain(chat_model, COMBINED_TEMPLATE, SubqAndSummary)

    async def enhance_batch(self, chunks: List[str]) -> List[dict]:
        inputs = [{"document_text": doc[:3000]} for doc in chunks]
        raw_results = await call_llm_batch(self.chain, inputs, "组合增强批次")
        return [parse_llm_raw(raw, "组合增强批次") for raw in raw_results]
