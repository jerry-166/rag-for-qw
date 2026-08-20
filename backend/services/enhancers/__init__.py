"""增强生成适配器（文档 03）。

可插拔的 chunk 增强器注册表：
  - 每种增强（子问题/摘要/未来的实体抽取）是一个 Enhancer；
  - EnhancerPipeline 按启用集装配执行（双开走合并 prompt 保 token 成本）；
  - 启用集三级解析：请求参数 > 知识库配置 > 全局配置（默认双开 = 现有行为）。
"""

from services.enhancers.base import (
    Enhancer,
    SubqAndSummary,
    strip_markdown_json,
    parse_llm_raw,
    call_llm_batch,
)
from services.enhancers.pipeline import (
    EnhancerPipeline,
    resolve_enabled_enhancers,
    VALID_ENHANCERS,
)

__all__ = [
    "Enhancer",
    "SubqAndSummary",
    "strip_markdown_json",
    "parse_llm_raw",
    "call_llm_batch",
    "EnhancerPipeline",
    "resolve_enabled_enhancers",
    "VALID_ENHANCERS",
]
