"""自动策略：按内容探测委托 markdown / recursive（= 迁移前的默认行为）。"""

from __future__ import annotations

import re
from typing import List

from config import init_logger
from services.chunking.base import ChunkParams, ChunkStrategy
from services.chunking.registry import register_strategy, get_strategy

logger = init_logger(__name__)


@register_strategy
class AutoStrategy(ChunkStrategy):
    name = "auto"
    label = "自动探测（默认）"
    description = "文档同时含 # 与 ## 标题时走 Markdown 标题切割，否则走递归字符切割"

    def split(self, text: str, params: ChunkParams) -> List[str]:
        # MULTILINE 使 ^ 匹配每一行行首（与迁移前探测逻辑一致）
        has1 = bool(re.match(r"^#\s+", text, re.MULTILINE))
        has2 = bool(re.match(r"^##\s+", text, re.MULTILINE))

        if has1 and has2:
            delegate = get_strategy("markdown")
        else:
            delegate = get_strategy("recursive")
        return delegate.split(text, params)
