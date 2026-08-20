"""切割策略适配器（文档 02）。

可插拔的文档切割策略注册表：
  - 新增策略 = 新建模块 + @register 装饰器，document_processor 无需改动；
  - 策略选择三级解析：请求参数 > 知识库配置 > 全局配置（默认 auto = 现有内容探测行为）。
"""

from services.chunking.base import ChunkStrategy, ChunkParams
from services.chunking.registry import (
    register_strategy,
    get_strategy,
    list_strategies,
    resolve_strategy_name,
)

# import 触发策略注册
from services.chunking import markdown as _markdown  # noqa: F401
from services.chunking import recursive as _recursive  # noqa: F401
from services.chunking import auto as _auto  # noqa: F401

__all__ = [
    "ChunkStrategy",
    "ChunkParams",
    "register_strategy",
    "get_strategy",
    "list_strategies",
    "resolve_strategy_name",
]
