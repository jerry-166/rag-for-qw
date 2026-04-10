from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
import asyncio

from config import init_logger, settings
from services.database import db
from services.auth import get_current_user
from services.elasticsearch_client import es_client
from langchain_openai import OpenAI

logger = init_logger(__name__)
router = APIRouter()

# 支持metadata过滤
class QueryRequest(BaseModel):
    query: str
    limit: int = 5
    metadata_filter: dict = None
    knowledge_base_id: int = None


def rrf(rankings, k=60):
    """Reciprocal Rank Fusion算法"""
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            item_id = item['id'] if 'id' in item else item.get('chunk_id')
            if item_id not in scores:
                scores[item_id] = 0
            scores[item_id] += 1 / (k + rank)
    # 按分数排序
    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [item[0] for item in sorted_items]


def rerank_results(query, results, top_k=5):
    """使用OpenAI模型对搜索结果进行重新排序
    
    Args:
        query: 查询文本
        results: 搜索结果列表
        top_k: 返回的结果数量
    
    Returns:
        重新排序后的结果列表
    """
    if not results:
        return []
    
    try:
        # 初始化OpenAI客户端
        openai_client = OpenAI(
            api_key=settings.LITELLM_API_KEY,
            base_url=settings.LITELLM_BASE_URL
        )
        
        # 构建rerank提示
        prompt = f"请根据以下查询语句，对提供的搜索结果按相关性从高到低排序：\n\n查询语句：{query}\n\n搜索结果：\n"
        
        for i, result in enumerate(results, 1):
            content = result.get('content', result.get('chunk_text', ''))
            prompt += f"{i}. {content[:500]}...\n"
        
        prompt += "\n请返回排序后的结果编号，格式为逗号分隔的数字列表，例如：1,3,2,5,4"
        
        # 调用OpenAI API
        response = openai_client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的信息检索助手，擅长根据查询语句对搜索结果进行相关性排序。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.1,
            max_tokens=100
        )
        
        # 解析响应
        sorted_indices_str = response.choices[0].message.content.strip()
        sorted_indices = [int(idx.strip()) - 1 for idx in sorted_indices_str.split(',')]
        
        # 过滤有效的索引
        valid_indices = [idx for idx in sorted_indices if 0 <= idx < len(results)]
        
        # 构建重新排序的结果
        reranked_results = [results[idx] for idx in valid_indices[:top_k]]
        
        return reranked_results
    except Exception as e:
        logger.error(f"Rerank失败: {str(e)}")
        # 如果rerank失败，返回原始结果
        return results[:top_k]


@router.post("/milvus/query")
async def query_milvus(request: QueryRequest, req: Request, current_user=Depends(get_current_user)):
    """查询Milvus数据"""
    logger.info(f"开始查询Milvus数据，查询文本: {request.query}")
    try:
        # 使用全局Milvus客户端实例
        milvus_client = req.app.state['milvus_client']

        # 执行查询，传递用户权限信息
        # 构建metadata_filter，包含用户权限信息
        metadata_filter = request.metadata_filter or {}

        # 非管理员只能访问自己的文档和有权限的知识库
        if current_user["role"] != "admin":
            metadata_filter["user_id"] = current_user["id"]

        # 如果指定了知识库ID，添加到过滤条件
        if request.knowledge_base_id:
            metadata_filter["knowledge_base_id"] = request.knowledge_base_id

        # 获取更多结果以进行rerank
        raw_results = milvus_client.query(
            query_text=request.query,
            limit=request.limit * 3,  # 获取3倍结果用于rerank
            metadata_filter=metadata_filter
        )

        # 对结果进行重新排序
        results = rerank_results(request.query, raw_results, request.limit)

        logger.debug(f"查询完成，返回 {len(results)} 条结果")

        logger.info(f"查询Milvus数据成功")
        return {
            "status": "success",
            "query": request.query,
            "results": results
        }
    except Exception as e:
        logger.error(f"查询失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/milvus/info")
async def get_milvus_info(req: Request, current_user=Depends(get_current_user)):
    """获取Milvus集合信息"""
    logger.info("开始获取Milvus集合信息")
    try:
        # 只有管理员可以获取Milvus集合信息
        if current_user["role"] != "admin":
            logger.warning(f"非管理员用户尝试获取Milvus集合信息: {current_user['username']}")
            raise HTTPException(status_code=403, detail="无权限访问该接口")

        # 使用全局Milvus客户端实例
        milvus_client = req.app.state['milvus_client']

        # 获取集合信息
        info = milvus_client.get_collection_info()
        logger.debug(f"获取集合信息: {info}")

        logger.info("获取Milvus集合信息成功")
        return {
            "status": "success",
            "info": info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Milvus信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取Milvus信息失败: {str(e)}")


@router.post("/elasticsearch/search")
async def search_elasticsearch(request: QueryRequest, current_user=Depends(get_current_user)):
    """Elasticsearch关键词检索"""
    logger.info(f"开始Elasticsearch关键词检索，查询文本: {request.query}")
    try:
        # 构建filters，包含知识库ID
        filters = request.metadata_filter or {}
        if request.knowledge_base_id:
            filters["knowledge_base_id"] = request.knowledge_base_id
        
        # 执行关键词搜索
        # 获取更多结果以进行rerank
        raw_results = es_client.search(
            query=request.query,
            user_id=current_user["id"],
            size=request.limit * 3,  # 获取3倍结果用于rerank
            filters=filters
        )

        # 对结果进行重新排序
        results = rerank_results(request.query, raw_results, request.limit)

        logger.debug(f"搜索完成，返回 {len(results)} 条结果")

        logger.info("Elasticsearch关键词检索成功")
        return {
            "status": "success",
            "query": request.query,
            "results": results
        }
    except Exception as e:
        logger.error(f"搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.post("/hybrid/search")
async def hybrid_search(request: QueryRequest, req: Request, current_user=Depends(get_current_user)):
    """混合检索（关键词 + 向量）"""
    logger.info(f"开始混合检索，查询文本: {request.query}")
    try:
        # 并行执行检索

        # 执行Elasticsearch关键词检索
        async def es_search():
            filters = request.metadata_filter or {}
            # 如果指定了知识库ID，添加到过滤条件
            if request.knowledge_base_id:
                filters["knowledge_base_id"] = request.knowledge_base_id
            return es_client.search(
                query=request.query,
                user_id=current_user["id"],
                size=request.limit * 2,  # 获取更多结果以提高RRF效果
                filters=filters
            )

        # 执行Milvus向量检索
        async def milvus_search():
            milvus_client = req.app.state['milvus_client']
            metadata_filter = request.metadata_filter or {}
            if current_user["role"] != "admin":
                metadata_filter["user_id"] = current_user["id"]
            # 如果指定了知识库ID，添加到过滤条件
            if request.knowledge_base_id:
                metadata_filter["knowledge_base_id"] = request.knowledge_base_id
            return milvus_client.query(
                query_text=request.query,
                limit=request.limit * 2,  # 获取更多结果以提高RRF效果
                metadata_filter=metadata_filter
            )

        # 并行执行两个检索
        es_results, milvus_results = await asyncio.gather(
            es_search(),
            milvus_search()
        )

        # 准备RRF输入
        rankings = []

        # 处理ES结果
        if es_results:
            rankings.append(es_results)

        # 处理Milvus结果
        if milvus_results:
            rankings.append(milvus_results)

        # 使用RRF合并结果
        if rankings:
            final_ids = rrf(rankings)
            # 限制返回结果数量
            final_ids = final_ids[:request.limit]

            # 从PostgreSQL获取完整的chunk信息
            if final_ids:
                chunks = db.get_document_chunks_by_ids(final_ids)
                # 构建结果列表，保持RRF排序
                final_results = []
                id_to_chunk = {chunk['id']: chunk for chunk in chunks}
                # 计算RRF分数
                scores = {}
                for ranking in rankings:
                    for rank, item in enumerate(ranking, 1):
                        item_id = item['id'] if 'id' in item else item.get('chunk_id')
                        if item_id not in scores:
                            scores[item_id] = 0
                        scores[item_id] += 1 / (60 + rank)

                for chunk_id in final_ids:
                    if chunk_id in id_to_chunk:
                        chunk = id_to_chunk[chunk_id]
                        # 使用RRF分数
                        chunk['score'] = scores.get(chunk_id, 0.0)
                        final_results.append(chunk)
            else:
                final_results = []
        else:
            final_results = []

        # 对混合检索结果进行重新排序
        reranked_results = rerank_results(request.query, final_results, request.limit)

        logger.debug(f"混合检索完成，返回 {len(reranked_results)} 条结果")

        logger.info("混合检索成功")
        return {
            "status": "success",
            "query": request.query,
            "results": reranked_results
        }
    except Exception as e:
        logger.error(f"混合检索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"混合检索失败: {str(e)}")
