import os
import asyncio
import re
import json
import time
import uuid
import logging
from pathlib import Path
from pydantic import BaseModel
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.output_parsers import OutputFixingParser

from config import settings, init_logger

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
    metadata: dict

class SubqAndSummary(BaseModel):
    subqs: list[str]
    summary: str

class DocumentProcessor:
    def __init__(self):
        # 配置模型
        self.LITELLM_BASE_URL = settings.LITELLM_BASE_URL
        self.LITELLM_API_KEY = settings.LITELLM_API_KEY
        if not self.LITELLM_API_KEY:
            raise ValueError("LITELLM_API_KEY 环境变量未设置")
        
        self.EMBEDDING_MODEL = settings.EMBEDDING_MODEL
        self.DEFAULT_MODEL = settings.DEFAULT_MODEL
        
        # 初始化模型
        self.ChatModel = ChatOpenAI(
            model_name=self.DEFAULT_MODEL,
            api_key=self.LITELLM_API_KEY,
            base_url=self.LITELLM_BASE_URL,
            max_retries=3,
            timeout=120,
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
            MIN_CHUNK_SIZE = 100  # 最小chunk大小，低于此值的会被合并
            MAX_CHUNK_SIZE = 800  # 最大chunk大小，超过此值的会被进一步切割
            
            # 初始化递归切割器
            recursive_splitter = RecursiveCharacterTextSplitter(
                separators=["\n\n", "\n"],
                chunk_size=400,
                chunk_overlap=50
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
                chunk_size=400,
                chunk_overlap=50
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
        batch_size=settings.BATCH_SIZE,
        max_concurrency=settings.MAX_CONCURRENCY,
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

        # 立即写 DB
        from services.database import db

        for i, data in enumerate(batch_data):
            chunk_db_id = data.metadata.get("chunk_id")
            if chunk_db_id is None:
                continue
            parsed = results[i]

            # 幂等：先清理旧数据，再写入新数据
            db.delete_sub_questions_by_chunk(chunk_db_id)
            db.delete_summary_by_chunk(chunk_db_id)

            # 写子问题
            for sq in parsed["subqs"]:
                db.add_sub_question(
                    document_id=document_id,
                    chunk_id=chunk_db_id,
                    content=sq,
                    metadata=data.metadata,
                    knowledge_base_id=knowledge_base_id,
                )

            # 写摘要
            if parsed["summary"]:
                db.add_chunk_summary(
                    document_id=document_id,
                    chunk_id=chunk_db_id,
                    content=parsed["summary"],
                    metadata=data.metadata,
                    knowledge_base_id=knowledge_base_id,
                )

        end_time = time.time()
        logger.info(f"增量批次 {batch_idx} 完成并已持久化，耗时: {end_time - start_time:.2f}秒")
    
    async def batch_embed_texts(self, texts, batch_size=settings.EMBEDDING_BATCH_SIZE, max_concurrency=settings.MAX_CONCURRENCY):
        """批量生成嵌入（并行处理）"""
        if not texts:
            return []
        
        start_time = time.time()
        outer_batch_size = batch_size * settings.EMBEDDING_BATCH_FACTOR
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
        
        # 并行生成 embedding
        summary_start = time.time()
        summary_embeddings = await self.batch_embed_texts(summary_texts, batch_size=32, max_concurrency=settings.MAX_CONCURRENCY)
        summary_end = time.time()
        logger.info(f"摘要嵌入生成完成，耗时: {summary_end - summary_start:.2f}秒")
        
        subq_start = time.time()
        subq_embeddings = await self.batch_embed_texts(subq_texts, batch_size=64, max_concurrency=settings.MAX_CONCURRENCY)
        subq_end = time.time()
        logger.info(f"子问题嵌入生成完成，耗时: {subq_end - subq_start:.2f}秒")
        
        # 填充嵌入
        fill_start = time.time()
        subq_offset = 0
        for idx, d in zip(valid_indices, valid_datas):
            datas[idx].summary_embedding = summary_embeddings[valid_datas.index(d)]
            datas[idx].subq_embeddings = subq_embeddings[subq_offset:subq_offset + len(d.sub_questions)]
            subq_offset += len(d.sub_questions)
        fill_end = time.time()
        logger.info(f"嵌入填充完成，耗时: {fill_end - fill_start:.2f}秒")
        
        total_end = time.time()
        logger.info(f"嵌入生成和填充总耗时: {total_end - start_time:.2f}秒")
    
    async def process_document_async(self, markdown_path):
        """异步处理文档"""
        total_start_time = time.time()
        logger.info(f"开始处理文档: {Path(markdown_path).name}")
        
        # 切分文档
        split_start = time.time()
        split_documents = self.split_document(markdown_path)
        split_end = time.time()
        logger.info(f"文档切分耗时: {split_end - split_start:.2f}秒")
        
        # 构建数据对象
        build_start = time.time()
        datas = [StoredData(
            id=f"doc_{uuid.uuid4()}",
            chunk=chunk,
            sub_questions=[],
            subq_embeddings=[],
            summary="",
            summary_embedding=[],
            metadata={"source": Path(markdown_path).name}
        ) for i, chunk in enumerate(split_documents)]
        build_end = time.time()
        logger.info(f"构建数据对象完成，数据数量: {len(datas)}，耗时: {build_end - build_start:.2f}秒")
        
        # 生成子问题和摘要
        subq_summary_start = time.time()
        await self.generate_batches_async_concurrent(datas, batch_size=16, max_concurrency=8)
        subq_summary_end = time.time()
        logger.info(f"生成子问题和摘要耗时: {subq_summary_end - subq_summary_start:.2f}秒")
        
        # 生成嵌入
        embed_start = time.time()
        await self.generate_and_fill_embeddings(datas)
        embed_end = time.time()
        logger.info(f"生成嵌入耗时: {embed_end - embed_start:.2f}秒")
        
        # 提取结果
        extract_start = time.time()
        chunks = [d.chunk for d in datas]
        sub_questions = [d.sub_questions for d in datas]
        summaries = [d.summary for d in datas]
        extract_end = time.time()
        logger.info(f"提取结果耗时: {extract_end - extract_start:.2f}秒")
        
        total_end_time = time.time()
        total_duration = total_end_time - total_start_time
        logger.info(f"文档处理完成，总耗时: {total_duration:.2f}秒")
        logger.info(f"平均每个文档段落处理耗时: {total_duration/len(datas):.4f}秒")
        
        return {
            "chunks": chunks,
            "sub_questions": sub_questions,
            "summaries": summaries,
            "datas": datas
        }
    
    async def process_document(self, markdown_path):
        """处理文档（异步方法）"""
        return await self.process_document_async(markdown_path)