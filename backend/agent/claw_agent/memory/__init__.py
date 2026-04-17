"""
RAG Agent Memory 模块

融合 mini-openclew 的"文件即记忆"设计理念：
- 每个会话对应一个 JSON 文件（sessions/）
- 长期记忆写入 MEMORY.md（可供 System Prompt 读取）
- System Prompt 动态拼接（workspace/*.md）
- 技能快照（可扩展的 Skills 插件化设计预留）
"""

from .memory_manager import MemoryManager
from .session_store import SessionStore

__all__ = ["MemoryManager", "SessionStore"]
