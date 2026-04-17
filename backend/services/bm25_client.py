"""
纯内存 BM25 检索客户端 — 替代 Elasticsearch 的轻量方案

特点:
  - 零外部依赖（仅 rank_bm25 + jieba），不占用额外端口和内存
  - 与 ElasticsearchClient 保持相同接口，上层代码无需改动
  - 支持按 user_id / knowledge_base_id 过滤
  - 增量索引：index_chunk / bulk_index_chunks 动态加入，无需全量重建
  - 中文分词：使用 jieba（与 ES 的 IK 分词效果接近）

配置:
  SEARCH_BACKEND=bm25 时自动启用
"""

import math
import re
import logging
from typing import List, Dict, Optional, Any
from collections import defaultdict

from config import settings, init_logger

logger = init_logger(__name__)

# 延迟导入 rank_bm25 和 jieba（避免未安装时报错）
_rank_bm25 = None
_jieba = None


def _get_bm25():
    """懒加载 rank_bm25.BM25Okapi"""
    global _rank_bm25
    if _rank_bm25 is None:
        try:
            from rank_bm25 import BM25Okapi
            _rank_bm25 = BM25Okapi
            logger.info("rank_bm25 加载成功")
        except ImportError:
            raise ImportError(
                "需要安装 rank_bm25:  pip install rank_bm25 jieba\n"
                "或设置 SEARCH_BACKEND=elasticsearch 使用 Elasticsearch"
            )
    return _rank_bm25


def _get_jieba():
    """懒加载 jieba"""
    global _jieba
    if _jieba is None:
        try:
            import jieba
            # 加载常用词库，提升分词质量
            jieba.initialize()
            _jieba = jieba
            logger.info("jieba 分词器加载成功")
        except ImportError:
            raise ImportError(
                "需要安装 jieba 用于中文分词:  pip install jieba"
            )
    return _jieba


class BM25Client:
    """
    纯内存 BM25 检索引擎。

    内部按 (user_id, knowledge_base_id) 维度分桶存储文档，
    每个桶独立维护一个 BM25 模型。新增文档后该桶的模型会在下次搜索时自动重建。
    """

    def __init__(self):
        # 核心存储：按 (user_id, kb_id) 分桶
        # bucket_key -> { doc_id: doc_dict }
        self._corpus: Dict[str, Dict[int, dict]] = defaultdict(dict)

        # 缓存的 BM25 模型：bucket_key -> (tokenized_corpus, bm25_model, doc_id_list)
        # doc_id_list 保证返回顺序与 corpus 对应
        self._models: Dict[str, tuple] = {}

        # 是否已初始化（标记是否从 PG 加载过数据）
        self._initialized = False

        logger.info("BM25 内存检索引擎已创建（尚未加载索引）")

    # ================================================================
    # 公开接口（与 ElasticsearchClient 一致）
    # ================================================================

    def connect(self) -> bool:
        """兼容接口 — BM25 无需连接，始终返回 True"""
        return True

    def create_index(self) -> bool:
        """兼容接口 — BM25 无需预建索引"""
        return True

    def index_chunk(
        self,
        chunk_id: int,
        user_id: int,
        document_id: int,
        knowledge_base_id: int,
        chunk_index: int,
        content: str,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        索引单个 chunk 到内存。

        Returns:
            bool: 是否成功
        """
        try:
            key = self._bucket_key(user_id, knowledge_base_id)
            self._corpus[key][chunk_id] = {
                "id": chunk_id,
                "user_id": user_id,
                "knowledge_base_id": knowledge_base_id,
                "document_id": document_id,
                "chunk_index": chunk_index,
                "content": content,
                "metadata": metadata or {},
            }
            # 标记该桶模型过期
            self._invalidate_model(key)
            return True
        except Exception as e:
            logger.error(f"BM25 索引 chunk 失败: {e}")
            return False

    def bulk_index_chunks(self, chunks: List[dict]) -> bool:
        """
        批量索引 chunks。

        Args:
            chunks: 列表，每项需包含 id, user_id, document_id, chunk_index,
                    content, knowledge_base_id(可选), metadata(可选)

        Returns:
            bool: 是否全部成功
        """
        try:
            affected_buckets = set()
            for chunk in chunks:
                key = self._bucket_key(
                    chunk.get("user_id", 0),
                    chunk.get("knowledge_base_id", 0),
                )
                self._corpus[key][chunk["id"]] = {
                    "id": chunk["id"],
                    "user_id": chunk["user_id"],
                    "knowledge_base_id": chunk.get("knowledge_base_id", 0),
                    "document_id": chunk["document_id"],
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk.get("content", ""),
                    "metadata": chunk.get("metadata", {}),
                }
                affected_buckets.add(key)

            for key in affected_buckets:
                self._invalidate_model(key)

            logger.info(f"BM25 批量索引完成，共 {len(chunks)} 条")
            return True
        except Exception as e:
            logger.error(f"BM25 批量索引失败: {e}")
            return False

    def search(
        self,
        query: str,
        user_id: int,
        size: int = 20,
        filters: Optional[dict] = None,
    ) -> List[dict]:
        """
        BM25 关键词搜索。

        Args:
            query: 搜索查询文本
            user_id: 用户 ID（必须匹配）
            size: 返回条数上限
            filters: 过滤条件，支持 knowledge_base_id 等

        Returns:
            结果列表，每项包含 id/score/content/document_id/chunk_index
        """
        if not query.strip():
            return []

        try:
            kb_id = filters.get("knowledge_base_id") if filters else None
            key = self._bucket_key(user_id, kb_id or 0)

            # 如果指定了 kb_id 但该桶为空，尝试从所有该用户的桶中搜索
            corpus_bucket = dict(self._corpus[key])
            if not corpus_bucket and kb_id is None:
                # 聚合该用户所有知识库的数据
                corpus_bucket = {}
                for k, docs in self._corpus.items():
                    parsed_user, _ = k.split(":", 1)
                    if str(parsed_user) == str(user_id):
                        corpus_bucket.update(docs)

            if not corpus_bucket:
                return []

            # 获取或构建 BM25 模型
            bm25, doc_ids = self._get_or_build_model(key, corpus_bucket)
            if bm25 is None:
                return []

            # 对查询分词并打分
            jieba = _get_jieba()
            tokenized_query = list(jieba.cut_for_search(query))
            scores = bm25.get_scores(tokenized_query)

            # 按 BM25 分数降序排列，取 top size
            scored = sorted(
                zip(doc_ids, scores),
                key=lambda x: x[1],
                reverse=True,
            )

            results = []
            for doc_id, score in scored[:size]:
                if score <= 0:
                    continue  # BM25 分数为 0 表示完全不相关，跳过
                doc = corpus_bucket.get(doc_id)
                if doc:
                    results.append({
                        "id": doc["id"],
                        "score": float(score),
                        "content": doc["content"],
                        "document_id": doc["document_id"],
                        "chunk_index": doc["chunk_index"],
                    })

            logger.debug(
                f"BM25 搜索完成: query='{query[:30]}', "
                f"user={user_id}, kb={kb_id}, 返回{len(results)}条"
            )
            return results

        except Exception as e:
            logger.error(f"BM25 搜索失败: {e}")
            return []

    def delete_chunk(self, chunk_id: int, user_id: int) -> bool:
        """删除单个 chunk 索引。需要在所有桶中查找。"""
        try:
            for key in list(self._corpus.keys()):
                parsed_user, _ = key.split(":", 1)
                if str(parsed_user) == str(user_id) and chunk_id in self._corpus[key]:
                    del self._corpus[key][chunk_id]
                    self._invalidate_model(key)
                    return True
            return False
        except Exception as e:
            logger.error(f"BM25 删除 chunk 失败: {e}")
            return False

    def delete_document_chunks(
        self, document_id: int, user_id: int
    ) -> bool:
        """删除某文档的所有 chunk 索引。"""
        try:
            deleted = 0
            for key in list(self._corpus.keys()):
                parsed_user, _ = key.split(":", 1)
                if str(parsed_user) != str(user_id):
                    continue
                to_remove = [
                    cid
                    for cid, doc in self._corpus[key].items()
                    if doc.get("document_id") == document_id
                ]
                for cid in to_remove:
                    del self._corpus[key][cid]
                    deleted += 1
                if to_remove:
                    self._invalidate_model(key)

            logger.info(f"BM25 删除文档 {document_id} 的 {deleted} 条 chunk 索引")
            return deleted > 0
        except Exception as e:
            logger.error(f"BM25 删除文档 chunks 失败: {e}")
            return False

    # ================================================================
    # 从 PG 全量加载索引（可选，启动时调用）
    # ================================================================

    def load_from_database(self) -> int:
        """
        从 PostgreSQL 全量加载所有 document_chunk 到内存索引。
        在应用启动时调用一次即可，之后增量更新由 index_chunk/bulk 负责。

        Returns:
            int: 加载的 chunk 总数
        """
        try:
            from services.database import db
            rows = db.fetchall("SELECT * FROM document_chunk")

            count = 0
            for row in rows:
                key = self._bucket_key(
                    row.get("user_id", 0), row.get("knowledge_base_id", 0)
                )
                content = row.get("chunk_text") or row.get("content") or ""
                self._corpus[key][row["id"]] = {
                    "id": row["id"],
                    "user_id": row.get("user_id", 0),
                    "knowledge_base_id": row.get("knowledge_base_id", 0),
                    "document_id": row.get("document_id"),
                    "chunk_index": row.get("chunk_index", 0),
                    "content": content,
                    "metadata": {},
                }
                count += 1

            self._initialized = True
            # 清空所有模型缓存（下次搜索时按需构建）
            self._models.clear()

            logger.info(f"BM25 索引从 PG 加载完成，共 {count} 条 chunk，{len(self._corpus)} 个分桶")
            return count

        except Exception as e:
            logger.error(f"BM25 从 PG 加载索引失败: {e}")
            return 0

    # ================================================================
    # 内部方法
    # ================================================================

    @staticmethod
    def _bucket_key(user_id, knowledge_base_id) -> str:
        """生成分桶键"""
        return f"{user_id}:{knowledge_base_id or '_all'}"

    def _invalidate_model(self, bucket_key: str):
        """使某个桶的 BM25 模型缓存失效"""
        self._models.pop(bucket_key, None)

    def _get_or_build_model(
        self, bucket_key: str, corpus: Dict[int, dict]
    ):
        """
        获取或构建指定桶的 BM25 模型。

        Returns:
            (bm25_instance, doc_id_list) 或 (None, []) 当无数据时
        """
        # 检查缓存是否有效
        cached = self._models.get(bucket_key)
        if cached is not None:
            return cached

        if not corpus:
            self._models[bucket_key] = (None, [])
            return None, []

        jieba = _get_jieba()
        BM25Okapi = _get_bm25()

        # 按 id 排序保证稳定顺序（虽然 BM25 本身对顺序不敏感，
        # 但我们需要 doc_id_list 与 scores 一一对应）
        sorted_ids = sorted(corpus.keys())
        tokenized_docs = [
            list(jieba.cut_for_search(corpus[doc_id]["content"]))
            for doc_id in sorted_ids
        ]

        bm25 = BM25Okapi(tokenized_docs)
        result = (bm25, sorted_ids)
        self._models[bucket_key] = result

        logger.debug(f"BM25 模型构建完成: bucket={bucket_key}, 文档数={len(sorted_ids)}")
        return result


# ================================================================
# 工厂函数 — 根据 SEARCH_BACKEND 配置返回对应实例
# ================================================================

_backend_type: Optional[str] = None
_client_instance = None


def get_search_client():
    """
    获取搜索引擎实例。

    由 app.py 启动时调用一次，之后全局复用。
    通过环境变量 SEARCH_BACKEND 控制：
      - 'bm25'     → BM25Client（纯内存，默认）
      - 'elasticsearch' → ElasticsearchClient
      - 未配置       → 默认使用 bm25
    """
    global _backend_type, _client_instance

    if _client_instance is not None:
        return _client_instance

    backend = getattr(settings, "SEARCH_BACKEND", "bm25").lower().strip()

    if backend == "elasticsearch":
        from .elasticsearch_client import ElasticsearchClient
        _client_instance = ElasticsearchClient()
        _backend_type = "elasticsearch"
        logger.info("搜索引擎: Elasticsearch")
    else:
        _client_instance = BM25Client()
        _backend_type = "bm25"
        logger.info("搜索引擎: BM25 (纯内存)")

    return _client_instance


def get_backend_type() -> str:
    """返回当前搜索引擎类型标识"""
    return _backend_type or "unknown"


# 兼容旧代码的直接引用
# 旧代码用 `from services.elasticsearch_client import es_client`
# 新代码应改用 `from services.bm25_client import get_search_client`
