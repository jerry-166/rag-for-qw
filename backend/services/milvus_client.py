from typing import Optional
import time

from config import settings, init_logger, get_runtime

# 初始化日志记录器
logger = init_logger(__name__)


def _pymilvus():
    """圈6：pymilvus（含 grpc/pandas，实测 import ~1.7s）延迟到首次真正使用时加载，不阻塞启动。"""
    from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, list_collections
    return connections, Collection, FieldSchema, CollectionSchema, DataType, list_collections


class MilvusClient:
    def __init__(self, host=None, port=None, db_name=None):
        host = host or get_runtime("MILVUS_HOST", settings.MILVUS_HOST)
        port = port or get_runtime("MILVUS_PORT", settings.MILVUS_PORT)
        db_name = db_name or get_runtime("MILVUS_DB_NAME", settings.MILVUS_DB_NAME)
        self.host = host
        self.port = port
        self.db_name = db_name
        self.summaries_collection = None
        self.subquestions_collection = None
        self.chunks_collection = None  # [新增] chunk原文向量集合（Native检索）
        # 01-B：连接从构造剥离，移入 app 启动后台预热（不阻塞 HTTP 服务）。
        # query() 入口已有 create_collections() 的断连重连兜底，懒连接安全。
    
    def connect(self):
        """连接到 Milvus 或 Zilliz Cloud（云托管）。

        连接优先级（实现"配置页优先 → 失败 fallback 本地"）：
          1. MILVUS_URI 非空 → 先尝试 Zilliz Cloud（uri + token）
          2. Zilliz Cloud 失败 → 自动 fallback 到本地 Milvus（host + port）
          3. 本地也失败 → 返回 False

        运行时配置：set_runtime('MILVUS_URI', ...) 优先于 .env 配置。
        """
        connections = _pymilvus()[0]
        try:
            uri = get_runtime("MILVUS_URI", settings.MILVUS_URI)
            token = get_runtime("MILVUS_TOKEN", settings.MILVUS_TOKEN)

            # 首先检查 URL 和 token，两个都配齐才走 Zilliz Cloud
            # 任一为空 → 直接降级到本地 Milvus（避免无谓的失败尝试）
            if uri and token:
                # ============ Zilliz Cloud 模式（优先）============
                logger.info(f"正在连接 Zilliz Cloud: {uri}")
                try:
                    connections.connect(
                        alias="default",
                        uri=uri,
                        token=token,
                        secure=True,
                        timeout=30
                    )
                    # Zilliz Cloud Free 套餐不支持创建自定义数据库，强制用 default
                    from pymilvus import db
                    try:
                        db.using_database(self.db_name)
                        logger.info(f"Zilliz Cloud 连接成功，使用数据库: {self.db_name}")
                    except Exception as db_err:
                        logger.warning(
                            f"切换到数据库 {self.db_name} 失败，"
                            f"fallback 到 default: {db_err}"
                        )
                        self.db_name = "default"
                        db.using_database("default")
                    return True
                except Exception as cloud_err:
                    # Zilliz Cloud 连不上，自动 fallback 到本地 Milvus
                    logger.warning(
                        f"Zilliz Cloud 连接失败，尝试 fallback 到本地 Milvus: {cloud_err}"
                    )
                    # 继续往下走本地模式

            # ============ 本地 Milvus 模式（fallback）============
            host = "127.0.0.1" if str(self.host).lower() in ("localhost", "127.0.0.1") else self.host
            connections.connect(
                alias="default",
                host=host,
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
            logger.info(f"本地 Milvus 连接成功（fallback），使用数据库: {self.db_name}")
            return True
        except Exception as e:
            logger.error(f"Milvus连接失败（Zilliz Cloud 和本地都不可用）: {e}")
            return False

    def close(self):
        """断开 Milvus 连接（运行时重建客户端前调用）。"""
        try:
            from pymilvus import connections
            connections.disconnect("default")
            logger.info("Milvus 连接已断开")
        except Exception as e:
            logger.warning(f"Milvus 断开连接失败: {e}")
    
    def get_collections(self):
        """获取集合列表"""
        try:
            return _pymilvus()[5]()
        except Exception as e:
            logger.error(f"获取集合列表失败: {e}")
            return []
    
    def create_collections(self):
        """创建集合"""
        try:
            _, Collection, FieldSchema, CollectionSchema, DataType, _ = _pymilvus()
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
            summaries_collection = get_runtime("MILVUS_SUMMARIES_COLLECTION", settings.MILVUS_SUMMARIES_COLLECTION)
            if summaries_collection not in collections:
                summaries_fields = [
                    FieldSchema(name="chunk_id", dtype=DataType.INT64, is_primary=True, auto_id=True),  # 使用Milvus自动ID
                    FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="summary_text", dtype=DataType.VARCHAR, max_length=2000),
                    FieldSchema(name="summary_vector", dtype=DataType.FLOAT_VECTOR, dim=get_runtime("EMBEDDING_DIM", settings.EMBEDDING_DIM)),
                    FieldSchema(name="created_at", dtype=DataType.INT64),
                    FieldSchema(name="knowledge_base_id", dtype=DataType.INT64),  # 添加knowledge_base_id字段
                    FieldSchema(name="document_id", dtype=DataType.INT64),  # 添加document_id字段
                    FieldSchema(name="metadata", dtype=DataType.JSON)  # 添加metadata字段
                ]
                summaries_schema = CollectionSchema(fields=summaries_fields, description="文档摘要集合")
                self.summaries_collection = Collection(name=summaries_collection, schema=summaries_schema)
                
                # 创建摘要向量索引
                summaries_index_params = {
                    "index_type": "AUTOINDEX",
                    "metric_type": get_runtime("MILVUS_METRIC_TYPE", settings.MILVUS_METRIC_TYPE)
                }
                self.summaries_collection.create_index(field_name="summary_vector", index_params=summaries_index_params)
                logger.info("摘要集合创建成功")
            else:
                # 集合已存在，直接获取
                self.summaries_collection = Collection(name=summaries_collection)
                logger.info("摘要集合已存在，直接使用")
            
            # 创建子问题集合
            subquestions_collection = get_runtime("MILVUS_SUBQUESTIONS_COLLECTION", settings.MILVUS_SUBQUESTIONS_COLLECTION)
            if subquestions_collection not in collections:
                subquestions_fields = [
                    FieldSchema(name="subquestion_id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="chunk_id", dtype=DataType.INT64),
                    FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="question_text", dtype=DataType.VARCHAR, max_length=500),
                    FieldSchema(name="question_vector", dtype=DataType.FLOAT_VECTOR, dim=get_runtime("EMBEDDING_DIM", settings.EMBEDDING_DIM)),
                    FieldSchema(name="created_at", dtype=DataType.INT64),
                    FieldSchema(name="knowledge_base_id", dtype=DataType.INT64),  # 添加knowledge_base_id字段
                    FieldSchema(name="document_id", dtype=DataType.INT64),  # 添加document_id字段
                    FieldSchema(name="metadata", dtype=DataType.JSON)  # 添加metadata字段
                ]
                subquestions_schema = CollectionSchema(fields=subquestions_fields, description="文档子问题集合")
                self.subquestions_collection = Collection(name=subquestions_collection, schema=subquestions_schema)
                
                # 创建子问题向量索引
                subquestions_index_params = {
                    "index_type": "AUTOINDEX",
                    "metric_type": get_runtime("MILVUS_METRIC_TYPE", settings.MILVUS_METRIC_TYPE)
                }
                self.subquestions_collection.create_index(field_name="question_vector",
                                                          index_params=subquestions_index_params)
                logger.info("子问题集合创建成功")
            else:
                # 集合已存在，直接获取
                self.subquestions_collection = Collection(name=subquestions_collection)
                logger.info("子问题集合已存在，直接使用")
            
            # ── 新增：chunk原文向量集合（Native检索）──
            chunks_collection = get_runtime("MILVUS_CHUNKS_COLLECTION", settings.MILVUS_CHUNKS_COLLECTION)
            logger.info(f"开始处理chunk原文向量集合: {chunks_collection}")
            if chunks_collection not in collections:
                logger.info("chunk原文向量集合不存在，开始创建...")
                chunks_fields = [
                    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="pg_chunk_id", dtype=DataType.INT64),
                    FieldSchema(name="document_id", dtype=DataType.INT64),
                    FieldSchema(name="knowledge_base_id", dtype=DataType.INT64),
                    FieldSchema(name="chunk_index", dtype=DataType.INT64),
                    FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="chunk_vector", dtype=DataType.FLOAT_VECTOR, dim=get_runtime("EMBEDDING_DIM", settings.EMBEDDING_DIM)),
                    FieldSchema(name="created_at", dtype=DataType.INT64),
                    FieldSchema(name="metadata", dtype=DataType.JSON),
                ]
                chunks_schema = CollectionSchema(fields=chunks_fields, description="chunk原文向量集合，用于Native检索")
                logger.info("创建chunk原文向量集合对象...")
                self.chunks_collection = Collection(name=chunks_collection, schema=chunks_schema)
                logger.info("创建chunk原文向量索引...")
                # 使用 IVF_FLAT 索引，创建速度更快
                self.chunks_collection.create_index(
                    field_name="chunk_vector",
                    index_params={"index_type": "IVF_FLAT", "metric_type": get_runtime("MILVUS_METRIC_TYPE", settings.MILVUS_METRIC_TYPE), "params": {"nlist": get_runtime("MILVUS_NLIST", settings.MILVUS_NLIST)}}
                )
                logger.info("chunk原文向量集合创建成功")
            else:
                logger.info("chunk原文向量集合已存在，直接获取...")
                self.chunks_collection = Collection(name=chunks_collection)
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
        查询Milvus数据，通过策略模式支持可扩展的检索模式。

        内置模式: native / advanced / hybrid
        新增模式只需在 retrieval_strategies.py 添加策略类，本方法无需改动。
        """
        if not self.summaries_collection or not self.subquestions_collection:
            if not self.create_collections():
                logger.error("集合创建失败")
                return []

        # 生成查询嵌入
        from langchain_openai import OpenAIEmbeddings
        embedding_model = OpenAIEmbeddings(
            model=get_runtime("EMBEDDING_MODEL", settings.EMBEDDING_MODEL),
            api_key=get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY),
            base_url=get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL),
        )
        query_embedding = [embedding_model.embed_query(query_text)]

        search_params = {"metric_type": get_runtime("MILVUS_METRIC_TYPE", settings.MILVUS_METRIC_TYPE), "params": {"nprobe": get_runtime("MILVUS_NPROBE", settings.MILVUS_NPROBE)}}

        # 构建过滤表达式
        conditions = []
        filter_copy = dict(metadata_filter) if metadata_filter else {}
        if "knowledge_base_id" in filter_copy:
            knowledge_base_id = filter_copy.pop("knowledge_base_id")
            conditions.append(f"knowledge_base_id == {knowledge_base_id}")
        for key, value in filter_copy.items():
            if isinstance(value, str):
                conditions.append(f"metadata['{key}'] == '{value}'")
            else:
                conditions.append(f"metadata['{key}'] == {value}")
        expr = " && ".join(conditions) if conditions else None

        # ── 构建上下文 + 策略调度 ───────────────────────────────────────

        from services.retrieval_strategies import get_strategy, SearchContext

        ctx = SearchContext(
            query_embedding=query_embedding,
            search_params=search_params,
            limit=limit,
            expr=expr,
            summaries_collection=self.summaries_collection,
            subquestions_collection=self.subquestions_collection,
            chunks_collection=self.chunks_collection,
        )

        logger.info(f"[MilvusClient] 开始检索, retrieval_mode={retrieval_mode}, limit={limit}, query_len={len(query_text)}")

        try:
            strategy = get_strategy(retrieval_mode, ctx)
        except ValueError:
            logger.warning(f"[MilvusClient] 未知检索模式 '{retrieval_mode}'，fallback 到 advanced")
            strategy = get_strategy("advanced", ctx)

        results = strategy.execute(limit)
        logger.info(f"[MilvusClient] {retrieval_mode} 模式检索完成，返回 {len(results)} 条结果")
        return results
    
    def get_collection_info(self):
        """获取集合信息"""
        try:
            collections = self.get_collections()
            info = {}
            
            for collection_name in collections:
                if collection_name in [
                    get_runtime("MILVUS_SUMMARIES_COLLECTION", settings.MILVUS_SUMMARIES_COLLECTION),
                    get_runtime("MILVUS_SUBQUESTIONS_COLLECTION", settings.MILVUS_SUBQUESTIONS_COLLECTION),
                    get_runtime("MILVUS_CHUNKS_COLLECTION", settings.MILVUS_CHUNKS_COLLECTION),
                ]:
                    collection = _pymilvus()[1](collection_name)
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
            _pymilvus()[0].disconnect("default")
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
