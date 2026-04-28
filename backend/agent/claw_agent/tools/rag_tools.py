"""
RAG 专属工具定义

所有工具使用 LangChain @tool 装饰器定义，可直接注入 LangGraph 工具节点。

设计原则（参考 mini-openclew）：
- 每个工具职责单一、接口清晰
- 工具内部日志记录详细，方便 SSE 推送中间状态
- 所有工具均为同步函数（LangGraph ToolNode 要求），异步包装在外层
"""

import json
import asyncio
from typing import Optional, List, Any
from langchain_core.tools import tool

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import settings, init_logger

logger = init_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Tool 1: 混合检索
# ─────────────────────────────────────────────────────────────

@tool
def rag_hybrid_search(
    query: str,
    knowledge_base_id: Optional[int] = None,
    top_k: int = 10,
    use_vector: bool = True,
    use_keyword: bool = True,
    use_rerank: bool = True,
    rerank_top_k: int = 5,
    retrieval_mode: Optional[str] = "advanced",
) -> str:
    """
    混合检索工具：同时执行向量语义检索（Milvus）和关键词检索（Elasticsearch），
    融合结果并去重后返回最相关的文档片段列表。

    Args:
        query: 用户查询文本
        knowledge_base_id: 知识库 ID，不传则搜索所有知识库
        top_k: 返回结果数量（每路各取 top_k/2）
        use_vector: 是否启用向量检索
        use_keyword: 是否启用关键词检索
        use_rerank: 是否启用精排
        rerank_top_k: 精排后保留的结果数量
        retrieval_mode: 向量检索模式：native(原文) | advanced(摘要+子问题) | hybrid(三路融合)

    Returns:
        JSON 字符串，包含 results 列表和 total_count
    """
    results = []
    vector_results = []
    keyword_results = []

    per_k = max(top_k // 2, 3)

    # ── 向量检索（Milvus）────────────────────────────────────
    if use_vector:
        try:
            from services.milvus_client import MilvusClient
            milvus = MilvusClient()

            metadata_filter = {}
            if knowledge_base_id is not None:
                metadata_filter["knowledge_base_id"] = knowledge_base_id

            logger.info(f"[rag_tools] 向量检索开始，query={query[:50]}, retrieval_mode={retrieval_mode}, knowledge_base_id={knowledge_base_id}")

            raw = milvus.query(
                query_text=query,
                limit=per_k,
                metadata_filter=metadata_filter if metadata_filter else None,
                retrieval_mode=retrieval_mode,
            )

            for item in raw:
                vector_results.append({
                    "source": "vector",
                    "content": item.get("content", item.get("chunk_text", "")),
                    "chunk_text": item.get("chunk_text", ""),
                    "score": float(item.get("distance", 0.0)),
                    "type": item.get("type", "unknown"),
                    "metadata": item.get("metadata", {}),
                })

            logger.info(f"向量检索完成，返回 {len(vector_results)} 条结果")

        except Exception as e:
            logger.warning(f"向量检索失败（跳过）: {e}")

    # ── 关键词检索（BM25 或 Elasticsearch，由 SEARCH_BACKEND 配置决定）──
    if use_keyword:
        try:
            from services.bm25_client import get_search_client
            search_client = get_search_client()

            filters = {}
            if knowledge_base_id is not None:
                filters["knowledge_base_id"] = knowledge_base_id

            # user_id 传 0 会在 BM25 里聚合全部用户数据（系统级检索）
            raw = search_client.search(
                query=query,
                user_id=0,
                size=per_k,
                filters=filters if filters else None,
            )

            for item in raw:
                keyword_results.append({
                    "source": "keyword",
                    "content": item.get("content", ""),
                    "chunk_text": item.get("content", ""),
                    "score": float(item.get("score", 0.0)),
                    "type": "keyword",
                    "metadata": {
                        "document_id": item.get("document_id"),
                        "chunk_index": item.get("chunk_index"),
                    },
                })

            logger.info(f"关键词检索完成，返回 {len(keyword_results)} 条结果")

        except Exception as e:
            logger.warning(f"关键词检索失败（跳过）: {e}")

    # ── 结果融合（倒数排名融合 RRF）──────────────────────────
    results = _reciprocal_rank_fusion(vector_results, keyword_results, k=60)

    # 去重（按 content 前 200 字符去重）
    seen = set()
    deduped = []
    for r in results:
        key = r["content"][:200]
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    # ── 分数阈值过滤 ──────────────────────────────────────
    min_score = getattr(settings, 'RETRIEVAL_MIN_SCORE', 0.3)
    # RRF 分数归一化到 0-1 范围（RRF 最大约 2*(1/(60+1)) ≈ 0.065，需要缩放）
    # 实际上 RRF 分数范围是 [0, ~0.066]，用原始 score（distance/BM25）来判断更合理
    # 这里的 score 来自 Milvus distance (越小越相似) 或 BM25 score (越大越好)
    # 统一处理：对 vector 结果，distance < (1 - min_score) 视为合格
    # 对 keyword 结果，score > min_score 视为合格
    filtered = []
    for r in deduped:
        src = r.get("source", "")
        sc = r.get("score", 0)
        if src == "vector":
            # Milvus distance: 0=最相似, 1=不相似。转换为相似度: 1 - distance
            similarity = 1.0 - max(0.0, min(1.0, float(sc)))
            if similarity >= min_score:
                r["_similarity"] = round(similarity, 4)
                filtered.append(r)
        else:
            # keyword / reranked: score 越大越好，已经是正分
            if float(sc) >= min_score:
                r["_similarity"] = round(float(sc), 4)
                filtered.append(r)

    final = filtered[:top_k]
    
    # ── 精排（Rerank）───────────────────────────────────────
    if use_rerank and final:
        try:
            from services.reranker import get_reranker
            reranker = get_reranker()

            # 统一字段格式给 reranker
            normalized = []
            for r in final:
                normalized.append({
                    **r,
                    "content": r.get("content") or r.get("chunk_text", ""),
                })

            # 同步函数内调用异步 reranker
            # 本工具通过 asyncio.to_thread 在线程池中执行，线程内无运行中的事件循环
            reranked = asyncio.run(
                reranker.rerank(query=query, results=normalized, top_k=rerank_top_k)
            )
            
            # 精排后再次过滤低分结果
            min_score = getattr(settings, 'RETRIEVAL_MIN_SCORE', 0.3)
            final_filtered = [r for r in reranked if float(r.get("rerank_score", 0)) >= min_score]
            final = final_filtered if final_filtered else reranked[:3]  # 至少保留前3条
            logger.info(f"精排完成（阈值 {min_score}），保留 {len(final)} 条结果")

        except Exception as e:
            logger.error(f"精排失败，使用原始结果: {e}")
    
    logger.info(f"混合检索最终返回 {len(final)} 条结果")

    return json.dumps({
        "results": final,
        "total_count": len(final),
        "vector_count": len(vector_results),
        "keyword_count": len(keyword_results),
        "reranked": use_rerank,
    }, ensure_ascii=False)


def _reciprocal_rank_fusion(list_a: list, list_b: list, k: int = 60) -> list:
    """
    倒数排名融合（RRF）算法：合并两路检索结果，按 RRF 分数排序。
    
    RRF(d) = sum(1 / (k + rank_i(d))) 其中 k=60 是平滑常数
    """
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    def _get_key(item: dict) -> str:
        return item["content"][:200]

    for rank, item in enumerate(list_a, start=1):
        key = _get_key(item)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        items[key] = item

    for rank, item in enumerate(list_b, start=1):
        key = _get_key(item)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        if key not in items:
            items[key] = item

    sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    result = []
    for key in sorted_keys:
        item = items[key].copy()
        item["rrf_score"] = scores[key]
        result.append(item)

    return result


# ─────────────────────────────────────────────────────────────
# Tool 3: 查询扩展
# ─────────────────────────────────────────────────────────────

@tool
def rag_query_expand(
    query: str,
    num_subquestions: int = 3,
    context_hint: Optional[str] = None,
) -> str:
    """
    查询扩展工具：将用户原始查询扩展为多个子问题，提升检索召回率。
    支持复杂查询的分解和同义改写。

    Args:
        query: 用户原始查询
        num_subquestions: 生成子问题数量（1-5）
        context_hint: 可选的上下文提示（如知识库名称、领域）

    Returns:
        JSON 字符串，包含 original_query 和 subquestions 列表
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    try:
        llm = ChatOpenAI(
            model=settings.DEFAULT_MODEL,
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
            temperature=0.3,
        )

        context_str = f"\n上下文背景：{context_hint}" if context_hint else ""

        prompt = f"""你是一个信息检索专家。请将用户的查询扩展为 {num_subquestions} 个更具体的子问题，
以提高知识库检索的召回率。子问题应该从不同角度切入，覆盖原查询的各个方面。{context_str}

原始查询：{query}

请以 JSON 格式返回，例如：
{{
  "subquestions": ["子问题1", "子问题2", "子问题3"],
  "query_type": "factual/conceptual/procedural",
  "key_concepts": ["概念1", "概念2"]
}}

只返回 JSON，不要包含其他文字。"""

        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content.strip()

        # 提取 JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content)
        subquestions = parsed.get("subquestions", [])

        logger.info(f"查询扩展完成：原始查询 → {len(subquestions)} 个子问题")

        return json.dumps({
            "original_query": query,
            "subquestions": subquestions,
            "query_type": parsed.get("query_type", "unknown"),
            "key_concepts": parsed.get("key_concepts", []),
        }, ensure_ascii=False)

    except Exception as e:
        logger.warning(f"查询扩展失败，返回原始查询: {e}")
        return json.dumps({
            "original_query": query,
            "subquestions": [query],  # 降级：只用原始查询
            "query_type": "unknown",
            "key_concepts": [],
            "expand_failed": True,
        }, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
# Tool 4: 内容摘要
# ─────────────────────────────────────────────────────────────

@tool
def rag_summarize(
    content: str,
    query: str,
    max_length: int = 500,
) -> str:
    """
    对检索到的文档内容进行针对性摘要，聚焦于与查询相关的部分。

    Args:
        content: 需要摘要的文档内容（可以是多段文本的拼接）
        query: 用户原始查询（用于聚焦摘要方向）
        max_length: 摘要最大字符数

    Returns:
        JSON 字符串，包含 summary 和 key_points
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    try:
        llm = ChatOpenAI(
            model=settings.DEFAULT_MODEL,
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
            temperature=0.3,
        )

        # 截断过长内容
        truncated_content = content[:3000] if len(content) > 3000 else content

        prompt = f"""请针对用户的查询，对以下文档内容进行精准摘要。
摘要应聚焦于与查询最相关的信息，不超过 {max_length} 字。

用户查询：{query}

文档内容：
{truncated_content}

请以 JSON 格式返回：
{{
  "summary": "针对查询的精准摘要",
  "key_points": ["要点1", "要点2", "要点3"],
  "relevance_score": 0.0-1.0
}}

只返回 JSON。"""

        response = llm.invoke([HumanMessage(content=prompt)])
        content_str = response.content.strip()

        if "```json" in content_str:
            content_str = content_str.split("```json")[1].split("```")[0].strip()
        elif "```" in content_str:
            content_str = content_str.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content_str)
        return json.dumps(parsed, ensure_ascii=False)

    except Exception as e:
        logger.error(f"摘要生成失败: {e}")
        return json.dumps({
            "summary": content[:max_length],
            "key_points": [],
            "relevance_score": 0.5,
            "error": str(e),
        }, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
# 工具注册表
# ─────────────────────────────────────────────────────────────

def get_rag_tools() -> list:
    """
    返回所有可用的 RAG 工具列表，可直接传入 LangGraph ToolNode。

    Returns:
        工具列表
    """
    return [
        rag_hybrid_search,
        rag_summarize,
        rag_query_expand,
    ]
