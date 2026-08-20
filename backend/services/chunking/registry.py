"""切割策略注册表（文档 02 §3.2）。"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from config import settings, get_runtime
from services.chunking.base import ChunkStrategy

_REGISTRY: Dict[str, Type[ChunkStrategy]] = {}


def register_strategy(cls: Type[ChunkStrategy]) -> Type[ChunkStrategy]:
    """装饰器：将策略类注册到全局注册表。"""
    if not cls.name:
        raise ValueError(f"策略类 {cls.__name__} 必须设置 name 属性")
    _REGISTRY[cls.name] = cls
    return cls


def get_strategy(name: Optional[str]) -> ChunkStrategy:
    """按名称获取策略实例；未知/空名称回落 auto（= 现有默认行为）。"""
    cls = _REGISTRY.get(name) or _REGISTRY["auto"]
    return cls()


def list_strategies() -> List[dict]:
    """所有已注册策略的元信息（供设置页 / 前端下拉渲染）。"""
    return [
        {"name": cls.name, "label": cls.label, "description": cls.description}
        for cls in _REGISTRY.values()
    ]


def resolve_strategy_name(
    request_strategy: Optional[str] = None,
    kb_strategy: Optional[str] = None,
) -> str:
    """三级策略解析：请求参数 > 知识库配置 > 全局配置（文档 02 §3.3）。

    调用方先取 KB 的 chunk_strategy（可能为 None = 跟随全局），
    再传入本函数完成整条解析链。未知名称交由 get_strategy 回落 auto。
    """
    if request_strategy:
        return request_strategy
    if kb_strategy:
        return kb_strategy
    return get_runtime("CHUNK_STRATEGY", settings.CHUNK_STRATEGY)
