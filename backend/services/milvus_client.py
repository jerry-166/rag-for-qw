from typing import Optional
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, list_collections
import time

from config import settings, init_logger

# 初始化日志记录器
logger = init_logger(__name__)

class MilvusClient:
    def __init__(self, host=settings.MILVUS_HOST, port=settings.MILVUS_PORT, db_name=settings.MILVUS_DB_NAME):
        self.host = host
        self.port = port
        self.db_name = db_name
        self.summaries_collection = None
        self.subquestions_collection = None
        self.chunks_collection = None  # [新增] chunk原文向量集合（Native检索）
        self.connect()
    
    def connect(self):
        """连接到Milvus"""
        try:
            # 先连接到默认数据库，使用IPv4地址
            connections.connect(
                alias="default",
                host="127.0.0.1",  # 使用127.0.0.1而不是localhost，避免IPv6连接问题
                port=self.port,
                timeout=30  # 设置连接超时为30秒
            )
            
            # 检查数据库是否存在
            from pymilvus import db
            databases = db.list_database()
            if self.db_name not in databases:
                # 创建数据库
                db.create_database(self.db_name)
                logger.info(f"创建Milvus数据库成功: {self.db_name}")
            else:
                logger.info(f"Milvus数据库已存在: {self.db_name}")
            
            # 切换到目标数据库
            db.using_database(self.db_name)
            logger.info(f"Milvus连接成功，使用数据库: {self.db_name}")
            return True
        except Exception as e:
            logger.error(f"Milvus连接失败: {e}")
            return False
    
    def get_collections(self):
        """获取集合列表"""
        try:
            return list_collections()
        except Exception as e:
            logger.error(f"获取集合列表失败: {e}")
            return []
    
    def create_collections(self):
        """创建集合"""
        try:
            # 检查连接是否存在，如果不存在，重新连接
            try:
                # 尝试获取集合列表，测试连接是否存在
                from pymilvus import list_collections
                list_collections()
            except Exception as conn_error:
                logger.warning(f"Milvus连接不存在，尝试重新连接: {conn_error}")
                if not self.connect():
                    logger.error("重新连接失败")
                    return False
            
            # 检查集合是否已存在
            collections = self.get_collections()
            
            # 创建摘要集合
            if settings.MILVUS_SUMMARIES_COLLECTION not in collections:
                summaries_fields = [
                    FieldSchema(name="chunk_id", dtype=DataType.INT64, is_primary=True, auto_id=True),  # 使用Milvus自动ID
                    FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="summary_text", dtype=DataType.VARCHAR, max_length=2000),
                    FieldSchema(name="summary_vector", dtype=DataType.FLOAT_VECTOR, dim=1536),
                    FieldSchema(name="created_at", dtype=DataType.INT64),
                    FieldSchema(name="knowledge_base_id", dtype=DataType.INT64),  # 添加knowledge_base_id字段
                    FieldSchema(name="document_id", dtype=DataType.INT64),  # 添加document_id字段
                    FieldSchema(name="metadata", dtype=DataType.JSON)  # 添加metadata字段
                ]
                summaries_schema = CollectionSchema(fields=summaries_fields, description="文档摘要集合")
                self.summaries_collection = Collection(name=settings.MILVUS_SUMMARIES_COLLECTION, schema=summaries_schema)
                
                # 创建摘要向量索引
                summaries_index_params = {
                    "index_type": "AUTOINDEX",
                    "metric_type": "COSINE"
                }
                self.summaries_collection.create_index(field_name="summary_vector", index_params=summaries_index_params)
                logger.info("摘要集合创建成功")
            else:
                # 集合已存在，直接获取
                self.summaries_collection = Collection(name=settings.MILVUS_SUMMARIES_COLLECTION)
                logger.info("摘要集合已存在，直接使用")
            
            # 创建子问题集合
            if settings.MILVUS_SUBQUESTIONS_COLLECTION not in collections:
                subquestions_fields = [
                    FieldSchema(name="subquestion_id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="chunk_id", dtype=DataType.INT64),
                    FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="question_text", dtype=DataType.VARCHAR, max_length=500),
                    FieldSchema(name="question_vector", dtype=DataType.FLOAT_VECTOR, dim=1536),
                    FieldSchema(name="created_at", dtype=DataType.INT64),
                    FieldSchema(name="knowledge_base_id", dtype=DataType.INT64),  # 添加knowledge_base_id字段
                    FieldSchema(name="document_id", dtype=DataType.INT64),  # 添加document_id字段
                    FieldSchema(name="metadata", dtype=DataType.JSON)  # 添加metadata字段
                ]
                subquestions_schema = CollectionSchema(fields=subquestions_fields, description="文档子问题集合")
                self.subquestions_collection = Collection(name=settings.MILVUS_SUBQUESTIONS_COLLECTION, schema=subquestions_schema)
                
                # 创建子问题向量索引
                subquestions_index_params = {
                    "index_type": "AUTOINDEX",
                    "metric_type": "COSINE"
                }
                self.subquestions_collection.create_index(field_name="question_vector",
                                                          index_params=subquestions_index_params)
                logger.info("子问题集合创建成功")
            else:
                # 集合已存在，直接获取
                self.subquestions_collection = Collection(name=settings.MILVUS_SUBQUESTIONS_COLLECTION)
                logger.info("子问题集合已存在，直接使用")
            
            # ── 新增：chunk原文向量集合（Native检索）──
            logger.info(f"开始处理chunk原文向量集合: {settings.MILVUS_CHUNKS_COLLECTION}")
            if settings.MILVUS_CHUNKS_COLLECTION not in collections:
                logger.info("chunk原文向量集合不存在，开始创建...")
                chunks_fields = [
                    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="pg_chunk_id", dtype=DataType.INT64),
                    FieldSchema(name="document_id", dtype=DataType.INT64),
                    FieldSchema(name="knowledge_base_id", dtype=DataType.INT64),
                    FieldSchema(name="chunk_index", dtype=DataType.INT64),
                    FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="chunk_vector", dtype=DataType.FLOAT_VECTOR, dim=1536),
                    FieldSchema(name="created_at", dtype=DataType.INT64),
                    FieldSchema(name="metadata", dtype=DataType.JSON),
                ]
                chunks_schema = CollectionSchema(fields=chunks_fields, description="chunk原文向量集合，用于Native检索")
                logger.info("创建chunk原文向量集合对象...")
                self.chunks_collection = Collection(name=settings.MILVUS_CHUNKS_COLLECTION, schema=chunks_schema)
                logger.info("创建chunk原文向量索引...")
                # 使用 IVF_FLAT 索引，创建速度更快
                self.chunks_collection.create_index(
                    field_name="chunk_vector",
                    index_params={"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}}
                )
                logger.info("chunk原文向量集合创建成功")
            else:
                logger.info("chunk原文向量集合已存在，直接获取...")
                self.chunks_collection = Collection(name=settings.MILVUS_CHUNKS_COLLECTION)
                logger.info("chunk原文向量集合已存在，直接使用")
            # ────────────────────────────────────────
            
            return True
        except Exception as e:
            logger.error(f"创建集合失败: {e}")
            return False 

    def import_data(self, datas, user_id=None, role="user", knowledge_base_id=None):
        """导入数据到Milvus"""
        if not self.summaries_collection or not self.subquestions_collection:
            # 尝试创建集合
            if not self.create_collections():
                logger.error("集合创建失败")
                return False
        
        logger.info(f"开始导入 {len(datas)} 个文档数据")
        
        summaries_chunk_texts = []
        summaries_texts = []
        summaries_vectors = []
        summaries_created_at = []
        summaries_knowledge_base_ids = []
        summaries_document_ids = []
        summaries_metadata = []
        
        subquestions_chunk_texts = []
        subquestions_texts = []
        subquestions_vectors = []
        subquestions_created_at = []
        subquestions_knowledge_base_ids = []
        subquestions_document_ids = []
        subquestions_metadata = []
        
        timestamp = int(time.time() * 1000)
        
        for i, doc in enumerate(datas):
            metadata = doc.metadata if hasattr(doc, 'metadata') else {}
            # 添加用户权限信息到metadata
            metadata["user_id"] = user_id
            metadata["role"] = role
            metadata["knowledge_base_id"] = knowledge_base_id
            
            # 从metadata中获取document_id，并确保它是整数类型
            document_id = int(metadata.get("document_id", 0))
            
            if doc.summary and doc.summary_embedding:
                summaries_chunk_texts.append(doc.chunk)
                summaries_texts.append(doc.summary)
                summaries_vectors.append(doc.summary_embedding)
                summaries_created_at.append(timestamp)
                summaries_knowledge_base_ids.append(knowledge_base_id)
                summaries_document_ids.append(document_id)
                summaries_metadata.append(metadata)
            if doc.sub_questions and doc.subq_embeddings:
                for subq, embedding in zip(doc.sub_questions, doc.subq_embeddings):
                    if subq and embedding:
                        subquestions_chunk_texts.append(doc.chunk)
                        subquestions_texts.append(subq)
                        subquestions_vectors.append(embedding)
                        subquestions_created_at.append(timestamp)
                        subquestions_knowledge_base_ids.append(knowledge_base_id)
                        subquestions_document_ids.append(document_id)
                        subquestions_metadata.append(metadata)
        
        import_result = {}
        
        if summaries_chunk_texts:
            logger.info(f"导入 {len(summaries_chunk_texts)} 条摘要数据")
            summaries_entities = [
                summaries_chunk_texts,
                summaries_texts,
                summaries_vectors,
                summaries_created_at,
                summaries_knowledge_base_ids,
                summaries_document_ids,
                summaries_metadata
            ]
            try:
                logger.info("开始执行摘要数据插入...")
                # 设置插入超时为60秒
                self.summaries_collection.insert(summaries_entities, timeout=60)
                logger.info("摘要数据导入成功")
                import_result["summaries_count"] = len(summaries_chunk_texts)
            except Exception as e:
                logger.error(f"导入摘要数据失败: {e}")
                return False
        
        if subquestions_chunk_texts:
            logger.info(f"导入 {len(subquestions_chunk_texts)} 条子问题数据")
            # 为子问题生成chunk_id（使用文档索引）
            subquestions_chunk_ids = []
            for i, doc in enumerate(datas):
                if doc.sub_questions and doc.subq_embeddings:
                    for _ in doc.sub_questions:
                        subquestions_chunk_ids.append(i + 1)
            
            subquestions_entities = [
                subquestions_chunk_ids,
                subquestions_chunk_texts,
                subquestions_texts,
                subquestions_vectors,
                subquestions_created_at,
                subquestions_knowledge_base_ids,
                subquestions_document_ids,
                subquestions_metadata
            ]
            try:
                self.subquestions_collection.insert(subquestions_entities)
                logger.info("子问题数据导入成功")
                import_result["subquestions_count"] = len(subquestions_chunk_ids)
            except Exception as e:
                logger.error(f"导入子问题数据失败: {e}")
                return False
        
        # ── 新增：写入 chunk 原文向量集合 ──────────────────────────────
        chunks_pg_ids, chunks_doc_ids, chunks_kb_ids = [], [], []
        chunks_indices, chunks_texts, chunks_vectors = [], [], []
        chunks_ts_list, chunks_meta_list = [], []

        for doc in datas:
            if doc.chunk_embedding:
                meta = doc.metadata if hasattr(doc, "metadata") else {}
                chunks_pg_ids.append(int(meta.get("chunk_id", 0)))
                chunks_doc_ids.append(int(meta.get("document_id", 0)))
                chunks_kb_ids.append(knowledge_base_id)
                chunks_indices.append(int(meta.get("chunk_index", 0)))
                chunks_texts.append(doc.chunk)
                chunks_vectors.append(doc.chunk_embedding)
                chunks_ts_list.append(timestamp)
                chunks_meta_list.append(meta)

        if chunks_texts:
            if not self.chunks_collection:
                self.create_collections()
            try:
                self.chunks_collection.insert([
                    chunks_pg_ids, chunks_doc_ids, chunks_kb_ids,
                    chunks_indices, chunks_texts, chunks_vectors,
                    chunks_ts_list, chunks_meta_list,
                ])
                logger.info(f"chunk原文向量写入成功，共 {len(chunks_texts)} 条")
                import_result["chunks_count"] = len(chunks_texts)
            except Exception as e:
                logger.error(f"写入chunk原文向量失败: {e}")
        # ────────────────────────────────────────────────────────────
        
        # flush 确保数据持久化（insert 后不需要 load，load 是查询前才需要的）
        self.summaries_collection.flush()
        self.subquestions_collection.flush()
        if self.chunks_collection and chunks_texts:
            self.chunks_collection.flush()
        logger.info("数据导入完成")
        return import_result
    
    def query(self, query_text, limit=5, metadata_filter=None, retrieval_mode="advanced"):
        """
        查询Milvus数据，支持三种检索模式：

        retrieval_mode:
          "native"   — 仅对 chunk 原文向量进行检索（高保真，直接语义匹配）
          "advanced" — 仅对 summary + sub_question 向量检索（默认，原有逻辑）
          "hybrid"   — 三路并行检索，RRF 融合去重后返回（召回最全面）
        """
        if not self.summaries_collection or not self.subquestions_collection:
            if not self.create_collections():
                logger.error("集合创建失败")
                return []

        # 生成查询嵌入
        from langchain_openai import OpenAIEmbeddings
        embedding_model = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.LITELLM_API_KEY,
            base_url=settings.LITELLM_BASE_URL,
        )
        query_embedding = [embedding_model.embed_query(query_text)]

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        # 构建过滤表达式
        conditions = []
        filter_copy = dict(metadata_filter) if metadata_filter else {}
        if "knowledge_base_id" in filter_copy:
            knowledge_base_id = filter_copy.pop("knowledge_base_id")
            conditions.append(f"knowledge_base_id == {knowledge_base_id}")
        for key, value in filter_copy.items():
            if isinstance(value, str):
                conditions.append(f"metadata[\'{key}\'] == \'{value}\'")
            else:
                conditions.append(f"metadata[\'{key}\'] == {value}")
        expr = " && ".join(conditions) if conditions else None

        # ── 各路检索 ──────────────────────────────────────────────────────

        def _search_summaries():
            hits_list = self.summaries_collection.search(
                data=query_embedding, anns_field="summary_vector",
                param=search_params, limit=limit, expr=expr,
                output_fields=["chunk_id", "chunk_text", "summary_text", "created_at", "metadata"]
            )
            results = []
            for hits in hits_list:
                for hit in hits:
                    results.append({
                        "type": "summary",
                        "chunk_id": hit.entity.get("chunk_id"),
                        "chunk_text": hit.entity.get("chunk_text"),
                        "content": hit.entity.get("summary_text"),
                        "distance": hit.distance,
                        "created_at": hit.entity.get("created_at"),
                        "metadata": hit.entity.get("metadata"),
                    })
            return results

        def _search_subquestions():
            hits_list = self.subquestions_collection.search(
                data=query_embedding, anns_field="question_vector",
                param=search_params, limit=limit, expr=expr,
                output_fields=["chunk_id", "chunk_text", "question_text", "created_at", "metadata"]
            )
            results = []
            for hits in hits_list:
                for hit in hits:
                    results.append({
                        "type": "subquestion",
                        "chunk_id": hit.entity.get("chunk_id"),
                        "chunk_text": hit.entity.get("chunk_text"),
                        "content": hit.entity.get("question_text"),
                        "distance": hit.distance,
                        "created_at": hit.entity.get("created_at"),
                        "metadata": hit.entity.get("metadata"),
                    })
            return results

        def _search_chunks():
            if not self.chunks_collection:
                logger.warning("chunk_vectors 集合未初始化，跳过 native 检索")
                return []
            hits_list = self.chunks_collection.search(
                data=query_embedding, anns_field="chunk_vector",
                param=search_params, limit=limit, expr=expr,
                output_fields=["pg_chunk_id", "chunk_text", "chunk_index", "created_at", "metadata"]
            )
            results = []
            for hits in hits_list:
                for hit in hits:
                    results.append({
                        "type": "native",
                        "chunk_id": hit.entity.get("pg_chunk_id"),
                        "chunk_text": hit.entity.get("chunk_text"),
                        "content": hit.entity.get("chunk_text"),  # native模式 content 即 chunk_text
                        "distance": hit.distance,
                        "created_at": hit.entity.get("created_at"),
                        "metadata": hit.entity.get("metadata"),
                    })
            return results

        # ── 按模式执行检索 ─────────────────────────────────────────────────

        logger.info(f"[MilvusClient] 开始检索, retrieval_mode={retrieval_mode}, limit={limit}, query_len={len(query_text)}")

        if retrieval_mode == "native":
            logger.info(f"[MilvusClient] 使用 native 模式：仅检索 chunk 原文向量")
            results = _search_chunks()
            results.sort(key=lambda x: x["distance"], reverse=True)
            logger.info(f"[MilvusClient] native 模式检索完成，返回 {len(results)} 条结果")
            return results[:limit]

        elif retrieval_mode == "advanced":
            logger.info(f"[MilvusClient] 使用 advanced 模式：检索 summaries + subquestions")
            results = _search_summaries() + _search_subquestions()
            results.sort(key=lambda x: x["distance"], reverse=True)
            logger.info(f"[MilvusClient] advanced 模式检索完成，返回 {len(results)} 条结果")
            return results[:limit]

        else:  # "hybrid" — RRF 融合三路结果
            logger.info(f"[MilvusClient] 使用 hybrid 模式：三路并行检索 + RRF 融合")
            summary_res = _search_summaries()
            subq_res = _search_subquestions()
            chunk_res = _search_chunks()

            # RRF (Reciprocal Rank Fusion)  score = Σ 1/(rank + k)
            K = 60
            rrf_scores: dict = {}   # key: chunk_text（去重锚点）
            rrf_items: dict = {}    # key → best hit

            for result_list in [summary_res, subq_res, chunk_res]:
                for rank, item in enumerate(result_list):
                    key = item["chunk_text"]
                    score = 1.0 / (rank + 1 + K)
                    if key not in rrf_scores:
                        rrf_scores[key] = 0.0
                        rrf_items[key] = item
                    rrf_scores[key] += score
                    # 保留 distance 最高的那条 hit 作为代表
                    if item["distance"] > rrf_items[key]["distance"]:
                        rrf_items[key] = item

            # 按 RRF 分排序
            sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)
            merged = []
            for k in sorted_keys[:limit]:
                item = dict(rrf_items[k])
                item["rrf_score"] = rrf_scores[k]
                merged.append(item)

            logger.info(
                f"hybrid 检索完成：summary={len(summary_res)}, subq={len(subq_res)}, "
                f"native={len(chunk_res)}, merged={len(merged)}"
            )
            return merged
    
    def get_collection_info(self):
        """获取集合信息"""
        try:
            collections = self.get_collections()
            info = {}
            
            for collection_name in collections:
                if collection_name in [settings.MILVUS_SUMMARIES_COLLECTION, settings.MILVUS_SUBQUESTIONS_COLLECTION, settings.MILVUS_CHUNKS_COLLECTION]:
                    collection = Collection(collection_name)
                    info[collection_name] = {
                        "num_entities": collection.num_entities
                    }
            
            return info
        except Exception as e:
            logger.error(f"获取集合信息失败: {e}")
            return {}
    
    def close(self):
        """关闭连接"""
        try:
            connections.disconnect("default")
            logger.info("Milvus连接已关闭")
        except Exception as e:
            logger.error(f"关闭连接失败: {e}")
    
    def delete_data_by_knowledge_base(self, knowledge_base_id):
        """根据知识库ID删除Milvus中的对应数据"""
        try:
            if not self.summaries_collection or not self.subquestions_collection:
                logger.warning("集合未初始化，跳过删除操作")
                return True
            
            # 删除摘要集合中对应知识库的数据
            logger.info(f"开始删除知识库ID为{knowledge_base_id}的摘要数据")
            expr = f"knowledge_base_id == {knowledge_base_id}"
            self.summaries_collection.delete(expr)
            logger.info("摘要数据删除成功")
            
            # 删除子问题集合中对应知识库的数据
            logger.info(f"开始删除知识库ID为{knowledge_base_id}的子问题数据")
            self.subquestions_collection.delete(expr)
            logger.info("子问题数据删除成功")
            
            # 删除chunk原文向量集合中对应知识库的数据
            if self.chunks_collection:
                logger.info(f"开始删除知识库ID为{knowledge_base_id}的chunk原文向量数据")
                self.chunks_collection.delete(expr)
                logger.info("chunk原文向量数据删除成功")
            
            return True
        except Exception as e:
            logger.error(f"删除Milvus数据失败: {e}")
            return False
    
    def delete_data_by_document(self, document_id):
        """根据文档ID删除Milvus中的对应数据"""
        try:
            if not self.summaries_collection or not self.subquestions_collection:
                logger.warning("集合未初始化，跳过删除操作")
                return True
            
            # 确保document_id是整数类型
            document_id = int(document_id)
            
            # 删除摘要集合中对应文档的数据
            logger.info(f"开始删除文档ID为{document_id}的摘要数据")
            expr = f"document_id == {document_id}"
            self.summaries_collection.delete(expr)
            logger.info("摘要数据删除成功")
            
            # 删除子问题集合中对应文档的数据
            logger.info(f"开始删除文档ID为{document_id}的子问题数据")
            self.subquestions_collection.delete(expr)
            logger.info("子问题数据删除成功")
            
            # 删除chunk原文向量集合中对应文档的数据
            if self.chunks_collection:
                logger.info(f"开始删除文档ID为{document_id}的chunk原文向量数据")
                self.chunks_collection.delete(expr)
                logger.info("chunk原文向量数据删除成功")
            
            return True
        except Exception as e:
            logger.error(f"删除Milvus数据失败: {e}")
            return False
