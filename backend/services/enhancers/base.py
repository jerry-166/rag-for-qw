"""增强器基类与共享工具（文档 03 §3.1）。

自 document_processor.py 迁移的 LLM 调用 / 解析降级逻辑，
三个内置增强器共享，保证行为与迁移前一致。
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import List, Optional

from pydantic import BaseModel
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.output_parsers import OutputFixingParser

from config import init_logger

logger = init_logger(__name__)


class SubqAndSummary(BaseModel):
    """合并增强（子问题+摘要）的结构化输出。"""
    subqs: list[str]
    summary: str


def strip_markdown_json(text: str) -> str:
    """清理 LLM 输出中的 markdown 代码块包裹（自 document_processor 迁移）。"""
    text = text.strip()
    pattern = r'^```(?:json)?\s*\n?(.*?)\n?\s*```$'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def parse_llm_raw(raw, batch_label: str = "") -> dict:
    """解析单条 LLM 原始输出为 {'subqs': list, 'summary': str}。

    降级链（与迁移前一致）：
    1. SubqAndSummary 对象（OutputFixingParser 成功时）→ 直接取值；
    2. 字符串 → 清理 markdown 代码块后 JSON 解析；
    3. 其他 → 尝试取属性；
    4. 全部失败 → 空 subqs + 空 summary。
    """
    if raw is None:
        return {"subqs": [], "summary": ""}
    try:
        if isinstance(raw, SubqAndSummary):
            return {"subqs": raw.subqs, "summary": raw.summary}
        if isinstance(raw, str):
            cleaned = strip_markdown_json(raw)
            parsed = json.loads(cleaned)
            return {"subqs": parsed.get("subqs", []), "summary": parsed.get("summary", "")}
        return {"subqs": getattr(raw, "subqs", []), "summary": getattr(raw, "summary", "")}
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        logger.warning(f"{batch_label} 解析失败: {e}")
        return {"subqs": [], "summary": ""}


async def call_llm_batch(chain, inputs: List[dict], batch_label: str = "") -> List:
    """abatch 并发调用 LLM；整体失败降级为逐条调用（与迁移前一致）。

    429 限流退避：智谱 GLM-4-Flash 256/window，撞限流时 sleep 60s 后重试（最多 3 次）。
    """
    import asyncio
    import time

    def _is_rate_limited(e):
        """检查异常是否是 429 限流"""
        err_str = str(e).lower()
        return '429' in err_str or 'rate' in err_str or '1302' in err_str

    # abatch + 429 退避重试
    for attempt in range(3):
        try:
            return await chain.abatch(inputs)
        except Exception as e:
            if _is_rate_limited(e) and attempt < 2:
                logger.warning(f"{batch_label} abatch 429 限流，sleep 60s 后重试 (attempt {attempt+1}/3): {str(e)[:100]}")
                await asyncio.sleep(60)
                continue
            logger.error(f"{batch_label} abatch 调用失败: {e}")
            break

    # 降级为逐条调用 + 429 退避重试
    raw_results = []
    for inp in inputs:
        for attempt in range(3):
            try:
                result = await chain.ainvoke(inp)
                raw_results.append(result)
                break
            except Exception as inner_e:
                if _is_rate_limited(inner_e) and attempt < 2:
                    logger.warning(f"{batch_label} 单条 429 限流，sleep 60s 后重试 (attempt {attempt+1}/3): {str(inner_e)[:100]}")
                    await asyncio.sleep(60)
                    continue
                logger.warning(f"{batch_label} 单条调用失败: {inner_e}")
                raw_results.append(None)
                break
    return raw_results


class Enhancer(ABC):
    """增强器抽象基类。

    子类声明 name / output_fields，实现 enhance_batch()：
    输入一批 chunk 文本，返回与输入对齐的结果 dict 列表。
    结果统一使用键 'subqs' / 'summary'（未启用的字段返回空值），
    与迁移前 document_processor 的结果结构一致。
    """

    name: str = ""
    output_fields: tuple = ()

    @abstractmethod
    async def enhance_batch(self, chunks: List[str]) -> List[dict]:
        raise NotImplementedError


def build_chain(chat_model, template_text: str, parser_model=None):
    """按模板构建 prompt | llm | fixing_parser 链（共享构建逻辑）。"""
    parser = PydanticOutputParser(pydantic_object=parser_model or SubqAndSummary)
    fixing_parser = OutputFixingParser.from_llm(parser=parser, llm=chat_model)
    prompt_template = PromptTemplate.from_template(template_text)
    return prompt_template | chat_model | fixing_parser
