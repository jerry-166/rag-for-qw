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

from pydantic import BaseModel

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


# ═══════════════════════════════════════════════════════════
#  GraphStrategy 结构化输出模型与 prompt 模板
# ═══════════════════════════════════════════════════════════

class _RelationScore(BaseModel):
    """LLM 关系重排单条打分"""
    relation_id: int
    score: float


class _RelationRerankResult(BaseModel):
    """LLM 关系重排批量打分结果"""
    scores: list[_RelationScore] = []


_ANCHOR_EXTRACT_TEMPLATE = (
    "从下面问题中提取出作为检索锚点的实体（人物/组织/概念/技术/产品等）。\n"
    "每个实体给一句话客观描述，不超过30字，不要发挥，只描述实体本身的客观属性。\n"
    "实体数量控制在1~5个，宁缺毋滥；若问题无明确实体，返回空数组。\n"
    "请严格按照以下JSON格式返回结果：\n"
    '{{"entities":[{{"name":"实体名","type":"类型","description":"一句话描述"}}]}}\n'
    "问题：{query}"
)

_RELATION_RERANK_TEMPLATE = (
    "你是关系相关性评估助手。请对以下关系与用户问题的相关性打分（0到1，1=高度相关，0=无关）。\n"
    "用户问题：{query}\n"
    "关系列表：\n{relations_text}\n"
    "请严格按照以下JSON格式返回结果：\n"
    '{{"scores":[{{"relation_id":1,"score":0.8}}]}}\n'
    "每条关系都必须给出一个分数。"
)


@register_strategy
class GraphStrategy(RetrievalStrategy):
    """图谱检索（文档 06 Phase 2：GraphRAG-lite on Milvus）。

    路由逻辑：
      1. LLM 结构化提取实体锚点（name + description）
      2. 路A name 精确直查 PG + 路B entity description embedding 匹 Milvus
      3. PG 关系表一跳扩展邻居实体 → LLM 关系重排（过滤噪声关系）
      4. 主路径 B: relation.source_chunk_id 直接拉证据原文
         兜底路径 A: source_chunk_id 为 null 时回退 entity.source_chunk_ids
      5. 无锚点 / 无关联 chunk / KB 未启用 entity 增强 → 降级 native 原文检索
    """
    name = "graph"
    label = "实体图谱"
    description = "实体锚点匹配→关系扩展→关联 chunk 召回，适合多跳关联查询；KB 需启用 entity 增强"

    def _extract_anchor_entities(self) -> List[dict]:
        """LLM 从问题中提取实体锚点（name + description），失败返回空列表。

        改造点 1：pydantic 结构化输出，复用 EntityItem 模型，
        对齐导入侧 EntityEnhancer 的 description 风格（一句话客观描述 ≤30 字）。
        """
        try:
            from langchain_openai import ChatOpenAI
            from services.enhancers.base import build_chain
            from services.enhancers.entity import EntityItem

            class _AnchorEntities(BaseModel):
                entities: list[EntityItem] = []

            llm = ChatOpenAI(
                model=get_runtime("DEFAULT_MODEL", settings.DEFAULT_MODEL),
                api_key=get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY),
                base_url=get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL),
                temperature=0, max_tokens=300,
            )
            chain = build_chain(llm, _ANCHOR_EXTRACT_TEMPLATE, _AnchorEntities)
            result = chain.invoke({"query": self.ctx.query})

            # 归一化为 [{"name": ..., "description": ...}]
            raw_entities = []
            if isinstance(result, _AnchorEntities):
                raw_entities = result.entities
            elif isinstance(result, dict):
                raw_entities = result.get("entities", [])
            else:
                raw_entities = getattr(result, "entities", [])

            out: List[dict] = []
            for e in raw_entities[:5]:
                if hasattr(e, "name"):
                    out.append({"name": e.name, "description": getattr(e, "description", "")})
                elif isinstance(e, dict):
                    out.append({"name": e.get("name", ""), "description": e.get("description", "")})
            return out
        except Exception as e:
            logger.warning(f"[GraphStrategy] 实体锚点提取失败: {e}")
            return []

    def _embed_entity_texts(self, texts: List[str]) -> Optional[List[List[float]]]:
        """同步批量 embedding（复用 milvus_client 的 OpenAIEmbeddings 模式）。

        改造点 2：对 entity "name：description" 文本做 embedding，
        替代旧的 query_embedding 匹 description_vector。
        """
        if not texts:
            return None
        try:
            from langchain_openai import OpenAIEmbeddings
            emb_model = OpenAIEmbeddings(
                model=get_runtime("EMBEDDING_MODEL", settings.EMBEDDING_MODEL),
                api_key=get_runtime("EMBEDDING_API_KEY", settings.EMBEDDING_API_KEY),
                base_url=get_runtime("EMBEDDING_BASE_URL", settings.EMBEDDING_BASE_URL),
            )
            return emb_model.embed_documents(texts)
        except Exception as e:
            logger.warning(f"[GraphStrategy] entity embedding 生成失败: {e}")
            return None

    def _rerank_relations(
        self, relations: List[dict], neighbor_entities: List[dict], query: str
    ) -> List[dict]:
        """LLM 对关系与问题的相关性打分，过滤低分关系（fail-open 保留全部）。

        改造点 3：graph 独有的 LLM 关系重排。一跳扩展出的关系可能含噪声，
        用 LLM 判断 relation_type + evidence 与 query 的相关性，过滤 score < 阈值的关系。
        """
        if not relations:
            return []

        try:
            from langchain_openai import ChatOpenAI
            from services.enhancers.base import build_chain

            # 构建实体 id → name 映射（LLM 看不懂 id，需要实体名）
            entity_map = {e["id"]: e["name"] for e in neighbor_entities}

            # 组装关系文本
            lines = []
            for r in relations:
                head_name = entity_map.get(r["head_entity_id"], "?")
                tail_name = entity_map.get(r["tail_entity_id"], "?")
                evidence = (r.get("evidence") or "")[:100]
                lines.append(
                    f'{r["id"]}. {head_name} —[{r["relation_type"]}]→ {tail_name}'
                    f" | 依据: {evidence}"
                )
            relations_text = "\n".join(lines)

            llm = ChatOpenAI(
                model=get_runtime("DEFAULT_MODEL", settings.DEFAULT_MODEL),
                api_key=get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY),
                base_url=get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL),
                temperature=0, max_tokens=800,
            )
            chain = build_chain(llm, _RELATION_RERANK_TEMPLATE, _RelationRerankResult)
            result = chain.invoke({"query": query, "relations_text": relations_text})

            # 解析分数 → dict
            score_map: Dict[int, float] = {}
            raw_scores = []
            if isinstance(result, _RelationRerankResult):
                raw_scores = result.scores
            elif isinstance(result, dict):
                raw_scores = result.get("scores", [])
            else:
                raw_scores = getattr(result, "scores", [])
            for s in raw_scores:
                if hasattr(s, "relation_id"):
                    score_map[s.relation_id] = s.score
                elif isinstance(s, dict):
                    score_map[s["relation_id"]] = s["score"]

            min_score = get_runtime("GRAPH_RELATION_MIN_SCORE", settings.GRAPH_RELATION_MIN_SCORE)
            kept = [r for r in relations if score_map.get(r["id"], 0.0) >= min_score]

            if not kept:
                logger.warning("[GraphStrategy] 关系重排后全部被过滤，fail-open 保留全部关系")
                return relations

            logger.info(f"[GraphStrategy] 关系重排: {len(relations)} → {len(kept)} 条 "
                        f"(阈值={min_score})")
            return kept
        except Exception as e:
            logger.warning(f"[GraphStrategy] 关系重排失败，fail-open 保留全部: {e}")
            return relations

    def execute(self, limit: int) -> List[Dict[str, Any]]:
        # 前置不满足 → 降级 native
        if self.ctx.entities_collection is None or not self.ctx.kb_id:
            logger.info("[GraphStrategy] 实体集合未启用或未指定 KB，降级 native")
            return _REGISTRY["native"](self.ctx).execute(limit)

        from services.database import db

        # 1. LLM 结构化锚点提取（改造点 1）
        anchor_entities = self._extract_anchor_entities()  # [{name, description}]

        # 路A: name 精确直查 PG
        anchor_ids: List[int] = []
        names = [e["name"] for e in anchor_entities if e.get("name")]
        if names:
            for row in db.find_entities_by_names(self.ctx.kb_id, names):
                anchor_ids.append(row["id"])

        # 路B: entity description embedding → Milvus 语义匹配（改造点 2）
        try:
            self.ctx.entities_collection.load()
        except Exception as e:
            logger.warning(f"[GraphStrategy] 实体集合 load 失败: {e}")

        timeout = float(get_runtime("MILVUS_TIMEOUT", settings.MILVUS_TIMEOUT))
        entity_texts = [
            f'{e["name"]}：{e["description"]}'
            for e in anchor_entities if e.get("name")
        ]
        entity_embeddings = self._embed_entity_texts(entity_texts)

        if entity_embeddings:
            for emb in entity_embeddings:
                for attempt in range(3):
                    try:
                        hits = self.ctx.entities_collection.search(
                            data=[emb],
                            anns_field="description_vector",
                            param=self.ctx.search_params,
                            limit=5,
                            expr=f"kb_id == {int(self.ctx.kb_id)}",
                            output_fields=["pg_entity_id"],
                            timeout=timeout,
                        )
                        for hit in hits[0]:
                            eid = hit.entity.get("pg_entity_id")
                            if eid is not None:
                                anchor_ids.append(eid)
                        break
                    except Exception as e:
                        if attempt < 2 and _is_transient_milvus_error(e):
                            _time.sleep(1.5 * (attempt + 1))
                            logger.warning(f"[GraphStrategy] 实体向量匹配瞬态失败，"
                                           f"第 {attempt + 1} 次重试: {e}")
                            continue
                        logger.warning(f"[GraphStrategy] 实体向量匹配失败: {e}")
                        break
        else:
            logger.warning("[GraphStrategy] entity embedding 不可用，仅用路A name 直查锚点")

        anchor_ids = list(dict.fromkeys(anchor_ids))  # 去重保序
        if not anchor_ids:
            logger.info("[GraphStrategy] 未找到实体锚点，降级 native")
            return _REGISTRY["native"](self.ctx).execute(limit)

        # 2. 关系一跳扩展
        relations, neighbor_ids = db.get_entity_neighbors(anchor_ids, kb_id=self.ctx.kb_id)
        logger.info(f"[GraphStrategy] 锚点 {len(anchor_ids)} 个，扩展后实体 {len(neighbor_ids)} 个，"
                    f"关系 {len(relations)} 条")

        # 3. 拿邻居实体 name → LLM 关系重排（改造点 3）
        entities = db.get_entities_by_ids(list(neighbor_ids))
        reranked_relations = self._rerank_relations(relations, entities, self.ctx.query)

        # 4. 收集关联 chunk（改造点 4）
        # 主路径 B: relations.source_chunk_id → 直接证据原文
        # 兜底路径 A: source_chunk_id 为 null 的关系 → 两端实体 source_chunk_ids
        def _src_ids(entity):
            src = entity.get("source_chunk_ids") or []
            if isinstance(src, str):
                import json as _json
                try:
                    src = _json.loads(src)
                except Exception:
                    src = []
            return src

        entity_map = {e["id"]: e for e in entities}
        chunk_ids: List[int] = []
        path_b_ids: set = set()  # 路径 B 来源（高分 0.9）

        for r in reranked_relations:
            scid = r.get("source_chunk_id")
            if scid is not None:
                chunk_ids.append(scid)
                path_b_ids.add(scid)
            else:
                # 兜底路径 A: 取两端实体 source_chunk_ids
                for eid in (r["head_entity_id"], r["tail_entity_id"]):
                    e = entity_map.get(eid)
                    if e:
                        chunk_ids.extend(_src_ids(e))

        # 无关系时的最终兜底：直接从所有实体取 source_chunk_ids
        if not reranked_relations:
            for e in entities:
                chunk_ids.extend(_src_ids(e))

        chunk_ids = list(dict.fromkeys(chunk_ids))[: limit * 2]

        if not chunk_ids:
            logger.info("[GraphStrategy] 关系无关联 chunk，降级 native")
            return _REGISTRY["native"](self.ctx).execute(limit)

        # 5. 取 chunk 原文，路径 B + 锚点实体来源给高分
        anchor_chunk_ids: List[int] = []
        for e in entities:
            if e["id"] in anchor_ids:
                anchor_chunk_ids.extend(_src_ids(e))
        high_confidence_set = set(anchor_chunk_ids) | path_b_ids

        chunks = db.get_chunks_by_ids(chunk_ids)
        results = []
        for ch in chunks:
            base = 0.9 if ch["id"] in high_confidence_set else 0.75
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