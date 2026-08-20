"""Markdown 标题切割策略（自 document_processor.py 迁移，行为保持一致）。"""

from __future__ import annotations

from typing import List

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from config import init_logger
from services.chunking.base import ChunkParams, ChunkStrategy
from services.chunking.registry import register_strategy

logger = init_logger(__name__)


@register_strategy
class MarkdownHeaderStrategy(ChunkStrategy):
    name = "markdown"
    label = "Markdown 标题切割"
    description = "按 #/## 标题层级切分；过短 chunk 自动合并、过长 chunk 二次递归切割"

    def split(self, text: str, params: ChunkParams) -> List[str]:
        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "header1"), ("##", "header2")]
        )
        split_documents = md_splitter.split_text(text)

        processed_documents: List[str] = []
        current_chunk = ""

        recursive_splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n"],
            chunk_size=params.chunk_size,
            chunk_overlap=params.chunk_overlap,
        )

        for doc in split_documents:
            doc_text = doc.page_content

            # 长 chunk：递归二次切割
            if len(doc_text) > params.max_chunk_size:
                logger.debug(f"检测到长文档，长度: {len(doc_text)}，进行递归切割")
                if current_chunk:
                    # 保持原行为：此分支 append 不 strip（与迁移前一致）
                    processed_documents.append(current_chunk)
                    current_chunk = ""
                recursive_chunks = recursive_splitter.split_text(doc_text)
                processed_documents.extend(recursive_chunks)
            else:
                # 短 chunk：与相邻合并
                if len(doc_text) < params.min_chunk_size:
                    logger.debug(f"检测到短文档，长度: {len(doc_text)}，进行合并")
                    current_chunk += doc_text + "\n\n"
                else:
                    if current_chunk:
                        processed_documents.append(current_chunk.strip())
                        current_chunk = ""
                    processed_documents.append(doc_text)

        if current_chunk:
            processed_documents.append(current_chunk.strip())

        logger.info(f"使用Markdown标题切分并处理，段落数: {len(processed_documents)}")
        return processed_documents
