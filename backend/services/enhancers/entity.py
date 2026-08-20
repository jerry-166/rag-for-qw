"""实体/关系抽取增强器（文档 06 Phase 2：GraphRAG-lite 的 L2 图谱层数据源）。

从 chunk 文本中抽取实体（name/type/description）与关系（head/relation/tail/evidence），
结果键为 "entities" / "relations"，由 import 阶段合并入 PG（权威）+ Milvus（实体向量）。
"""

from __future__ import annotations

import json
from typing import List

from pydantic import BaseModel

from config import init_logger
from services.enhancers.base import Enhancer, call_llm_batch, build_chain, strip_markdown_json

logger = init_logger(__name__)


class EntityItem(BaseModel):
    name: str
    type: str = "概念"
    description: str = ""


class RelationItem(BaseModel):
    head: str
    relation: str
    tail: str
    evidence: str = ""


class EntityExtraction(BaseModel):
    entities: list[EntityItem] = []
    relations: list[RelationItem] = []


ENTITY_TEMPLATE = (
    "你是知识图谱构建助手，负责从文档段落中抽取实体和实体间的关系。\n"
    "要求：\n"
    "1. 实体是段落中的关键概念、人物、组织、技术、产品、地点等，每个实体给出一句话描述；\n"
    "2. 关系必须表达实体间在原文中明确存在的联系，evidence 为原文依据（不超过100字）；\n"
    "3. 实体数量控制在 1~6 个，关系数量控制在 0~5 条，宁缺毋滥；\n"
    "4. 若段落不含可抽取的实体，返回空数组。\n"
    "文档段落：{document_text}\n"
    "请严格按照以下JSON格式返回结果：\n"
    "{{\"entities\":[{{\"name\":\"实体名\",\"type\":\"类型\",\"description\":\"一句话描述\"}}],"
    "\"relations\":[{{\"head\":\"头实体名\",\"relation\":\"关系\",\"tail\":\"尾实体名\",\"evidence\":\"原文依据\"}}]}}"
)


def _parse_extraction(raw) -> dict:
    """解析实体抽取输出，降级返回空（与 parse_llm_raw 同风格）。"""
    if raw is None:
        return {"entities": [], "relations": []}
    try:
        if isinstance(raw, EntityExtraction):
            return {
                "entities": [e.model_dump() for e in raw.entities],
                "relations": [r.model_dump() for r in raw.relations],
            }
        if isinstance(raw, str):
            parsed = json.loads(strip_markdown_json(raw))
            return {
                "entities": parsed.get("entities", []) or [],
                "relations": parsed.get("relations", []) or [],
            }
        return {
            "entities": [e.model_dump() if hasattr(e, "model_dump") else dict(e)
                         for e in getattr(raw, "entities", [])],
            "relations": [r.model_dump() if hasattr(r, "model_dump") else dict(r)
                          for r in getattr(raw, "relations", [])],
        }
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        logger.warning(f"实体抽取结果解析失败: {e}")
        return {"entities": [], "relations": []}


class EntityEnhancer(Enhancer):
    name = "entity"
    output_fields = ("entities", "relations")

    def __init__(self, chat_model):
        self.chain = build_chain(chat_model, ENTITY_TEMPLATE, EntityExtraction)

    async def enhance_batch(self, chunks: List[str]) -> List[dict]:
        inputs = [{"document_text": doc[:3000]} for doc in chunks]
        raw_results = await call_llm_batch(self.chain, inputs, "实体抽取批次")
        return [_parse_extraction(raw) for raw in raw_results]
