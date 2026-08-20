"""切割策略基类与参数包（文档 02 §3.1）。

策略为纯函数：只消费 ChunkParams、不读取全局运行时配置——由调用方
（DocumentProcessor）组装参数，保证策略可独立单测。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class ChunkParams:
    """切割参数包（从全局 runtime 配置 / KB 覆盖组装而来）。"""

    chunk_size: int = 400        # 递归切割目标大小
    chunk_overlap: int = 50      # 相邻 chunk 重叠字符数
    min_chunk_size: int = 100    # 短 chunk 合并阈值（markdown 策略）
    max_chunk_size: int = 800    # 长 chunk 二次切割阈值（markdown 策略）


class ChunkStrategy(ABC):
    """切割策略抽象基类。

    子类需声明 name / label / description，并实现 split()。
    返回字符串列表（与既有 split_document 返回格式一致，下游零改动）。
    """

    name: str = ""
    label: str = ""
    description: str = ""

    @abstractmethod
    def split(self, text: str, params: ChunkParams) -> List[str]:
        """将文档文本切分为 chunk 字符串列表。"""
        raise NotImplementedError

    def default_params(self) -> dict:
        """策略参数默认值（供设置页/KB 配置展示，当前四参数全局共享）。"""
        p = ChunkParams()
        return {
            "chunk_size": p.chunk_size,
            "chunk_overlap": p.chunk_overlap,
            "min_chunk_size": p.min_chunk_size,
            "max_chunk_size": p.max_chunk_size,
        }
