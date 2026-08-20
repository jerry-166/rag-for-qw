"""
检索策略模式 —— 可插拔的检索模式注册表

新增检索模式只需：
  1. 新建一个 RetrievalStrategy 子类
  2. 加 @register_strategy 装饰器
  3. 在 SearchContext 中注入新数据源（如果需要）
  4. 完成，milvus_client 无需任何改动
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import settings, get_runtime


# ═══════════════════════════════════════════════════════════
#  SearchContext —— 所有数据源和查询参数的容器
# ═══════════════════════════════════════════════════════════

class SearchContext:
    """
    打包所有可用的数据源和查询上下文。

    策略按需取用：
      - Milvus 策略用 collection + embedding
      - 未来 graph 策略用 graph_store
      - 未来 rerank 策略用 reranker

    新增数据源只在此类加字段，milvus_client 只在构建 ctx 时传入。
    """

    def __init__(
        self,
        query_embedding: List[float],
        search_params: Dict[str, Any],
        limit: int,
        expr: Optional[str],
        summaries_collection=None,
        subquestions_collection=None,
        chunks_collection=None,
    ):
        self.query_embedding = query_embedding
        self.search_params = search_params
        self.limit = limit
        self.expr = expr
        self.summaries_collection = summaries_collection
        self.subquestions_collection = subquestions_collection
        self.chunks_collection = chunks_collection


# ═══════════════════════════════════════════════════════════
#  通用工具函数
# ═══════════════════════════════════════════════════════════

def milvus_search(
    collection,
    query_embedding: List[float],
    anns_field: str,
    search_params: Dict[str, Any],
    limit: int,
    expr: Optional[str],
    output_fields: List[str],
    result_type: str,
    chunk_id_field: str = "chunk_id",
    content_field: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    通用 Milvus ANN search，消除重复代码。

    Args:
        collection: Milvus Collection 对象（None 时返回空列表）
        query_embedding: 查询向量
        anns_field: 向量字段名
        search_params: 搜索参数
        limit: 返回条数
        expr: 过滤表达式
        output_fields: 需要返回的字段列表
        result_type: 结果类型标识 ("native" / "summary" / "subquestion")
        chunk_id_field: chunk_id 在 Milvus 中的字段名（native 用 pg_chunk_id）
        content_field: content 字段在 Milvus 中的字段名（None 则取 chunk_text）

    Returns:
        统一格式: [{type, chunk_id, chunk_text, content, distance, created_at, metadata}, ...]
    """
    if collection is None:
        return []
    try:
        hits_list = collection.search(
            data=query_embedding,
            anns_field=anns_field,
            param=search_params,
            limit=limit,
            expr=expr,
            output_fields=output_fields,
        )
    except Exception as e:
        from config import init_logger
        init_logger(__name__).warning(f"Milvus search 失败 (anns_field={anns_field}): {e}")
        return []

    results = []
    for hits in hits_list:
        for hit in hits:
            chunk_text = hit.entity.get("chunk_text", "")
            content = hit.entity.get(content_field, chunk_text) if content_field else chunk_text
            results.append({
                "type": result_type,
                "chunk_id": hit.entity.get(chunk_id_field),
                "chunk_text": chunk_text,
                "content": content,
                "distance": hit.distance,
                "created_at": hit.entity.get("created_at"),
                "metadata": hit.entity.get("metadata"),
            })
    return results


def rrf_merge(
    result_lists: List[List[Dict[str, Any]]],
    limit: int,
    dedup_key: str = "chunk_text",
    k: int = 60,
) -> List[Dict[str, Any]]:
    """
    Reciprocal Rank Fusion 融合多路检索结果。

    Args:
        result_lists: 各路检索结果列表
        limit: 返回最大条数
        dedup_key: 去重锚点字段名
        k: RRF 参数，默认 60
    """
    rrf_scores: Dict[str, float] = {}
    rrf_items: Dict[str, Dict] = {}

    for result_list in result_lists:
        for rank, item in enumerate(result_list):
            key = item[dedup_key]
            score = 1.0 / (rank + 1 + k)
            if key not in rrf_scores:
                rrf_scores[key] = 0.0
                rrf_items[key] = item
            rrf_scores[key] += score
            if item["distance"] > rrf_items[key]["distance"]:
                rrf_items[key] = item

    sorted_keys = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
    return [
        {**dict(rrf_items[k]), "rrf_score": rrf_scores[k]}
        for k in sorted_keys[:limit]
    ]


# ═══════════════════════════════════════════════════════════
#  策略基类
# ═══════════════════════════════════════════════════════════

class RetrievalStrategy(ABC):
    """检索策略基类，子类实现 execute() 决定查哪些源、怎么合并。"""

    name: str = ""
    label: str = ""
    description: str = ""

    def __init__(self, ctx: SearchContext):
        self.ctx = ctx

    @abstractmethod
    def execute(self, limit: int) -> List[Dict[str, Any]]:
        ...


# ═══════════════════════════════════════════════════════════
#  注册表
# ═══════════════════════════════════════════════════════════

_REGISTRY: Dict[str, type] = {}


def register_strategy(cls: type) -> type:
    """装饰器：将策略类注册到全局注册表"""
    if not cls.name:
        raise ValueError(f"策略类 {cls.__name__} 必须设置 name 属性")
    _REGISTRY[cls.name] = cls
    return cls


def get_strategy(name: str, ctx: SearchContext) -> RetrievalStrategy:
    """根据名称获取策略实例"""
    if name not in _REGISTRY:
        raise ValueError(f"未知检索模式: '{name}'，可用: {list(_REGISTRY.keys())}")
    return _REGISTRY[name](ctx)


def available_modes() -> List[Dict[str, str]]:
    """返回所有已注册模式的元信息"""
    return [
        {"name": cls.name, "label": cls.label, "description": cls.description}
        for cls in _REGISTRY.values()
    ]


# ═══════════════════════════════════════════════════════════
#  内置策略
# ═══════════════════════════════════════════════════════════

@register_strategy
class NativeStrategy(RetrievalStrategy):
    name = "native"
    label = "原文匹配"
    description = "仅对 chunk 原文向量进行检索，高保真直接语义匹配"

    def execute(self, limit: int) -> List[Dict[str, Any]]:
        results = milvus_search(
            self.ctx.chunks_collection,
            self.ctx.query_embedding, "chunk_vector",
            self.ctx.search_params, limit, self.ctx.expr,
            output_fields=["pg_chunk_id", "chunk_text", "chunk_index", "created_at", "metadata"],
            result_type="native",
            chunk_id_field="pg_chunk_id",
        )
        results.sort(key=lambda x: x["distance"], reverse=True)
        return results[:limit]


@register_strategy
class AdvancedStrategy(RetrievalStrategy):
    name = "advanced"
    label = "摘要+子问题"
    description = "检索摘要向量和子问题向量，适合概念性查询"

    def execute(self, limit: int) -> List[Dict[str, Any]]:
        # 文档 03 降级：启用集全关时（KB 纯原文 RAG），两路增强集合均被短路置 None
        # → 直接回落 native，避免空结果（milvus_search 对 None 集合返回 []）
        if self.ctx.summaries_collection is None and self.ctx.subquestions_collection is None:
            from config import init_logger
            init_logger(__name__).info("[AdvancedStrategy] 增强集合全短路，降级 native 原文检索")
            return _REGISTRY["native"](self.ctx).execute(limit)
        summaries = milvus_search(
            self.ctx.summaries_collection,
            self.ctx.query_embedding, "summary_vector",
            self.ctx.search_params, limit, self.ctx.expr,
            output_fields=["chunk_id", "chunk_text", "summary_text", "created_at", "metadata"],
            result_type="summary",
            content_field="summary_text",
        )
        subquestions = milvus_search(
            self.ctx.subquestions_collection,
            self.ctx.query_embedding, "question_vector",
            self.ctx.search_params, limit, self.ctx.expr,
            output_fields=["chunk_id", "chunk_text", "question_text", "created_at", "metadata"],
            result_type="subquestion",
            content_field="question_text",
        )
        results = summaries + subquestions
        results.sort(key=lambda x: x["distance"], reverse=True)
        return results[:limit]


@register_strategy
class HybridStrategy(RetrievalStrategy):
    name = "hybrid"
    label = "三路融合"
    description = "三路并行检索（摘要+子问题+原文），RRF 融合去重，召回最全面"

    def execute(self, limit: int) -> List[Dict[str, Any]]:
        summaries = milvus_search(
            self.ctx.summaries_collection,
            self.ctx.query_embedding, "summary_vector",
            self.ctx.search_params, limit, self.ctx.expr,
            output_fields=["chunk_id", "chunk_text", "summary_text", "created_at", "metadata"],
            result_type="summary",
            content_field="summary_text",
        )
        subquestions = milvus_search(
            self.ctx.subquestions_collection,
            self.ctx.query_embedding, "question_vector",
            self.ctx.search_params, limit, self.ctx.expr,
            output_fields=["chunk_id", "chunk_text", "question_text", "created_at", "metadata"],
            result_type="subquestion",
            content_field="question_text",
        )
        chunks = milvus_search(
            self.ctx.chunks_collection,
            self.ctx.query_embedding, "chunk_vector",
            self.ctx.search_params, limit, self.ctx.expr,
            output_fields=["pg_chunk_id", "chunk_text", "chunk_index", "created_at", "metadata"],
            result_type="native",
            chunk_id_field="pg_chunk_id",
        )

        return rrf_merge([summaries, subquestions, chunks], limit, k=get_runtime("RRF_K", settings.RRF_K))