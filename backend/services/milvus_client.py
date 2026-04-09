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
        self.connect()
    
    def connect(self):
        """连接到Milvus"""
        try:
            # 先连接到默认数据库，使用IPv4地址
            connections.connect(
                alias="default",
                host="127.0.0.1",  # 使用127.0.0.1而不是localhost，避免IPv6连接问题
                port=self.port
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
                self.summaries_collection.insert(summaries_entities)
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
        
        # 加载集合
        self.summaries_collection.load()
        self.subquestions_collection.load()
        logger.info("数据导入完成")
        return import_result
    
    def query(self, query_text, limit=5, metadata_filter=None):
        """查询Milvus数据"""
        if not self.summaries_collection or not self.subquestions_collection:
            # 尝试创建集合
            if not self.create_collections():
                logger.error("集合创建失败")
                return []
        
        # 生成查询嵌入
        from langchain_openai import OpenAIEmbeddings
        
        # 使用配置类中的设置
        EMBEDDING_MODEL = settings.EMBEDDING_MODEL
        LITELLM_API_KEY = settings.LITELLM_API_KEY
        LITELLM_BASE_URL = settings.LITELLM_BASE_URL
        
        embedding_model = OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            api_key=LITELLM_API_KEY,
            base_url=LITELLM_BASE_URL,
        )
        
        query_embedding = [embedding_model.embed_query(query_text)]
        
        # 搜索参数
        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 10}
        }
        
        # 构建过滤表达式
        conditions = []
        
        # 优先使用标量字段进行过滤
        if metadata_filter:
            # 处理knowledge_base_id作为标量字段
            if "knowledge_base_id" in metadata_filter:
                knowledge_base_id = metadata_filter.pop("knowledge_base_id")
                conditions.append(f"knowledge_base_id == {knowledge_base_id}")
            
            # 处理其他metadata过滤
            for key, value in metadata_filter.items():
                if isinstance(value, str):
                    conditions.append(f"metadata['{key}'] == '{value}'")
                else:
                    conditions.append(f"metadata['{key}'] == {value}")
        
        expr = " && ".join(conditions) if conditions else None
        
        # 搜索摘要
        summary_results = self.summaries_collection.search(
            data=query_embedding,
            anns_field="summary_vector",
            param=search_params,
            limit=limit,
            expr=expr,
            output_fields=["chunk_id", "chunk_text", "summary_text", "created_at", "metadata"]
        )
        
        # 搜索子问题
        subquestion_results = self.subquestions_collection.search(
            data=query_embedding,
            anns_field="question_vector",
            param=search_params,
            limit=limit,
            expr=expr,
            output_fields=["chunk_id", "chunk_text", "question_text", "created_at", "metadata"]
        )
        
        # 处理结果
        results = []
        
        # 处理摘要结果
        for hits in summary_results:
            for hit in hits:
                results.append({
                    "type": "summary",
                    "chunk_id": hit.entity.get("chunk_id"),
                    "chunk_text": hit.entity.get("chunk_text"),
                    "content": hit.entity.get("summary_text"),
                    "distance": hit.distance,
                    "created_at": hit.entity.get("created_at"),
                    "metadata": hit.entity.get("metadata")
                })
        
        # 处理子问题结果
        for hits in subquestion_results:
            for hit in hits:
                results.append({
                    "type": "subquestion",
                    "chunk_id": hit.entity.get("chunk_id"),
                    "chunk_text": hit.entity.get("chunk_text"),
                    "content": hit.entity.get("question_text"),
                    "distance": hit.distance,
                    "created_at": hit.entity.get("created_at"),
                    "metadata": hit.entity.get("metadata")
                })
        
        # 按距离排序
        results.sort(key=lambda x: x["distance"], reverse=True)
        
        return results[:limit]
    
    def get_collection_info(self):
        """获取集合信息"""
        try:
            collections = self.get_collections()
            info = {}
            
            for collection_name in collections:
                if collection_name in [settings.MILVUS_SUMMARIES_COLLECTION, settings.MILVUS_SUBQUESTIONS_COLLECTION]:
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
            
            return True
        except Exception as e:
            logger.error(f"删除Milvus数据失败: {e}")
            return False
