"""
共享检索函数模块

为三种 Agent 类型提供统一的真实检索实现：
- SimpleAgent  → `func(query, top_k)` 返回 `List[dict]`
- AdvancedAgent → `func(query, top_k, entities)` 返回 `dict`（TaskPlanner 格式）
- ClawAgent   → 直接使用 `rag_tools.rag_hybrid_search`（已内置）

所有实现都基于 `rag_tools.rag_hybrid_search`（Milvus + ES 混合检索 + Rerank）。
"""

import json
import asyncio
from typing import List, Dict, Any, Optional, Callable
from functools import partial

from config import init_logger

logger = init_logger(__name__)


# ─────────────────────────────────────────────────────────────
# 核心检索函数（LangChain @tool 同步包装）
# ─────────────────────────────────────────────────────────────

def _call_hybrid_search(
    query: str,
    knowledge_base_id: Optional[int] = None,
    top_k: int = 10,
    use_vector: bool = True,
    use_keyword: bool = True,
    use_rerank: bool = True,
    rerank_top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    底层检索调用：同步包装 rag_hybrid_search.invoke()。

    Returns:
        List[Dict] — 检索结果列表，每项含 content/score/metadata
    """
    from agent.claw_agent.tools.rag_tools import rag_hybrid_search

    try:
        result_json = rag_hybrid_search.invoke({
            "query": query,
            "knowledge_base_id": knowledge_base_id,
            "top_k": top_k,
            "use_vector": use_vector,
            "use_keyword": use_keyword,
            "use_rerank": use_rerank,
            "rerank_top_k": rerank_top_k,
        })
        data = json.loads(result_json)
        results = data.get("results", [])
        logger.info(f"[retrieval] 检索成功，返回 {len(results)} 条结果")
        return results
    except Exception as e:
        logger.error(f"[retrieval] 检索失败: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# SimpleAgent 适配器：同步签名
# ─────────────────────────────────────────────────────────────

def simple_retriever(
    query: str,
    top_k: int = 5,
    knowledge_base_id: Optional[int] = None,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    SimpleAgent 使用的检索函数。

    SimpleAgent._get_context() 期望：
        func(query) -> List[dict]，每项含 content 和 score

    格式示例：
        [
            {"content": "...", "score": 0.92, "metadata": {...}},
            ...
        ]
    """
    return _call_hybrid_search(
        query=query,
        knowledge_base_id=knowledge_base_id,
        top_k=top_k,
        use_rerank=True,
        rerank_top_k=top_k,
    )


# ─────────────────────────────────────────────────────────────
# AdvancedAgent 适配器：async 函数签名
# ─────────────────────────────────────────────────────────────

async def advanced_retriever(
    query: str = "",
    top_k: int = 5,
    entities: Optional[List[str]] = None,
    knowledge_base_id: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    AdvancedAgent 使用的检索函数。

    AdvancedRAGAgent 注册的 knowledge_retrieval_tool 期望：
        func(query, top_k, entities) -> dict

    TaskPlanner 生成的参数格式为 {query, top_k, entities, ...}，
    多余参数由 **kwargs 接收。

    返回格式（TaskPlanner 的 task_results 消费）：
        {"results": [...], "total": N, "query": query}
    """
    # 实体列表作为关键词补充到查询中
    enhanced_query = query
    if entities:
        entity_str = " ".join(entities)
        enhanced_query = f"{query} {entity_str}"

    results = await asyncio.to_thread(
        _call_hybrid_search,
        query=enhanced_query,
        knowledge_base_id=knowledge_base_id,
        top_k=top_k,
        use_rerank=True,
        rerank_top_k=top_k,
    )

    return {
        "results": results,
        "total": len(results),
        "query": query,
        "entities": entities or [],
    }


# ─────────────────────────────────────────────────────────────
# 工厂函数（供 api/agent.py 统一调用）
# ─────────────────────────────────────────────────────────────

def get_retriever_for_simple() -> Callable:
    """返回适配 SimpleAgent 的同步检索函数。"""
    return simple_retriever


def get_retriever_for_advanced() -> Callable:
    """返回适配 AdvancedAgent 的异步检索函数。"""
    return advanced_retriever
