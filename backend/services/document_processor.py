import os
import asyncio
import time
import logging
from pydantic import BaseModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from config import settings, init_logger, get_runtime
from services.audit import audit

# 初始化日志记录器
logger = init_logger(__name__)

# 兼容导入（已迁移至 services/enhancers/，文档 03）
from services.enhancers.base import SubqAndSummary, strip_markdown_json as _strip_markdown_json  # noqa: F401

class StoredData(BaseModel):
    id: str
    chunk: str
    sub_questions: list[str]
    subq_embeddings: list[list[float]]
    summary: str
    summary_embedding: list[float]
    chunk_embedding: list[float] = []  # [新增] chunk原文向量，用于Native检索
    metadata: dict

class DocumentProcessor:
    def __init__(self):
        # 配置模型
        self.LITELLM_BASE_URL = get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL)
        self.LITELLM_API_KEY = get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY)
        if not self.LITELLM_API_KEY:
            raise ValueError("LITELLM_API_KEY 环境变量未设置")
        
        self.EMBEDDING_MODEL = get_runtime("EMBEDDING_MODEL", settings.EMBEDDING_MODEL)
        self.DEFAULT_MODEL = get_runtime("DEFAULT_MODEL", settings.DEFAULT_MODEL)
        
        # 初始化模型
        self.ChatModel = ChatOpenAI(
            model_name=self.DEFAULT_MODEL,
            api_key=self.LITELLM_API_KEY,
            base_url=self.LITELLM_BASE_URL,
            max_retries=get_runtime("LLM_MAX_RETRIES", settings.LLM_MAX_RETRIES),
            timeout=get_runtime("LLM_TIMEOUT", settings.LLM_TIMEOUT),
        )
        
        self.EmbeddingModel = OpenAIEmbeddings(
            model=self.EMBEDDING_MODEL,
            api_key=self.LITELLM_API_KEY,
            base_url=self.LITELLM_BASE_URL,
        )

        # 增强器流水线缓存（文档 03）：{frozenset(enabled): EnhancerPipeline}
        # LLM 增强生成（prompt/解析/降级）已委托 services/enhancers/
        self._pipelines = {}

    def _get_pipeline(self, enabled):
        """按启用集获取（或构建）增强器流水线。"""
        from services.enhancers import EnhancerPipeline
        key = frozenset(enabled)
        if key not in self._pipelines:
            self._pipelines[key] = EnhancerPipeline(enabled, self.ChatModel)
        return self._pipelines[key]
    
    def split_document(self, markdown_content, strategy=None):
        """切分文档（文档 02：委托给可插拔切割策略，默认 auto = 原内容探测行为）。"""
        start_time = time.time()
        logger.debug(f"Markdown内容预览：{markdown_content[:100]}...")

        from services.chunking import get_strategy, ChunkParams

        params = ChunkParams(
            chunk_size=get_runtime("CHUNK_SIZE", settings.CHUNK_SIZE),
            chunk_overlap=get_runtime("CHUNK_OVERLAP", settings.CHUNK_OVERLAP),
            min_chunk_size=get_runtime("MIN_CHUNK_SIZE", settings.MIN_CHUNK_SIZE),
            max_chunk_size=get_runtime("MAX_CHUNK_SIZE", settings.MAX_CHUNK_SIZE),
        )
        s = get_strategy(strategy)
        split_documents = s.split(markdown_content, params)

        end_time = time.time()
        logger.info(f"文档切分完成（策略={s.name}），段落数: {len(split_documents)}，耗时: {end_time - start_time:.2f}秒")
        return {
            "chunks": split_documents,
            "strategy": s.name,
        }
    
    async def process_batch(self, chunk, batch_idx, pipeline):
        """
        处理批次（文档 03）：LLM 调用与解析已委托 EnhancerPipeline。

        防御策略（pipeline 内部）：markdown 代码块清理 + OutputFixingParser 修复 + 降级返回空。
        """
        logger.info(f"开始处理批次 {batch_idx}，包含 {len(chunk)} 个文档")
        start_time = time.time()

        results = await pipeline.run_batch(chunk)

        end_time = time.time()
        logger.info(f"批次 {batch_idx} 处理完成，耗时: {end_time - start_time:.2f}秒")
        return {
            "idx": batch_idx,
            "results": results,
        }
    
    async def generate_batches_async_concurrent(
        self,
        datas,
        batch_size=None,
        max_concurrency=None,
        document_id=None,
        knowledge_base_id=None,
        enabled=None,
    ):
        """
        并发生成批次（支持增量模式，文档 03：按启用集装配增强器）。

        enabled（启用集）解析：参数显式传入 > KB 配置 > 全局配置（resolve_enabled_enhancers）。
        - {sub_question, summary} 双开 → 合并 prompt（= 迁移前默认行为）
        - 只开其一 → 独立精简 prompt
        - 全关 → no-op，直接返回（纯原文 RAG）

        增量模式（document_id 不为 None）：
        - 先查 DB，按启用集逐块检查缺失字段
        - 只对缺失的块调用 LLM
        - 每个批次完成后立即写 DB（边生成边持久化）

        全量模式（document_id 为 None）：
        - 直接对所有 datas 调用 LLM，行为同原版
        """
        from services.enhancers import resolve_enabled_enhancers

        if enabled is None:
            enabled = resolve_enabled_enhancers(knowledge_base_id)
        enabled = set(enabled)
        pipeline = self._get_pipeline(enabled)

        batch_size = batch_size or get_runtime("BATCH_SIZE", settings.BATCH_SIZE)
        max_concurrency = max_concurrency or get_runtime("MAX_CONCURRENCY", settings.MAX_CONCURRENCY)
        start_time = time.time()
        docs = [d.chunk for d in datas]
        total = len(docs)

        need_subq = "sub_question" in enabled
        need_summary = "summary" in enabled

        # ==================== 全关：秒回（文档 03 §3.4） ====================
        if not (need_subq or need_summary):
            logger.info(f"增强器已全部关闭（KB={knowledge_base_id}），跳过 {total} 个块的 LLM 生成")
            audit.log("process.generate.done", resource_type="document", resource_id=document_id,
                      kb_id=knowledge_base_id,
                      detail={"total_chunks": total, "enabled_enhancers": sorted(enabled),
                              "duration_ms": 0, "mode": "noop"})
            return

        # ==================== 增量模式 ====================
        if document_id is not None:
            from services.database import db

            # 第 1 步：查询 DB，按启用集找出缺失字段的块（文档 03 §3.4 增量改造）
            miss_indices = []
            for idx, d in enumerate(datas):
                chunk_db_id = d.metadata.get("chunk_id")
                if chunk_db_id is None:
                    # 找不到 chunk_id，跳过（走全量逻辑）
                    miss_indices.append(idx)
                    continue
                # 只检查启用集中的字段；未启用字段视为已满足（不触发补生成）
                subqs = db.get_sub_questions_by_chunk(chunk_db_id) if need_subq else [1]
                summary = db.get_chunk_summary(chunk_db_id) if need_summary else "1"
                if not subqs or not summary:
                    miss_indices.append(idx)

            if not miss_indices:
                logger.info(f"所有 {total} 个块均已生成（启用集: {sorted(enabled)}），跳过 LLM 调用")
                return
            logger.info(f"增量模式：{total} 个块中 {len(miss_indices)} 个需要生成（启用集: {sorted(enabled)}）")

            # 第 2 步：构建 miss 批次，按 batch_size 分组
            miss_chunks = [docs[i] for i in miss_indices]
            miss_datas = [datas[i] for i in miss_indices]
            miss_batches = [miss_chunks[i : i + batch_size] for i in range(0, len(miss_chunks), batch_size)]
            miss_data_batches = [miss_datas[i : i + batch_size] for i in range(0, len(miss_datas), batch_size)]

            sem = asyncio.Semaphore(max_concurrency)

            async def sem_task(chunk, batch_data, batch_idx):
                async with sem:
                    # 内部处理 + 写 DB
                    await self._process_and_persist_batch(
                        chunk, batch_data, batch_idx, document_id, knowledge_base_id, pipeline
                    )

            tasks = [sem_task(cb, mb, idx) for idx, (cb, mb) in enumerate(zip(miss_batches, miss_data_batches))]
            await asyncio.gather(*tasks)
            end_time = time.time()
            audit.log("process.generate.done", resource_type="document", resource_id=document_id,
                      kb_id=knowledge_base_id,
                      detail={"total_chunks": total, "batch_size": batch_size, "enabled_enhancers": sorted(enabled),
                              "max_concurrency": max_concurrency, "duration_ms": round((time.time() - start_time) * 1000, 1),
                              "mode": "incremental"})
            logger.info(f"增量批次处理完成，总耗时: {end_time - start_time:.2f}秒")
            return

        # ==================== 全量模式（原有逻辑） ====================
        batches = [docs[i : i + batch_size] for i in range(0, len(docs), batch_size)]
        sem = asyncio.Semaphore(max_concurrency)

        async def sem_task(chunk, batch_idx):
            async with sem:
                return await self.process_batch(chunk, batch_idx, pipeline)

        tasks = [sem_task(chunk, idx) for idx, chunk in enumerate(batches)]
        logger.info(f"开始生成增强内容（启用集: {sorted(enabled)}），共 {len(batches)} 个批次，并发数: {max_concurrency}（批次大小: {batch_size}）")
        results_list = await asyncio.gather(*tasks)
        end_time = time.time()
        logger.info(f"全部批次处理完成，总耗时: {end_time - start_time:.2f}秒")
        audit.log("process.generate.done", resource_type="datas", resource_id=None,
                  detail={"total_chunks": total, "batch_size": batch_size, "enabled_enhancers": sorted(enabled),
                          "max_concurrency": max_concurrency, "duration_ms": round((end_time - start_time) * 1000, 1),
                          "mode": "full"})

        # 统计
        total_sub_questions = 0
        total_summaries = 0
        for results in results_list:
            chunk_id = results.get("idx")
            batch_start = chunk_id * batch_size
            batch_end = min(batch_start + batch_size, len(datas))
            for i, idx in enumerate(range(batch_start, batch_end)):
                doc_result = results["results"][i]
                datas[idx].sub_questions = [q for q in doc_result["subqs"] if q]
                datas[idx].summary = doc_result["summary"]
                total_sub_questions += len(datas[idx].sub_questions)
                if datas[idx].summary:
                    total_summaries += 1

        logger.info(f"增强内容生成完成，共生成 {total_sub_questions} 个子问题，{total_summaries} 个摘要")

    async def _process_and_persist_batch(
        self, chunk, batch_data, batch_idx, document_id, knowledge_base_id, pipeline
    ):
        """
        处理单个批次 + 立即写 DB（增量模式）。

        文档 03：LLM 调用委托 pipeline；未启用的增强字段在写库时
        skip（不删除已有数据、不写入空值），保护此前生成的增强内容。
        """
        logger.info(f"增量批次 {batch_idx} 开始，包含 {len(chunk)} 个块")
        start_time = time.time()

        results = await pipeline.run_batch(chunk)

        # 构建批量写入数据列表
        from services.database import db

        skip_subqs = "sub_question" not in pipeline.enabled
        skip_summary = "summary" not in pipeline.enabled

        chunk_data_list = []
        for i, data in enumerate(batch_data):
            chunk_db_id = data.metadata.get("chunk_id")
            if chunk_db_id is None:
                continue
            parsed = results[i]
            chunk_data_list.append({
                "chunk_db_id": chunk_db_id,
                "document_id": document_id,
                "knowledge_base_id": knowledge_base_id,
                "metadata": data.metadata,
                "subqs": parsed["subqs"],
                "summary": parsed["summary"],
                "skip_subqs": skip_subqs,
                "skip_summary": skip_summary,
            })

        # 事务性批量保存（原子性保护）
        success = db.save_chunk_enhanced_data_batch(chunk_data_list)
        if not success:
            logger.error(f"增量批次 {batch_idx} 批量保存失败")

        end_time = time.time()
        logger.info(f"增量批次 {batch_idx} 完成并已持久化，耗时: {end_time - start_time:.2f}秒")
    
    async def batch_embed_texts(self, texts, batch_size=None, max_concurrency=None):
        """批量生成嵌入（并行处理）"""
        if not texts:
            return []
        
        batch_size = batch_size or get_runtime("EMBEDDING_BATCH_SIZE", settings.EMBEDDING_BATCH_SIZE)
        max_concurrency = max_concurrency or get_runtime("MAX_CONCURRENCY", settings.MAX_CONCURRENCY)
        start_time = time.time()
        outer_batch_size = batch_size * get_runtime("EMBEDDING_BATCH_FACTOR", settings.EMBEDDING_BATCH_FACTOR)
        # 将文本分成批次
        batches = [texts[i:i+outer_batch_size] for i in range(0, len(texts), outer_batch_size)]
        sem = asyncio.Semaphore(max_concurrency)  # 控制并发数量
        
        async def process_batch(batch, batch_idx):
            """处理单个批次"""
            batch_start = time.time()
            async with sem:
                embeddings = await self.EmbeddingModel.aembed_documents(batch, chunk_size=batch_size)
                batch_end = time.time()
                logger.debug(f"嵌入批次 {batch_idx} 处理完成，耗时: {batch_end - batch_start:.2f}秒")
                return embeddings
        
        # 创建所有任务
        tasks = [process_batch(batch, idx) for idx, batch in enumerate(batches)]
        
        # 并行执行所有任务
        logger.info(f"开始生成嵌入，共 {len(batches)} 个批次，文本数量: {len(texts)}")
        results = await asyncio.gather(*tasks)
        end_time = time.time()
        logger.info(f"嵌入生成完成，总耗时: {end_time - start_time:.2f}秒，平均每条文本耗时: {(end_time - start_time)/len(texts):.4f}秒")
        audit.log("process.embed.done", resource_type="texts",
                  detail={"text_count": len(texts), "batch_count": len(batches),
                          "batch_size": batch_size, "max_concurrency": max_concurrency,
                          "duration_ms": round((end_time - start_time) * 1000, 1)})
        
        # 合并结果
        embeddings = []
        for batch_embeds in results:
            embeddings.extend(batch_embeds)
        
        return embeddings
    
    async def generate_and_fill_embeddings(self, datas, enabled=None):
        """生成并填充嵌入（文档 03：按启用集只嵌入启用的增强内容）"""
        from services.enhancers import resolve_enabled_enhancers

        if enabled is None:
            enabled = resolve_enabled_enhancers(
                datas[0].metadata.get("knowledge_base_id") if datas else None
            )
        enabled = set(enabled)
        need_summary = "summary" in enabled
        need_subq = "sub_question" in enabled

        # 全关：无增强内容需要嵌入
        if not (need_summary or need_subq):
            logger.info("增强器已全部关闭，跳过增强嵌入生成")
            return

        start_time = time.time()
        logger.info(f"开始生成并填充增强内容的嵌入（启用集: {sorted(enabled)}）...")

        # 有效块判定：启用集中的字段非空即可
        if need_summary and need_subq:
            valid_indices = [i for i, d in enumerate(datas) if d.summary and d.sub_questions]
        elif need_summary:
            valid_indices = [i for i, d in enumerate(datas) if d.summary]
        else:
            valid_indices = [i for i, d in enumerate(datas) if d.sub_questions]
        valid_datas = [datas[i] for i in valid_indices]
        logger.info(f"共 {len(valid_datas)} 条数据需要生成嵌入")

        summary_texts = [d.summary for d in valid_datas] if need_summary else []
        subq_texts = [subq for d in valid_datas for subq in d.sub_questions] if need_subq else []

        logger.info(f"需要生成 {len(summary_texts)} 个摘要嵌入和 {len(subq_texts)} 个子问题嵌入")

        # 并行生成 embedding（摘要与子问题无依赖，gather 交错并行；共享同一 Semaphore 限流）
        fill_start_time = time.time()
        sem = asyncio.Semaphore(get_runtime("MAX_CONCURRENCY", settings.MAX_CONCURRENCY))

        async def _embed_with_shared_sem(texts_, inner_batch_size):
            """共享信号量版的批量嵌入：限流语义与 batch_embed_texts 一致，仅坑位可交错占用"""
            if not texts_:
                return []
            outer_batch_size = inner_batch_size * get_runtime("EMBEDDING_BATCH_FACTOR", settings.EMBEDDING_BATCH_FACTOR)
            batches_ = [texts_[i:i + outer_batch_size] for i in range(0, len(texts_), outer_batch_size)]

            async def _run(batch):
                async with sem:
                    return await self.EmbeddingModel.aembed_documents(batch, chunk_size=inner_batch_size)

            results_ = await asyncio.gather(*[_run(b) for b in batches_])
            merged = []
            for r in results_:
                merged.extend(r)
            return merged

        summary_embeddings, subq_embeddings = await asyncio.gather(
            _embed_with_shared_sem(summary_texts, 32),
            _embed_with_shared_sem(subq_texts, 64),
        )
        logger.info(f"摘要/子问题嵌入并行完成，摘要: {len(summary_texts)} 条，子问题: {len(subq_texts)} 条，耗时: {time.time() - fill_start_time:.2f}秒")

        # 填充嵌入（O(n)：valid_datas 与 valid_indices 按位置一一对应，直接枚举落位）
        fill_start = time.time()
        subq_offset = 0
        for pos, (idx, d) in enumerate(zip(valid_indices, valid_datas)):
            if need_summary:
                datas[idx].summary_embedding = summary_embeddings[pos]
            if need_subq:
                datas[idx].subq_embeddings = subq_embeddings[subq_offset:subq_offset + len(d.sub_questions)]
                subq_offset += len(d.sub_questions)
        fill_end = time.time()
        logger.info(f"嵌入填充完成，耗时: {fill_end - fill_start:.2f}秒")

        total_end = time.time()
        logger.info(f"嵌入生成和填充总耗时: {total_end - start_time:.2f}秒")
        audit.log("process.embed.fill_done", resource_type="datas",
                  detail={"valid_chunks": len(valid_datas), "summary_embeddings": len(summary_texts),
                          "subq_embeddings": len(subq_texts), "enabled_enhancers": sorted(enabled),
                          "duration_ms": round((total_end - start_time) * 1000, 1)})
    
    async def generate_chunk_embeddings(self, datas):
        """
        生成 chunk 原文向量（用于 Native 检索）。
        直接对原始 chunk 文本进行向量化，信息保真度高。
        """
        if not datas:
            return
        start_time = time.time()
        logger.info(f"开始生成 chunk 原文向量，共 {len(datas)} 个 chunk...")
        chunk_texts = [d.chunk for d in datas]
        chunk_embeddings = await self.batch_embed_texts(
            chunk_texts,
            batch_size=get_runtime("EMBEDDING_BATCH_SIZE", settings.EMBEDDING_BATCH_SIZE),
            max_concurrency=get_runtime("MAX_CONCURRENCY", settings.MAX_CONCURRENCY),
        )
        for i, d in enumerate(datas):
            d.chunk_embedding = chunk_embeddings[i]
        end_time = time.time()
        logger.info(f"chunk 原文向量生成完成，耗时: {end_time - start_time:.2f}秒")

    # 说明：旧的 process_document_async / process_document 串行流程已删除（文档 04 §3.5 死代码）。
    # 现行流程为 api/processing.py 的四阶段流水线（split / generate / import / full）。
