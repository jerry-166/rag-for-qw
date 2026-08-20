"""递归字符切割策略（自 document_processor.py 迁移，行为保持一致）。"""

from __future__ import annotations

from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import init_logger
from services.chunking.base import ChunkParams, ChunkStrategy
from services.chunking.registry import register_strategy

logger = init_logger(__name__)


@register_strategy
class RecursiveStrategy(ChunkStrategy):
    name = "recursive"
    label = "递归字符切割"
    description = "按 \\n\\n / \\n 分隔符递归切分至目标大小，通用性最强"

    def split(self, text: str, params: ChunkParams) -> List[str]:
        recursive_splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n"],
            chunk_size=params.chunk_size,
            chunk_overlap=params.chunk_overlap,
        )
        chunks = recursive_splitter.split_text(text)
        logger.info(f"使用递归字符切分，段落数: {len(chunks)}")
        return chunks
