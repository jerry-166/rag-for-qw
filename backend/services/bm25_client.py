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
from collections import defaultdict, OrderedDict

from config import settings, init_logger, get_runtime

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


# 01-C：jieba 在中英混排间会产出纯空白 token（' '、'\n'、混合空白等）。
# TEXT 空格连接/还原对纯空白 token 有损；且不同空白串在旧实现中是不同 token（各有 idf），
# 简单过滤或合并为单一哨兵都会改变 BM25 统计导致打分偏差。
# 解决：可逆编码 ws → '␣' + 码点 hex（无空格、语料不出现），语料与查询两侧同样编码，
# 读取缓存后解码还原 → 与旧实现的 BM25 打分严格等价。
_WS_PREFIX = '␣'


def _encode_tokens(tokens):
    """空白 token → '␣'+码点hex（可逆，保持 BM25 统计严格等价）"""
    out = []
    for t in tokens:
        if t.strip():
            out.append(t)
        else:
            out.append(_WS_PREFIX + '.'.join(f'{ord(c):X}' for c in t))
    return out


def _decode_tokens(tokens):
    """还原 _encode_tokens 的编码（'␣20' → ' '）"""
    out = []
    for t in tokens:
        if t.startswith(_WS_PREFIX) and len(t) > len(_WS_PREFIX):
            try:
                out.append(''.join(chr(int(h, 16)) for h in t[len(_WS_PREFIX):].split('.')))
                continue
            except ValueError:
                pass
        out.append(t)
    return out


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
        # 01 §7.1：LRU 化（双上限：桶数 / 总 chunk 数）
        self._models: "OrderedDict[str, tuple]" = OrderedDict()
        # 各桶缓存的 chunk 数（用于总 chunk 上限统计）
        self._model_sizes: Dict[str, int] = {}
        # 超过单桶上限的桶不缓存（每次现算），记 warn
        self._oversized: set = set()

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

            # 对查询分词并打分（与缓存编码一致：空白 token → 哨兵，保持打分等价）
            jieba = _get_jieba()
            tokenized_query = _encode_tokens(jieba.cut_for_search(query))
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
            self._model_sizes.clear()
            self._oversized.clear()

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
        self._model_sizes.pop(bucket_key, None)
        self._oversized.discard(bucket_key)

    # ------------------------------------------------------------------
    # 01 §7.1：LRU 容量管理
    # ------------------------------------------------------------------
    def _evict_to_limits(self, incoming_key: str, incoming_size: int):
        """插入新桶后执行 LRU 逐出，直到满足双上限。

        - 桶数上限：BM25_CACHE_BUCKETS
        - 总 chunk 上限：BM25_CACHE_MAX_CHUNKS
        逐出顺序 = 最久未使用（OrderedDict 头部）；incoming 桶不参与本次逐出。
        """
        from services.audit import audit

        max_buckets = int(get_runtime("BM25_CACHE_BUCKETS", 16))
        max_chunks = int(get_runtime("BM25_CACHE_MAX_CHUNKS", 100000))

        total_chunks = incoming_size + sum(
            s for k, s in self._model_sizes.items() if k != incoming_key
        )

        evicted = []
        while len(self._models) > max_buckets or (
            max_chunks > 0 and total_chunks > max_chunks and len(self._models) > 1
        ):
            victim = next(iter(self._models))
            if victim == incoming_key:  # 只剩新桶，不再逐出
                break
            v_size = self._model_sizes.pop(victim, 0)
            self._models.pop(victim, None)
            total_chunks -= v_size
            evicted.append((victim, v_size))

        if evicted:
            for victim, v_size in evicted:
                logger.info(
                    f"BM25 LRU 逐出: bucket={victim}, chunks={v_size}"
                )
            audit.log(
                "bm25.cache.lru_evict",
                resource_type="bm25_bucket",
                detail={
                    "evicted": [{"bucket": k, "chunks": s} for k, s in evicted],
                    "remaining_buckets": len(self._models),
                    "total_cached_chunks": total_chunks,
                    "max_buckets": max_buckets,
                    "max_chunks": max_chunks,
                },
            )

    def _model_memory_hint(self, bucket_key: str, tokenized_docs) -> int:
        """粗略估算单桶 token 总数（内存观测用，常数开销不精确估算）。"""
        return sum(len(tokens) for tokens in tokenized_docs)

    def _get_tokenized_batch(self, corpus: Dict[int, dict]) -> Dict[int, list]:
        """01-C：批量获取分词结果（优先 PG 缓存，未命中的批量 jieba 按需分词并回写）。

        保证与直接 jieba.cut_for_search(content) 结果一致，仅缓存来源不同。
        """
        import time as _time
        from services.audit import audit
        from services.database import db

        t0 = _time.perf_counter()
        # 注意：缓存读回保持编码形态（不解码）——BM25 对 token 双射重命名不变，
        # 语料与查询两侧统一使用编码 token 即与旧实现打分严格等价。
        cached = db.get_tokenized_by_ids(list(corpus.keys()))
        missing = {cid: c for cid, c in corpus.items() if cid not in cached}

        if missing:
            jieba = _get_jieba()
            new_tokens = {
                cid: _encode_tokens(jieba.cut_for_search(c["content"]))
                for cid, c in missing.items()
            }
            db.set_chunk_tokenized_batch(new_tokens)
            cached.update(new_tokens)

        elapsed_ms = ( _time.perf_counter() - t0) * 1000
        audit.log(
            "bm25.cache.tokenize_batch",
            resource_type="bm25_bucket",
            detail={
                "total": len(corpus),
                "cache_hit": len(corpus) - len(missing),
                "cache_miss": len(missing),
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )
        if missing:
            logger.info(
                f"分词缓存命中 {len(corpus) - len(missing)}/{len(corpus)}，"
                f"按需分词并回写 {len(missing)} 条（{elapsed_ms:.1f}ms）"
            )
        else:
            logger.info(f"分词缓存全命中 {len(corpus)}/{len(corpus)}（{elapsed_ms:.1f}ms）")
        return cached

    def _get_or_build_model(
        self, bucket_key: str, corpus: Dict[int, dict]
    ):
        """
        获取或构建指定桶的 BM25 模型。

        Returns:
            (bm25_instance, doc_id_list) 或 (None, []) 当无数据时
        """
        # 检查缓存是否有效（LRU 命中刷新位置）
        cached = self._models.get(bucket_key)
        if cached is not None:
            self._models.move_to_end(bucket_key)
            return cached

        if not corpus:
            self._models[bucket_key] = (None, [])
            self._model_sizes[bucket_key] = 0
            return None, []

        max_buckets = int(get_runtime("BM25_CACHE_BUCKETS", 16))
        max_chunks = int(get_runtime("BM25_CACHE_MAX_CHUNKS", 100000))

        # 兜底：单桶本身超总上限 → 不缓存，每次现算
        if bucket_key in self._oversized or (
            max_chunks > 0 and len(corpus) > max_chunks
        ):
            if bucket_key not in self._oversized:
                self._oversized.add(bucket_key)
                logger.warning(
                    f"BM25 桶 {bucket_key} chunk 数 {len(corpus)} 超过单桶缓存上限 "
                    f"{max_chunks}，不缓存模型（每次现算；建议拆分知识库）"
                )
                from services.audit import audit
                audit.log(
                    "bm25.cache.oversized_bucket",
                    resource_type="bm25_bucket",
                    detail={"bucket": bucket_key, "chunks": len(corpus),
                            "max_chunks": max_chunks},
                )
            return self._build_model(bucket_key, corpus)

        if max_buckets <= 0:  # 上限为 0 → 禁用缓存
            return self._build_model(bucket_key, corpus)

        result = self._build_model(bucket_key, corpus)
        self._models[bucket_key] = result
        self._model_sizes[bucket_key] = len(corpus)
        self._evict_to_limits(bucket_key, len(corpus))
        return result

    def _build_model(self, bucket_key: str, corpus: Dict[int, dict]):
        """构建（不缓存）指定桶的 BM25 模型。"""
        BM25Okapi = _get_bm25()

        # 按 id 排序保证稳定顺序（虽然 BM25 本身对顺序不敏感，
        # 但我们需要 doc_id_list 与 scores 一一对应）
        sorted_ids = sorted(corpus.keys())
        # 01-C：分词走 PG 缓存 + 批量按需分词（替代逐条 jieba 全量分词）
        tokenized_map = self._get_tokenized_batch(corpus)
        tokenized_docs = [tokenized_map.get(doc_id, []) for doc_id in sorted_ids]

        bm25 = BM25Okapi(tokenized_docs)
        result = (bm25, sorted_ids)

        token_total = self._model_memory_hint(bucket_key, tokenized_docs)
        logger.info(
            f"BM25 模型构建完成: bucket={bucket_key}, 文档数={len(sorted_ids)}, "
            f"token总数={token_total}"
        )
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

    backend = get_runtime("SEARCH_BACKEND", "bm25").lower().strip()

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


def reset_search_client():
    """重置搜索引擎单例，下次调用按最新配置重建（运行时热切换用）。"""
    global _backend_type, _client_instance
    _client_instance = None
    _backend_type = None
    from services.elasticsearch_client import reset_es_client
    reset_es_client()
    logger.info("搜索引擎单例已重置，等待按最新配置重建")


def get_backend_type() -> str:
    """返回当前搜索引擎类型标识"""
    return _backend_type or "unknown"


# 兼容旧代码的直接引用
# 旧代码用 `from services.elasticsearch_client import es_client`
# 新代码应改用 `from services.bm25_client import get_search_client`
