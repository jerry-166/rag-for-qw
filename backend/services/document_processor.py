import os
import asyncio
import re
import json
import time
import logging
from pydantic import BaseModel
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.output_parsers import OutputFixingParser

from config import settings, init_logger, get_runtime
from services.audit import audit

# 初始化日志记录器
logger = init_logger(__name__)


def _strip_markdown_json(text: str) -> str:
    """
    清理 LLM 输出中的 markdown 代码块包裹。
    
    LLM 经常返回 ```json\n{...}\n``` 格式，PydanticOutputParser 无法直接解析。
    此函数在解析前清理掉代码块标记。
    """
    text = text.strip()
    # 匹配 ```json ... ``` 或 ``` ... ```
    pattern = r'^```(?:json)?\s*\n?(.*?)\n?\s*```$'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text

class StoredData(BaseModel):
    id: str
    chunk: str
    sub_questions: list[str]
    subq_embeddings: list[list[float]]
    summary: str
    summary_embedding: list[float]
    chunk_embedding: list[float] = []  # [新增] chunk原文向量，用于Native检索
    metadata: dict

class SubqAndSummary(BaseModel):
    subqs: list[str]
    summary: str

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
        
        # 初始化解析器
        self.parser = PydanticOutputParser(pydantic_object=SubqAndSummary)
        self.fixing_parser = OutputFixingParser.from_llm(parser=self.parser, llm=self.ChatModel)
        
        # 创建PromptTemplate
        self.prompt_template = PromptTemplate.from_template(
            "你是一个专业的文档解析助手，负责为给定的文档段落生成子问题和摘要。\n"
            "请根据以下文档段落，生成3~5个相关的子问题和摘要。\n"
            "文档段落：{document_text}\n"
            "请严格按照以下JSON格式返回结果：{{'subqs':['subq1', 'subq2', ...], 'summary':'摘要内容'}}，请至少生成1条子问题"
        )
        
        # 创建处理链
        self.gen_chain = self.prompt_template | self.ChatModel | self.fixing_parser
    
    def split_document(self, markdown_content):
        """切分文档"""
        start_time = time.time()
        logger.debug(f"Markdown内容预览：{markdown_content[:100]}...")
        
        # 使用MULTILINE使^匹配每一行的开头
        has1 = bool(re.match(r"^#\s+", markdown_content, re.MULTILINE))
        has2 = bool(re.match(r"^##\s+", markdown_content, re.MULTILINE))
        
        if has1 and has2:
            md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "header1"), ("##", "header2")])
            split_documents = md_splitter.split_text(markdown_content)
            
            # 处理切分结果
            processed_documents = []
            current_chunk = ""
            
            # 定义阈值
            MIN_CHUNK_SIZE = get_runtime("MIN_CHUNK_SIZE", settings.MIN_CHUNK_SIZE)
            MAX_CHUNK_SIZE = get_runtime("MAX_CHUNK_SIZE", settings.MAX_CHUNK_SIZE)

            # 初始化递归切割器
            recursive_splitter = RecursiveCharacterTextSplitter(
                separators=["\n\n", "\n"],
                chunk_size=get_runtime("CHUNK_SIZE", settings.CHUNK_SIZE),
                chunk_overlap=get_runtime("CHUNK_OVERLAP", settings.CHUNK_OVERLAP)
            )
            
            for doc in split_documents:
                doc_text = doc.page_content
                
                # 处理长文档：如果chunk太长，进行递归切割
                if len(doc_text) > MAX_CHUNK_SIZE:
                    logger.debug(f"检测到长文档，长度: {len(doc_text)}，进行递归切割")
                    # 先处理当前积累的内容
                    if current_chunk:
                        processed_documents.append(current_chunk)
                        current_chunk = ""
                    # 对长文档进行递归切割
                    recursive_chunks = recursive_splitter.split_text(doc_text)
                    processed_documents.extend(recursive_chunks)
                else:
                    # 处理短文档：如果chunk太短，与相邻chunk合并
                    if len(doc_text) < MIN_CHUNK_SIZE:
                        logger.debug(f"检测到短文档，长度: {len(doc_text)}，进行合并")
                        current_chunk += doc_text + "\n\n"
                    else:
                        # 先处理当前积累的内容
                        if current_chunk:
                            processed_documents.append(current_chunk.strip())
                            current_chunk = ""
                        # 添加正常大小的chunk
                        processed_documents.append(doc_text)
            
            # 处理最后积累的内容
            if current_chunk:
                processed_documents.append(current_chunk.strip())
            
            split_documents = processed_documents
            logger.info(f"使用Markdown标题切分并处理，段落数: {len(split_documents)}")
        else:
            recursive_splitter = RecursiveCharacterTextSplitter(
                separators=["\n\n", "\n"],
                chunk_size=get_runtime("CHUNK_SIZE", settings.CHUNK_SIZE),
                chunk_overlap=get_runtime("CHUNK_OVERLAP", settings.CHUNK_OVERLAP)
            )
            split_documents = recursive_splitter.split_text(markdown_content)
            logger.info(f"使用递归字符切分，段落数: {len(split_documents)}")
        
        end_time = time.time()
        logger.info(f"文档切分完成，耗时: {end_time - start_time:.2f}秒")
        return {
            "chunks": split_documents
        }
    
    async def process_batch(self, chunk, batch_idx):
        """
        处理批次：使用 abatch 并发调用 LLM 生成子问题和摘要。
        
        防御策略：
        1. LLM 输出 markdown 代码块包裹 → _strip_markdown_json 清理
        2. 单条解析失败 → OutputFixingParser 修复，最终降级返回空
        """
        logger.info(f"开始处理批次 {batch_idx}，包含 {len(chunk)} 个文档")
        start_time = time.time()
        
        # 构建 chain 输入列表（PromptTemplate 需要 document_text 参数）
        inputs = [{"document_text": doc[:3000]} for doc in chunk]
        
        # 使用 abatch 并发调用
        try:
            raw_results = await self.gen_chain.abatch(inputs)
        except Exception as e:
            logger.error(f"批次 {batch_idx} abatch 调用失败: {e}")
            # abatch 整体失败时，降级为逐条调用
            raw_results = []
            for inp in inputs:
                try:
                    result = await self.gen_chain.ainvoke(inp)
                    raw_results.append(result)
                except Exception as inner_e:
                    logger.warning(f"批次 {batch_idx} 单条调用失败: {inner_e}")
                    raw_results.append(None)
        
        # 解析结果
        results = []
        for i, raw in enumerate(raw_results):
            if raw is None:
                results.append({"subqs": [], "summary": ""})
                continue
            try:
                # fixing_parser 成功时直接返回 SubqAndSummary 对象
                if isinstance(raw, SubqAndSummary):
                    results.append({"subqs": raw.subqs, "summary": raw.summary})
                    continue
                # 字符串情况：先清理 markdown 代码块再 JSON 解析
                if isinstance(raw, str):
                    cleaned = _strip_markdown_json(raw)
                    parsed = json.loads(cleaned)
                    results.append({"subqs": parsed.get("subqs", []), "summary": parsed.get("summary", "")})
                    continue
                # 其他情况尝试直接取属性
                results.append({"subqs": getattr(raw, 'subqs', []), "summary": getattr(raw, 'summary', '')})
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                logger.warning(f"批次 {batch_idx} 第 {i} 条解析失败: {e}")
                results.append({"subqs": [], "summary": ""})
        
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
    ):
        """
        并发生成批次（支持增量模式）。

        增量模式（document_id 不为 None）：
        - 先查 DB，逐块检查是否已有 sub_questions + summary
        - 只对缺失的块调用 LLM
        - 每个批次完成后立即写 DB（边生成边持久化）

        全量模式（document_id 为 None）：
        - 直接对所有 datas 调用 LLM，行为同原版
        """
        batch_size = batch_size or get_runtime("BATCH_SIZE", settings.BATCH_SIZE)
        max_concurrency = max_concurrency or get_runtime("MAX_CONCURRENCY", settings.MAX_CONCURRENCY)
        start_time = time.time()
        docs = [d.chunk for d in datas]
        total = len(docs)

        # ==================== 增量模式 ====================
        if document_id is not None:
            from services.database import db

            # 第 1 步：查询 DB，找出每个块是否已有 sub_questions + summary
            miss_indices = []
            for idx, d in enumerate(datas):
                chunk_db_id = d.metadata.get("chunk_id")
                if chunk_db_id is None:
                    # 找不到 chunk_id，跳过（走全量逻辑）
                    miss_indices.append(idx)
                    continue
                subqs = db.get_sub_questions_by_chunk(chunk_db_id)
                summary = db.get_chunk_summary(chunk_db_id)
                if not subqs or not summary:
                    miss_indices.append(idx)

            if not miss_indices:
                logger.info(f"所有 {total} 个块均已生成，跳过 LLM 调用")
                return
            logger.info(f"增量模式：{total} 个块中 {len(miss_indices)} 个需要生成")

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
                        chunk, batch_data, batch_idx, document_id, knowledge_base_id
                    )

            tasks = [sem_task(cb, mb, idx) for idx, (cb, mb) in enumerate(zip(miss_batches, miss_data_batches))]
            await asyncio.gather(*tasks)
            end_time = time.time()
        audit.log("process.generate.done", resource_type="document", resource_id=document_id,
                  kb_id=knowledge_base_id,
                  detail={"total_chunks": total, "batch_size": batch_size,
                          "max_concurrency": max_concurrency, "duration_ms": round((time.time() - start_time) * 1000, 1),
                          "mode": "incremental" if document_id is not None else "full"})
        if document_id is not None:
            logger.info(f"增量批次处理完成，总耗时: {end_time - start_time:.2f}秒")
            return

        # ==================== 全量模式（原有逻辑） ====================
        batches = [docs[i : i + batch_size] for i in range(0, len(docs), batch_size)]
        sem = asyncio.Semaphore(max_concurrency)

        async def sem_task(chunk, batch_idx):
            async with sem:
                return await self.process_batch(chunk, batch_idx)

        tasks = [sem_task(chunk, idx) for idx, chunk in enumerate(batches)]
        logger.info(f"开始生成子问题和摘要，共 {len(batches)} 个批次，并发数: {max_concurrency}（批次大小: {batch_size}）")
        results_list = await asyncio.gather(*tasks)
        end_time = time.time()
        logger.info(f"全部批次处理完成，总耗时: {end_time - start_time:.2f}秒")
        audit.log("process.generate.done", resource_type="datas", resource_id=None,
                  detail={"total_chunks": total, "batch_size": batch_size,
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

        logger.info(f"子问题和摘要生成完成，共生成 {total_sub_questions} 个子问题，{total_summaries} 个摘要")

    async def _process_and_persist_batch(
        self, chunk, batch_data, batch_idx, document_id, knowledge_base_id
    ):
        """
        处理单个批次 + 立即写 DB。
        用于增量模式，每个批次完成后立即持久化，不用等全部完成。
        """
        logger.info(f"增量批次 {batch_idx} 开始，包含 {len(chunk)} 个块")
        start_time = time.time()

        inputs = [{"document_text": doc[:3000]} for doc in chunk]

        try:
            raw_results = await self.gen_chain.abatch(inputs)
        except Exception as e:
            logger.error(f"增量批次 {batch_idx} abatch 失败: {e}")
            raw_results = []
            for inp in inputs:
                try:
                    result = await self.gen_chain.ainvoke(inp)
                    raw_results.append(result)
                except Exception as inner_e:
                    logger.warning(f"增量批次 {batch_idx} 单条失败: {inner_e}")
                    raw_results.append(None)

        # 解析结果
        results = []
        for i, raw in enumerate(raw_results):
            if raw is None:
                results.append({"subqs": [], "summary": ""})
                continue
            try:
                if isinstance(raw, SubqAndSummary):
                    results.append({"subqs": raw.subqs, "summary": raw.summary})
                    continue
                if isinstance(raw, str):
                    cleaned = _strip_markdown_json(raw)
                    parsed = json.loads(cleaned)
                    results.append({"subqs": parsed.get("subqs", []), "summary": parsed.get("summary", "")})
                    continue
                results.append({"subqs": getattr(raw, "subqs", []), "summary": getattr(raw, "summary", "")})
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                logger.warning(f"增量批次 {batch_idx} 第 {i} 条解析失败: {e}")
                results.append({"subqs": [], "summary": ""})

        # 构建批量写入数据列表
        from services.database import db

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
    
    async def generate_and_fill_embeddings(self, datas):
        """生成并填充嵌入"""
        start_time = time.time()
        logger.info("开始生成并填充摘要和子问题的嵌入...")
        valid_indices = [i for i, d in enumerate(datas) if d.summary and d.sub_questions]
        valid_datas = [datas[i] for i in valid_indices]
        logger.info(f"共 {len(valid_datas)} 条数据需要生成嵌入")
        
        summary_texts = [d.summary for d in valid_datas]
        subq_texts = [subq for d in valid_datas for subq in d.sub_questions]
        
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
            datas[idx].summary_embedding = summary_embeddings[pos]
            datas[idx].subq_embeddings = subq_embeddings[subq_offset:subq_offset + len(d.sub_questions)]
            subq_offset += len(d.sub_questions)
        fill_end = time.time()
        logger.info(f"嵌入填充完成，耗时: {fill_end - fill_start:.2f}秒")

        total_end = time.time()
        logger.info(f"嵌入生成和填充总耗时: {total_end - start_time:.2f}秒")
        audit.log("process.embed.fill_done", resource_type="datas",
                  detail={"valid_chunks": len(valid_datas), "summary_embeddings": len(summary_texts),
                          "subq_embeddings": len(subq_texts),
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
