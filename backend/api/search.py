"""
搜索 API 模块 — 提供三种检索端点

架构:
  1. 多路并行召回（Milvus 向量 + ES 关键词）
  2. RRF 融合排序
  3. PostgreSQL 补全完整内容
  4. 可选 Reranker 精排
  5. 返回 Top-K 结果

Reranker 已抽离至 services/reranker.py，通过 get_reranker() 获取实例。
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
import asyncio

from config import init_logger, settings
from services.database import db
from services.auth import get_current_user
from services.reranker import get_reranker
from services.bm25_client import get_backend_type

logger = init_logger(__name__)
router = APIRouter()

class QueryRequest(BaseModel):
    """通用查询请求"""
    query: str
    limit: int = 5
    metadata_filter: dict = None
    knowledge_base_id: int = None
    use_rerank: bool = True  # 是否启用 rerank 精排


_RRF_DEFAULT_K = 60


def rrf_fusion(rankings, k=_RRF_DEFAULT_K):
    """
    Reciprocal Rank Fusion — 合并多路召回结果并返回 (ID列表, 分数字典)。

    Args:
        rankings: 多路结果列表，每路为有序 dict 列表（需包含 id/chunk_id）
        k: RRF 平滑参数，默认 60

    Returns:
        (sorted_ids, scores_dict) — 排序后的 ID 列表和对应的分数映射
    """
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            item_id = item['id'] if 'id' in item else item.get('chunk_id')
            if item_id is not None:
                scores[item_id] = scores.get(item_id, 0.0) + 1 / (k + rank)

    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_items], dict(sorted_items)


def _build_metadata_filter(request: QueryRequest, current_user: dict) -> dict:
    """构建 Milvus metadata 过滤条件（含权限控制）。"""
    f = request.metadata_filter.copy() if request.metadata_filter else {}
    if current_user["role"] != "admin":
        f["user_id"] = current_user["id"]
    if request.knowledge_base_id:
        f["knowledge_base_id"] = request.knowledge_base_id
    return f


def _build_es_filters(request: QueryRequest) -> dict:
    """构建 Elasticsearch 过滤条件。"""
    f = request.metadata_filter.copy() if request.metadata_filter else {}
    if request.knowledge_base_id:
        f["knowledge_base_id"] = request.knowledge_base_id
    return f


async def _es_search(request: QueryRequest, req, current_user: dict) -> list:
    """执行关键词检索（BM25 或 ES，由 SEARCH_BACKEND 配置决定）。"""
    search_client = req.app.state['search_client']
    filters = _build_es_filters(request)
    multiplier = 2 if request.use_rerank else 1
    return search_client.search(
        query=request.query,
        user_id=current_user["id"],
        size=request.limit * multiplier,
        filters=filters,
    )


async def _milvus_search(request: QueryRequest, req: Request, current_user: dict) -> list:
    """执行 Milvus 向量检索。"""
    milvus_client = req.app.state['milvus_client']
    metadata_filter = _build_metadata_filter(request, current_user)
    multiplier = 2 if request.use_rerank else 1
    return milvus_client.query(
        query_text=request.query,
        limit=request.limit * multiplier,
        metadata_filter=metadata_filter,
    )


def _enrich_results(final_ids: list, rrf_scores: dict) -> list:
    """从 PostgreSQL 补充完整 chunk 内容，并附加 RRF 分数。"""
    if not final_ids:
        return []

    chunks = db.get_document_chunks_by_ids(final_ids)
    id_to_chunk = {chunk['id']: chunk for chunk in chunks}

    results = []
    for cid in final_ids:
        if cid in id_to_chunk:
            chunk = id_to_chunk[cid]
            chunk['score'] = rrf_scores.get(cid, 0.0)
            results.append(chunk)

    return results


def _optional_rerank(query: str, results: list, top_k: int, enabled: bool) -> list:
    """根据 enabled 决定是否执行 Rerank 精排。"""
    if not enabled or not results:
        return results[:top_k] if results else []

    reranker = get_reranker()
    return reranker.rerank(query, results, top_k)


# ============================================================
# API 端点
# ============================================================

@router.post("/milvus/query")
async def query_milvus(
    request: QueryRequest,
    req: Request,
    current_user=Depends(get_current_user),
):
    """
    纯向量检索 — 仅使用 Milvus 做语义相似度匹配。

    流程: Query → Embedding → Milvus ANN Search → [可选] Rerank → Top-K
    """
    logger.info(f"开始 Milvus 向量检索, 查询文本: {request.query}")

    try:
        milvus_client = req.app.state['milvus_client']
        metadata_filter = _build_metadata_filter(request, current_user)

        # 召回：use_rerank 时多取几条供精排使用
        multiplier = 3 if request.use_rerank else 1
        raw_results = milvus_client.query(
            query_text=request.query,
            limit=request.limit * multiplier,
            metadata_filter=metadata_filter,
        )

        # 可选精排
        results = _optional_rerank(
            request.query, raw_results, request.limit, request.use_rerank
        )

        logger.debug(f"Milvus 检索完成, 返回 {len(results)} 条结果")
        logger.info("Milvus 向量检索成功")

        return {
            "status": "success",
            "query": request.query,
            "results": results,
        }

    except Exception as e:
        logger.error(f"Milvus 检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"检索失败: {e}")


@router.get("/milvus/info")
async def get_milvus_info(req: Request, current_user=Depends(get_current_user)):
    """获取 Milvus 集合信息（仅管理员）。"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权限访问该接口")

    milvus_client = req.app.state['milvus_client']
    info = milvus_client.get_collection_info()
    return {"status": "success", "info": info}


@router.post("/elasticsearch/search")
async def search_elasticsearch(
    request: QueryRequest,
    req: Request,
    current_user=Depends(get_current_user),
):
    """
    纯关键词检索 — 使用配置的搜索引擎（BM25 或 ES）做关键词匹配。

    流程: Query → Search Match → [可选] Rerank → Top-K
    """
    logger.info(f"开始关键词检索, 查询文本: {request.query}, 后端={get_backend_type()}")

    try:
        filters = _build_es_filters(request)
        search_client = req.app.state['search_client']

        # 召回
        multiplier = 3 if request.use_rerank else 1
        raw_results = search_client.search(
            query=request.query,
            user_id=current_user["id"],
            size=request.limit * multiplier,
            filters=filters,
        )

        # 可选精排
        results = _optional_rerank(
            request.query, raw_results, request.limit, request.use_rerank
        )

        logger.debug(f"ES 检索完成, 返回 {len(results)} 条结果")
        logger.info("Elasticsearch 关键词检索成功")

        return {
            "status": "success",
            "query": request.query,
            "results": results,
        }

    except Exception as e:
        logger.error(f"ES 检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"检索失败: {e}")


@router.post("/hybrid/search")
async def hybrid_search(
    request: QueryRequest,
    req: Request,
    current_user=Depends(get_current_user),
):
    """
    混合检索 — 并行调用 ES + Milvus，经 RRF 融合后可选 Rerank 精排。

    完整流程:
      1. 并行召回: ES(关键词) + Milvus(向量·摘要+子问题)
      2. RRF 融合: 合并多路结果、去重、按排名打分
      3. 数据补全: 通过 PostgreSQL 获取完整 chunk 内容
      4. 精排:   可选 Cross-Encoder / LLM 重排序
      5. 返回:   最终 Top-K 结果
    """
    logger.info(f"开始混合检索, 查询文本: {request.query}")

    try:
        # ---- Step 1: 并行召回 ----
        es_results, milvus_results = await asyncio.gather(
            _es_search(request, req, current_user),
            _milvus_search(request, req, current_user),
        )

        # ---- Step 2: RRF 融合 ----
        rankings = []
        if es_results:
            rankings.append(es_results)
        if milvus_results:
            rankings.append(milvus_results)

        if not rankings:
            return {
                "status": "success",
                "query": request.query,
                "results": [],
            }

        final_ids, rrf_scores = rrf_fusion(rankings)
        # 截断到合理数量再查 PG（减少 DB 压力）
        rerank_pool_size = request.limit * 3 if request.use_rerank else request.limit
        final_ids = final_ids[:rerank_pool_size]

        # ---- Step 3: PG 补全内容 ----
        final_results = _enrich_results(final_ids, rrf_scores)

        # ---- Step 4: 可选 Rerank 精排 ----
        reranked = _optional_rerank(
            request.query, final_results, request.limit, request.use_rerank
        )

        logger.debug(f"混合检索完成, 返回 {len(reranked)} 条结果")
        logger.info("混合检索成功")

        return {
            "status": "success",
            "query": request.query,
            "results": reranked,
        }

    except Exception as e:
        logger.error(f"混合检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"混合检索失败: {e}")
