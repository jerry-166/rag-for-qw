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
from config import settings, get_runtime, init_logger

logger = init_logger(__name__)


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
        query: str = "",
        kb_id: Optional[int] = None,
        entities_collection=None,
    ):
        self.query_embedding = query_embedding
        self.search_params = search_params
        self.limit = limit
        self.expr = expr
        self.summaries_collection = summaries_collection
        self.subquestions_collection = subquestions_collection
        self.chunks_collection = chunks_collection
        # 06 Phase 2：graph 策略依赖（原始查询文本 / KB 范围 / 实体集合）
        self.query = query
        self.kb_id = kb_id
        self.entities_collection = entities_collection


# ═══════════════════════════════════════════════════════════
#  通用工具函数
# ═══════════════════════════════════════════════════════════

import time as _time

# Milvus 服务端瞬态错误（Zilliz Cloud serverless 冷启动/网关抖动时常见）：
#  - code=502 网关 Bad Gateway；code=14 gRPC UNAVAILABLE；code=2 连接失败
#  - 消息含 timeout / unavailable / temporarily 等关键字
_TRANSIENT_HINTS = ("timeout", "unavailable", "temporarily", "try again",
                    "retry", "error code: 502", "bad gateway", "connection reset")


def _is_transient_milvus_error(e: Exception) -> bool:
    """判断是否为可重试的 Milvus 瞬态错误（冷启动/网关/超时）。"""
    code = getattr(e, "code", None)
    if isinstance(code, int) and code in (502, 14, 2, 1):
        return True
    msg = str(e).lower()
    return any(hint in msg for hint in _TRANSIENT_HINTS)


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
    timeout: Optional[float] = None,
    retries: int = 2,
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
        timeout: 单次 search 超时秒数（默认取 MILVUS_TIMEOUT；Zilliz serverless
                 冷启动可能远超 pymilvus 默认 10s，必须显式给足）
        retries: 瞬态错误（502/UNAVAILABLE/超时）自动重试次数，默认 2

    Returns:
        统一格式: [{type, chunk_id, chunk_text, content, distance, created_at, metadata}, ...]
    """
    if collection is None:
        return []
    timeout = timeout or float(get_runtime("MILVUS_TIMEOUT", settings.MILVUS_TIMEOUT))
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            hits_list = collection.search(
                data=query_embedding,
                anns_field=anns_field,
                param=search_params,
                limit=limit,
                expr=expr,
                output_fields=output_fields,
                timeout=timeout,
            )
            break
        except Exception as e:
            last_error = e
            if attempt < retries and _is_transient_milvus_error(e):
                _time.sleep(1.5 * (attempt + 1))
                logger.warning(f"Milvus search 瞬态失败 (anns_field={anns_field}, "
                               f"第 {attempt + 1} 次, 共 {retries} 次重试): {e}")
                continue
            logger.warning(f"Milvus search 失败 (anns_field={anns_field}): {e}")
            return []
    else:
        # for 循环未被 break（重试次数耗尽仍未成功）时记录最终错误
        logger.warning(f"Milvus search 重试 {retries} 次仍失败 (anns_field={anns_field}): {last_error}")
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
            logger.info("[AdvancedStrategy] 增强集合全短路，降级 native 原文检索")
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
class GraphStrategy(RetrievalStrategy):
    """图谱检索（文档 06 Phase 2：GraphRAG-lite on Milvus）。

    路由逻辑：
      1. LLM 从问题提取实体锚点 + 实体向量语义匹配（双路锚点发现）
      2. PG 关系表一跳扩展邻居实体
      3. 收集全部相关实体的 source_chunk_ids → PG 取 chunk 原文返回
      4. 无锚点 / 查不到实体 / KB 未启用 entity 增强 → 降级 native 原文检索
    """
    name = "graph"
    label = "实体图谱"
    description = "实体锚点匹配→关系扩展→关联 chunk 召回，适合多跳关联查询；KB 需启用 entity 增强"

    def _extract_anchor_names(self) -> List[str]:
        """LLM 从问题中提取实体锚点名（失败/无实体返回空列表）"""
        try:
            from langchain_openai import ChatOpenAI
            from config import settings, get_runtime
            llm = ChatOpenAI(
                model=get_runtime("DEFAULT_MODEL", settings.DEFAULT_MODEL),
                api_key=get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY),
                base_url=get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL),
                temperature=0, max_tokens=200,
            )
            prompt = (
                "从下面问题中提取出作为检索锚点的实体名称（人物/组织/概念/技术/产品等）。\n"
                "只输出实体名，每行一个，最多 5 个；若没有明确实体，输出空。\n"
                f"问题：{self.ctx.query}"
            )
            resp = llm.invoke(prompt)
            text = resp.content if hasattr(resp, "content") else str(resp)
            names = [n.strip().strip("。；;,") for n in text.strip().splitlines()]
            return [n for n in names if n and len(n) <= 50][:5]
        except Exception as e:
            logger.warning(f"[GraphStrategy] 实体锚点提取失败: {e}")
            return []

    def execute(self, limit: int) -> List[Dict[str, Any]]:
        # 前置不满足 → 降级 native
        if self.ctx.entities_collection is None or not self.ctx.kb_id:
            logger.info("[GraphStrategy] 实体集合未启用或未指定 KB，降级 native")
            return _REGISTRY["native"](self.ctx).execute(limit)

        from services.database import db

        # 1. 双路锚点发现：按名直查 + 向量语义匹配
        anchor_ids: List[int] = []
        names = self._extract_anchor_names()
        if names:
            for row in db.find_entities_by_names(self.ctx.kb_id, names):
                anchor_ids.append(row["id"])

        try:
            self.ctx.entities_collection.load()
        except Exception as e:
            logger.warning(f"[GraphStrategy] 实体集合 load 失败: {e}")

        # 实体向量匹配：显式 timeout + 瞬态错误重试（同 milvus_search）
        timeout = float(get_runtime("MILVUS_TIMEOUT", settings.MILVUS_TIMEOUT))
        vec_hits = None
        for attempt in range(3):
            try:
                vec_hits = self.ctx.entities_collection.search(
                    data=[self.ctx.query_embedding],
                    anns_field="description_vector",
                    param=self.ctx.search_params,
                    limit=5,
                    expr=f"kb_id == {int(self.ctx.kb_id)}",
                    output_fields=["pg_entity_id"],
                    timeout=timeout,
                )
                break
            except Exception as e:
                if attempt < 2 and _is_transient_milvus_error(e):
                    _time.sleep(1.5 * (attempt + 1))
                    logger.warning(f"[GraphStrategy] 实体向量匹配瞬态失败，"
                                   f"第 {attempt + 1} 次重试: {e}")
                    continue
                logger.warning(f"[GraphStrategy] 实体向量匹配失败: {e}")
                break
        if vec_hits is not None:
            for hit in vec_hits[0]:
                eid = hit.entity.get("pg_entity_id")
                if eid is not None:
                    anchor_ids.append(eid)
        else:
            logger.warning("[GraphStrategy] 实体向量匹配不可用，仅用按名直查锚点")

        anchor_ids = list(dict.fromkeys(anchor_ids))  # 去重保序
        if not anchor_ids:
            logger.info("[GraphStrategy] 未找到实体锚点，降级 native")
            return _REGISTRY["native"](self.ctx).execute(limit)

        # 2. 关系一跳扩展
        relations, neighbor_ids = db.get_entity_neighbors(anchor_ids, kb_id=self.ctx.kb_id)
        logger.info(f"[GraphStrategy] 锚点 {len(anchor_ids)} 个，扩展后实体 {len(neighbor_ids)} 个，"
                    f"关系 {len(relations)} 条")

        # 3. 收集关联 chunk
        entities = db.get_entities_by_ids(list(neighbor_ids))

        def _src_ids(entity):
            src = entity.get("source_chunk_ids") or []
            if isinstance(src, str):
                import json as _json
                try:
                    src = _json.loads(src)
                except Exception:
                    src = []
            return src

        chunk_ids: List[int] = []
        for e in entities:
            chunk_ids.extend(_src_ids(e))
        chunk_ids = list(dict.fromkeys(chunk_ids))[: limit * 2]

        if not chunk_ids:
            logger.info("[GraphStrategy] 实体无关联 chunk，降级 native")
            return _REGISTRY["native"](self.ctx).execute(limit)

        # 4. 取 chunk 原文，锚点实体关联的 chunk 给更高分
        anchor_chunk_ids: List[int] = []
        for e in entities:
            if e["id"] in anchor_ids:
                anchor_chunk_ids.extend(_src_ids(e))
        anchor_set = set(anchor_chunk_ids)

        chunks = db.get_chunks_by_ids(chunk_ids)
        results = []
        for ch in chunks:
            base = 0.9 if ch["id"] in anchor_set else 0.75
            results.append({
                "chunk_text": ch["content"],
                # P1-4：下游 rag_tools 统一按 Milvus distance（1-distance=相似度）过滤，
                # graph 的 score 是相似度语义 → 补充等价 distance，保证过滤链行为一致。
                # 注意：阈值未实测校准，锚点 0.9/非锚点 0.75 映射 distance 0.1/0.25，
                # 均可通过 RETRIEVAL_MIN_SCORE=0.3 的默认过滤。
                "distance": round(1.0 - base, 4),
                "score": base,
                "metadata": {
                    "chunk_id": ch["id"],
                    "document_id": ch.get("document_id"),
                    "knowledge_base_id": ch.get("knowledge_base_id"),
                    "chunk_index": ch.get("chunk_index"),
                },
                "type": "graph",
            })
        results.sort(key=lambda x: x["score"], reverse=True)
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