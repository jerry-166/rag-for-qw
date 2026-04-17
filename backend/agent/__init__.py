"""
Agent 系统模块 — 可插拔多 Agent 架构

三种 Agent 实现对比：

┌─────────────┬───────────────────┬──────────────────────┬─────────────────────┐
│ Agent       │ 架构风格          │ 特点                 │ 适用场景             │
├─────────────┼───────────────────┼──────────────────────┼─────────────────────┤
│ simple      │ LangChain Chain   │ 轻量、简洁、快速      │ 快速原型、简单问答    │
│ advanced    │ LangGraph 完整Agent│ 意图识别、实体提取   │ 生产环境、复杂对话    │
│             │                   │ 任务规划、工具调用    │                     │
│ claw        │ LangGraph RAG流程 │ 查询扩展、混合检索    │ 深度 RAG、知识库问答  │
│             │ + 记忆管理        │ 精排、SSE流式、记忆   │                     │
└─────────────┴───────────────────┴──────────────────────┴─────────────────────┘

快速开始：

  # 方式 1: 直接使用注册中心（推荐）
  from agent.registry import setup_registry, get_registry

  registry = setup_registry()  # 初始化注册
  agent = registry.get("claw")  # 获取指定 Agent

  # 方式 2: 直接导入具体 Agent
  from agent import SimpleRAGAgent, AdvancedRAGAgent

  # 方式 3: 通过 API
  POST /api/agent/chat?agent_type=claw
"""

# ── 各层级导出 ──────────────────────────────────────────────

# 底层 Agent 类（保持向后兼容）
from agent.simple.agent import SimpleRAGAgent
from agent.advanced.agent import AdvancedRAGAgent

# 统一响应格式
from agent.registry import (
    AgentType,
    UnifiedResponse,
    StreamChunk,
    AgentAdapter,
    AgentRegistry,
    get_registry,
    setup_registry,
)

# ── 兼容性别名 ──────────────────────────────────────────────

# 为了向后兼容，保留原有导出
__all__ = [
    # 原有导出
    "SimpleRAGAgent",
    # 新的插件化接口
    "AgentType",
    "UnifiedResponse",
    "StreamChunk",
    "AgentAdapter",
    "AgentRegistry",
    "get_registry",
    "setup_registry",
]
