from elasticsearch import Elasticsearch
from config import settings, init_logger
from datetime import datetime

# 初始化日志记录器
logger = init_logger(__name__)

class ElasticsearchClient:
    def __init__(self):
        self.es = None
        self.connect()
        self.create_index()
    
    def connect(self):
        """连接到Elasticsearch"""
        try:
            # 使用现代的Elasticsearch客户端连接方式
            self.es = Elasticsearch(
                f"http://{settings.ELASTICSEARCH_HOST}:{settings.ELASTICSEARCH_PORT}",
                basic_auth=(
                    settings.ELASTICSEARCH_USER,
                    settings.ELASTICSEARCH_PASSWORD
                ),
                verify_certs=False
            )
            if self.es.ping():
                logger.info("Elasticsearch连接成功")
                return True
            else:
                logger.warning("Elasticsearch连接失败")
                return False
        except Exception as e:
            logger.error(f"Elasticsearch连接异常: {e}")
            return False
    
    def create_index(self):
        """创建chunk_keyword索引"""
        index_name = "chunk_keyword"
        try:
            if not self.es:
                logger.error("Elasticsearch客户端未初始化")
                return False
                
            if not self.es.indices.exists(index=index_name):
                mapping = {
                    "settings": {
                        "number_of_shards": 3,
                        "number_of_replicas": 1,
                        "analysis": {
                            "analyzer": {
                                "ik_max_word_analyzer": {
                                    "type": "custom",
                                    "tokenizer": "ik_max_word"
                                },
                                "ik_smart_analyzer": {
                                    "type": "custom",
                                    "tokenizer": "ik_smart"
                                }
                            }
                        }
                    },
                    "mappings": {
                        "properties": {
                            "id": { "type": "long" },
                            "user_id": { "type": "keyword" },
                            "knowledge_base_id": { "type": "long" },
                            "document_id": { "type": "long" },
                            "chunk_index": { "type": "integer" },
                            "content": {
                                "type": "text",
                                "analyzer": "ik_max_word",
                                "search_analyzer": "ik_smart",
                                "fields": {
                                    "raw": { "type": "keyword" }
                                }
                            },
                            "metadata": {
                                "type": "object",
                                "dynamic": True
                            },
                            "created_at": { "type": "date" }
                        }
                    }
                }
                self.es.indices.create(index=index_name, body=mapping)
                logger.info(f"创建索引 {index_name} 成功")
            else:
                logger.info(f"索引 {index_name} 已存在")
            return True
        except Exception as e:
            logger.error(f"创建索引失败: {e}")
            return False
    
    def index_chunk(self, chunk_id, user_id, document_id, knowledge_base_id, chunk_index, content, metadata=None):
        """索引文档块"""
        try:
            doc = {
                "id": chunk_id,
                "user_id": user_id,
                "knowledge_base_id": knowledge_base_id,
                "document_id": document_id,
                "chunk_index": chunk_index,
                "content": content,
                "metadata": metadata or {},
                "created_at": datetime.now().isoformat()
            }
            response = self.es.index(
                index="chunk_keyword",
                id=chunk_id,
                body=doc,
                routing=user_id
            )
            return response['result'] == 'created' or response['result'] == 'updated'
        except Exception as e:
            logger.error(f"索引文档块失败: {e}")
            return False
    
    def bulk_index_chunks(self, chunks):
        """批量索引文档块"""
        try:
            actions = []
            for chunk in chunks:
                action = {
                    "index": {
                        "_index": "chunk_keyword",
                        "_id": chunk['id'],
                        "routing": chunk['user_id']
                    }
                }
                doc = {
                    "id": chunk['id'],
                    "user_id": chunk['user_id'],
                    "knowledge_base_id": chunk.get('knowledge_base_id', 0),
                    "document_id": chunk['document_id'],
                    "chunk_index": chunk['chunk_index'],
                    "content": chunk['content'],
                    "metadata": chunk.get('metadata', {}),
                    "created_at": datetime.now().isoformat()
                }
                actions.append(action)
                actions.append(doc)
            if actions:
                response = self.es.bulk(body=actions)
                if response['errors']:
                    logger.error(f"批量索引失败: {response['items']}")
                    return False
                return True
            return True
        except Exception as e:
            logger.error(f"批量索引失败: {e}")
            return False
    
    def search(self, query, user_id, size=20, filters=None):
        """关键词搜索"""
        try:
            search_body = {
                "query": {
                    "bool": {
                        "must": [
                            { "match": { "content": query } }
                        ],
                        "filter": [
                            { "term": { "user_id": user_id } }
                        ]
                    }
                },
                "sort": [ { "_score": "desc" } ],
                "size": size
            }
            if filters:
                for key, value in filters.items():
                    if key == "knowledge_base_id":
                        search_body['query']['bool']['filter'].append(
                            { "term": { "knowledge_base_id": value } }
                        )
                    else:
                        search_body['query']['bool']['filter'].append(
                            { "term": { f"metadata.{key}": value } }
                        )
            response = self.es.search(index="chunk_keyword", body=search_body)
            results = []
            for hit in response['hits']['hits']:
                results.append({
                    'id': hit['_source']['id'],
                    'score': hit['_score'],
                    'content': hit['_source']['content'],
                    'document_id': hit['_source']['document_id'],
                    'chunk_index': hit['_source']['chunk_index']
                })
            return results
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []
    
    def delete_chunk(self, chunk_id, user_id):
        """删除文档块索引"""
        try:
            response = self.es.delete(
                index="chunk_keyword",
                id=chunk_id,
                routing=user_id
            )
            return response['result'] == 'deleted'
        except Exception as e:
            logger.error(f"删除文档块索引失败: {e}")
            return False
    
    def delete_document_chunks(self, document_id, user_id):
        """删除文档的所有块索引"""
        try:
            query = {
                "query": {
                    "bool": {
                        "filter": [
                            { "term": { "user_id": user_id } },
                            { "term": { "document_id": document_id } }
                        ]
                    }
                }
            }
            response = self.es.delete_by_query(
                index="chunk_keyword",
                body=query
            )
            return response['deleted'] > 0
        except Exception as e:
            logger.error(f"删除文档块索引失败: {e}")
            return False

# 全局Elasticsearch客户端实例
es_client = ElasticsearchClient()