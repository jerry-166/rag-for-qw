"""
Agent 插件化架构核心

设计思路（参考 mini-openclew 的插件注册模式）：
1. AgentAdapter 适配器层 —— 统一三种不同风格的 Agent 接口
2. AgentRegistry 注册中心 —— 运行时注册/切换/获取 Agent 实例
3. AgentFactory 工厂函数 —— 根据类型字符串创建 Agent 实例

三种 Agent 的定位对比：
  simple   → 轻量快速，适合简单问答（Chain 风格）
  advanced → 功能完整，适合生产环境（LangGraph 完整 Agent）
  claw     → RAG 专属，适合深度 RAG 场景（SSE 流式 + 记忆管理）
"""

import asyncio
import inspect
import uuid
import sys
import os
from typing import Dict, List, Any, Optional, Callable, Protocol, TypeVar, Union, AsyncGenerator
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime
import threading
import json

# 添加backend目录到搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import init_logger

logger = init_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Agent 类型枚举
# ─────────────────────────────────────────────────────────────

class AgentType(Enum):
    """支持的 Agent 类型"""
    SIMPLE = "simple"       # 轻量 Chain Agent
    ADVANCED = "advanced"   # 完整 LangGraph Agent
    CLAW = "claw"           # RAG 专属工作流


# ─────────────────────────────────────────────────────────────
# 统一响应格式
# ─────────────────────────────────────────────────────────────

@dataclass
class UnifiedResponse:
    """
    统一响应格式

    适配三种 Agent 的不同返回结构，输出统一的 JSON 格式。
    """
    content: str                          # 回答内容
    agent_type: str                        # 使用的 Agent 类型
    session_id: str                        # 会话 ID
    intent: Optional[str] = None          # 识别到的意图
    confidence: Optional[float] = None    # 意图置信度
    entities: List[Dict[str, Any]] = field(default_factory=list)   # 提取的实体
    subtasks: List[Dict[str, Any]] = field(default_factory=list)   # 子任务列表
    tool_calls: List[Dict[str, Any]] = field(default_factory=list) # 工具调用记录
    sources_count: int = 0                 # 检索到的文档数量
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据
    processing_time: float = 0.0          # 处理耗时（秒）
    error: Optional[str] = None           # 错误信息

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return asdict(self)

    def to_sse_event(self, event_type: str = "message") -> str:
        """转换为 SSE 事件格式"""
        data = {"type": event_type, **self.to_dict()}
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class StreamChunk:
    """流式响应块"""
    chunk: str
    done: bool
    event_type: str = "chunk"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        data = {"type": self.event_type, "chunk": self.chunk, "done": self.done, **self.metadata}
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ─────────────────────────────────────────────────────────────
# Agent 适配器协议（Protocol，用于类型检查）
# ─────────────────────────────────────────────────────────────

from typing import runtime_checkable

@runtime_checkable
class AgentAdapter(Protocol):
    """
    Agent 适配器协议

    所有 Agent 必须实现以下接口，才能被 AgentRegistry 管理。
    """

    @property
    def name(self) -> str:
        """Agent 名称"""
        ...

    @property
    def agent_type(self) -> AgentType:
        """Agent 类型"""
        ...

    async def process(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        **kwargs
    ) -> UnifiedResponse:
        """
        处理查询

        Args:
            query: 用户查询
            session_id: 会话 ID（可选）
            chat_history: 对话历史（可选）
            **kwargs: 额外参数

        Returns:
            UnifiedResponse: 统一响应格式
        """
        ...

    async def stream_process(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        流式处理（可选实现）

        如果 Agent 不支持流式，返回普通响应。
        """
        ...


# ─────────────────────────────────────────────────────────────
# 简单 Agent 适配器
# ─────────────────────────────────────────────────────────────

class SimpleAgentAdapter:
    """
    SimpleRAGAgent 适配器

    将 simple/agent.py 的 SimpleRAGAgent 适配为统一接口。
    特点：轻量 Chain，无状态管理。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        from agent.simple.agent import SimpleRAGAgent
        self._agent = SimpleRAGAgent(config=config)
        logger.info("[SimpleAgentAdapter] 初始化完成")

    @property
    def name(self) -> str:
        return self._agent.name

    @property
    def agent_type(self) -> AgentType:
        return AgentType.SIMPLE

    async def process(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        callbacks: Optional[List] = None,
        **kwargs
    ) -> UnifiedResponse:
        start = datetime.now()
        logger.info(f"[SimpleAgentAdapter] 开始处理查询: {query}")
        try:
            response = await self._agent.process(
                query=query,
                session_id=session_id,
                chat_history=chat_history or [],
                callbacks=callbacks,
                **kwargs
            )

            return UnifiedResponse(
                content=response.content,
                agent_type=self.agent_type.value,
                session_id=session_id or str(uuid.uuid4()),
                metadata={"raw_metadata": response.metadata},
                sources_count=response.metadata.get("sources_count", 0) if isinstance(response.metadata, dict) else 0,
                processing_time=response.processing_time or (datetime.now() - start).total_seconds(),
            )

        except Exception as e:
            logger.error(f"[SimpleAgentAdapter] 处理失败: {e}")
            return UnifiedResponse(
                content=f"处理失败: {str(e)}",
                agent_type=self.agent_type.value,
                session_id=session_id or str(uuid.uuid4()),
                error=str(e),
                processing_time=(datetime.now() - start).total_seconds(),
            )

    async def stream_process(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        callbacks: Optional[List] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """Simple Agent 模拟流式输出"""
        response = await self.process(query, session_id, chat_history, callbacks=callbacks, **kwargs)
        logger.info(f"[SimpleAgentAdapter] 流式处理查询: {query}")
        if response.error:
            logger.error(f"[SimpleAgentAdapter] 流式处理查询失败: {response.error}")
            yield StreamChunk(chunk="", done=True, event_type="error")
            return

        content = response.content
        for i in range(0, len(content), 15):
            chunk = content[i:i+15]
            done = i + 15 >= len(content)
            yield StreamChunk(chunk=chunk, done=done, metadata={"agent_type": self.agent_type.value})
            if not done:
                await asyncio.sleep(0.02)


# ─────────────────────────────────────────────────────────────
# 高级 Agent 适配器
# ─────────────────────────────────────────────────────────────

class AdvancedAgentAdapter:
    """
    AdvancedRAGAgent 适配器

    将 advanced/agent.py 的 AdvancedRAGAgent 适配为统一接口。
    特点：完整 LangGraph，支持意图识别、实体提取、任务规划。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        from agent.advanced.agent import AdvancedRAGAgent
        self._agent = AdvancedRAGAgent(config=config)
        logger.info("[AdvancedAgentAdapter] 初始化完成")

    @property
    def name(self) -> str:
        return self._agent.name

    @property
    def agent_type(self) -> AgentType:
        return AgentType.ADVANCED

    async def process(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        callbacks: Optional[List] = None,
        **kwargs
    ) -> UnifiedResponse:
        start = datetime.now()
        logger.info(f"[AdvancedAgentAdapter] 开始处理查询: {query}")
        try:
            response = await self._agent.process(
                query=query,
                session_id=session_id,
                callbacks=callbacks,
                **kwargs
            )

            # 提取意图信息
            intent_str = None
            confidence = None
            if response.intent:
                intent_str = response.intent.type.value
                confidence = response.intent.confidence

            return UnifiedResponse(
                content=response.content,
                agent_type=self.agent_type.value,
                session_id=session_id or str(uuid.uuid4()),
                intent=intent_str,
                confidence=confidence,
                entities=[{"name": e.name, "type": e.type, "confidence": e.confidence}
                          for e in (response.entities or [])],
                sources_count=response.metadata.get("sources_count", 0) if isinstance(response.metadata, dict) else 0,
                subtasks=[{"id": t.id, "description": t.description, "status": t.status.value}
                          for t in (response.subtasks or [])],
                tool_calls=response.tool_calls or [],
                metadata={"raw_metadata": response.metadata},
                processing_time=response.processing_time or (datetime.now() - start).total_seconds(),
            )

        except Exception as e:
            logger.error(f"[AdvancedAgentAdapter] 处理失败: {e}")
            return UnifiedResponse(
                content=f"处理失败: {str(e)}",
                agent_type=self.agent_type.value,
                session_id=session_id or str(uuid.uuid4()),
                error=str(e),
                processing_time=(datetime.now() - start).total_seconds(),
            )

    async def stream_process(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        callbacks: Optional[List] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """Advanced Agent 模拟流式输出"""
        response = await self.process(query, session_id, chat_history, callbacks=callbacks, **kwargs)
        logger.info(f"[AdvancedAgentAdapter] 流式处理查询: {query}")

        if response.error:
            logger.error(f"[AdvancedAgentAdapter] 流式处理查询失败: {response.error}")
            yield StreamChunk(chunk="", done=True, event_type="error")
            return

        content = response.content
        for i in range(0, len(content), 15):
            chunk = content[i:i+15]
            done = i + 15 >= len(content)
            yield StreamChunk(
                chunk=chunk,
                done=done,
                event_type="chunk",
                metadata={
                    "agent_type": self.agent_type.value,
                    "intent": response.intent,
                    "confidence": response.confidence,
                }
            )
            if not done:
                await asyncio.sleep(0.02)


# ─────────────────────────────────────────────────────────────
# Claw Agent 适配器（RAG 工作流封装）
# ─────────────────────────────────────────────────────────────

class ClawAgentAdapter:
    """
    ClawAgent（RAG 工作流）适配器

    将 claw_agent/rag_workflow.py 封装为统一接口。
    特点：SSE 友好，完整 RAG 链路，记忆管理。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化 ClawAgent 适配器

        Args:
            config: 配置字典，支持以下键：
                - memory_manager: MemoryManager 实例
                - session_store: SessionStore 实例
                - knowledge_base_id: 默认知识库 ID
        """
        from agent.claw_agent.rag_workflow import create_rag_workflow, build_initial_state

        self.config = config or {}
        self._memory_manager = self.config.get("memory_manager")
        self._session_store = self.config.get("session_store")

        # 构建工作流（lazy）
        self._workflow = None
        self._workflow_lock = threading.Lock()

        logger.info("[ClawAgentAdapter] 初始化完成")

    def _get_workflow(self):
        """懒加载工作流（线程安全）"""
        if self._workflow is None:
            with self._workflow_lock:
                if self._workflow is None:
                    from agent.claw_agent.rag_workflow import create_rag_workflow
                    self._workflow = create_rag_workflow(
                        memory_manager=self._memory_manager,
                        session_store=self._session_store,
                    )
        return self._workflow

    @property
    def name(self) -> str:
        return "ClawRAGAgent"

    @property
    def agent_type(self) -> AgentType:
        return AgentType.CLAW

    async def process(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        knowledge_base_id: Optional[int] = None,
        callbacks: Optional[List] = None,
        **kwargs
    ) -> UnifiedResponse:
        """
        处理查询

        Args:
            query: 用户查询
            session_id: 会话 ID（自动生成）
            chat_history: 对话历史（可选，但建议提供）
            knowledge_base_id: 知识库 ID（覆盖默认）
            callbacks: LangChain callbacks（用于追踪，如 Langfuse CallbackHandler）
            **kwargs: 额外参数
        """
        from agent.claw_agent.rag_workflow import build_initial_state
        logger.info(f"[ClawAgentAdapter] 开始处理查询: {query}")
        start = datetime.now()
        session_id = session_id or str(uuid.uuid4())
        knowledge_base_id = knowledge_base_id or self.config.get("knowledge_base_id")

        try:
            workflow = self._get_workflow()
            initial_state = build_initial_state(
                query=query,
                session_id=session_id,
                knowledge_base_id=knowledge_base_id,
                retrieval_mode=kwargs.get("retrieval_mode"),
            )

            # 构建 LangGraph config，合并追踪 callbacks
            invoke_config: Dict[str, Any] = {
                "configurable": {
                    "thread_id": session_id,
                    "checkpoint_ns": "claw_agent",
                    "checkpoint_id": f"{session_id}_{datetime.now().timestamp()}"
                }
            }
            if callbacks:
                invoke_config["callbacks"] = callbacks

            # 执行工作流
            result = await workflow.ainvoke(initial_state, config=invoke_config)

            # 提取意图信息
            intent_obj = result.get("intent")
            intent_str = intent_obj.type.value if intent_obj else None
            confidence = intent_obj.confidence if intent_obj else None

            # 透传 reranked_results 供评估器提取 contexts
            reranked_results = result.get("reranked_results", [])
            sources_data = [
                {
                    "content": r.get("content", ""),
                    "chunk_text": r.get("chunk_text", ""),
                    "score": r.get("rerank_score", r.get("rrf_score", 0)),
                    "source": r.get("source", ""),
                    "type": r.get("type", ""),
                    "metadata": r.get("metadata", {}),
                }
                for r in reranked_results
            ]

            return UnifiedResponse(
                content=result.get("final_answer", ""),
                agent_type=self.agent_type.value,
                session_id=session_id,
                intent=intent_str,
                confidence=confidence,
                sources_count=result.get("metadata", {}).get("sources_count", 0),
                metadata={
                    "events": result.get("events", []),
                    "expanded_queries": result.get("expanded_queries", []),
                    "retrieved_count": result.get("metadata", {}).get("retrieved_count", 0),
                    "error_details": result.get("metadata", {}).get("error_details"),
                    "sources": sources_data,  # 供评估器提取 contexts
                },
                processing_time=result.get("metadata", {}).get(
                    "processing_time_ms",
                    (datetime.now() - start).total_seconds() * 1000
                ) / 1000,
            )

        except Exception as e:
            logger.error(f"[ClawAgentAdapter] 处理失败: {e}")
            return UnifiedResponse(
                content=f"处理失败: {str(e)}",
                agent_type=self.agent_type.value,
                session_id=session_id,
                error=str(e),
                processing_time=(datetime.now() - start).total_seconds(),
            )

    async def stream_process(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        knowledge_base_id: Optional[int] = None,
        callbacks: Optional[List] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        流式处理 —— 基于工作流的 SSE 事件实时推送

        ClawAgent 支持真正的流式输出：
        1. 先发射 thinking 事件（客户端可展示"正在思考..."）
        2. 再逐块发射回答内容

        Args:
            callbacks: LangChain callbacks（用于追踪，如 Langfuse CallbackHandler）
        """
        from agent.claw_agent.rag_workflow import build_initial_state
        logger.info(f"[ClawAgentAdapter] 流式处理查询: {query}")
        
        session_id = session_id or str(uuid.uuid4())
        knowledge_base_id = knowledge_base_id or self.config.get("knowledge_base_id")

        try:
            workflow = self._get_workflow()
            initial_state = build_initial_state(
                query=query,
                session_id=session_id,
                knowledge_base_id=knowledge_base_id,
                retrieval_mode=kwargs.get("retrieval_mode"),
            )

            answer_sent = False  # 防止多个 on_chain_end 重复输出答案

            # 构建 LangGraph config，合并追踪 callbacks
            stream_config: Dict[str, Any] = {
                "configurable": {
                    "thread_id": session_id,
                    "checkpoint_ns": "claw_agent",
                    "checkpoint_id": f"{session_id}_{datetime.now().timestamp()}"
                }
            }
            if callbacks:
                stream_config["callbacks"] = callbacks

            # 使用异步迭代器流式执行
            async for event in workflow.astream_events(
                initial_state, 
                version="v2",
                config=stream_config
            ):
                # 确保event是字典
                if not isinstance(event, dict):
                    logger.warning(f"[ClawAgentAdapter] 收到非字典事件: {event}")
                    continue
                
                event_name = event.get("event", "")
                event_data = event.get("data", {})
                
                # 确保event_data是字典
                if not isinstance(event_data, dict):
                    logger.warning(f"[ClawAgentAdapter] 收到非字典事件数据: {event_data}")
                    continue

                # 解析工作流节点事件
                if event_name == "on_node_start":
                    node_name = event.get("name", "")
                    # 发射 thinking 状态
                    yield StreamChunk(
                        chunk="",
                        done=False,
                        event_type="node_start",
                        metadata={"node": node_name}
                    )

                elif event_name == "on_node_end":
                    node_name = event.get("name", "")
                    output = event_data.get("output", {})

                    # 收集中间事件
                    if isinstance(output, dict):
                        events = output.get("events", [])
                        for ev in events:
                            if not isinstance(ev, dict):
                                continue
                            if ev.get("type") == "thinking":
                                yield StreamChunk(
                                    chunk="",
                                    done=False,
                                    event_type="thinking",
                                    metadata={"message": ev.get("content", "")}
                                )
                            elif ev.get("type") == "intent_classified":
                                yield StreamChunk(
                                    chunk="",
                                    done=False,
                                    event_type="intent",
                                    metadata={
                                        "intent": ev.get("intent"),
                                        "confidence": ev.get("confidence"),
                                    }
                                )
                            elif ev.get("type") == "retrieved":
                                yield StreamChunk(
                                    chunk="",
                                    done=False,
                                    event_type="retrieved",
                                    metadata={
                                        "count": ev.get("count", 0),
                                        # 检索结果列表（供前端展示来源卡片）
                                        "results": ev.get("results", []),
                                    }
                                )
                            elif ev.get("type") == "reranked":
                                yield StreamChunk(
                                    chunk="",
                                    done=False,
                                    event_type="reranked",
                                    metadata={
                                        "count": ev.get("count", 0),
                                        # 精排后结果列表（最终来源）
                                        "results": ev.get("results", []),
                                    }
                                )

                elif event_name == "on_chain_end":
                    # LangGraph 会对每个条件边/子图也触发 on_chain_end，
                    # 此时 output 是路由函数的返回值（字符串如 "continue"），不是最终状态。
                    # 必须过滤掉这些中间事件，只处理包含 final_answer 的真正终态。
                    final_state = event_data.get("output", {})

                    if not isinstance(final_state, dict):
                        # 路由函数返回值（"continue" / "greeting" / "error"），跳过
                        logger.debug(f"[ClawAgentAdapter] 跳过中间 chain_end 事件: {final_state}")
                        continue

                    # 只有包含 final_answer 的状态才是工作流终态
                    final_answer = final_state.get("final_answer", "")
                    if not final_answer:
                        # 中间节点的 chain_end（没有 final_answer），跳过
                        continue

                    if answer_sent:
                        # 防止同一次请求多次输出（LangGraph 可能触发多次 on_chain_end）
                        logger.debug("[ClawAgentAdapter] 已发送过答案，跳过重复 chain_end")
                        continue

                    answer_sent = True

                    if final_answer:
                        # 流式发射回答
                        for i in range(0, len(final_answer), 15):
                            chunk = final_answer[i:i+15]
                            done = i + 15 >= len(final_answer)
                            yield StreamChunk(
                                chunk=chunk,
                                done=done,
                                event_type="chunk",
                                metadata={
                                    "agent_type": self.agent_type.value,
                                    "sources_count": final_state.get("metadata", {}).get("sources_count", 0),
                                }
                            )
                            if not done:
                                await asyncio.sleep(0.02)

                        # 【兜底】流结束后发送 sources_final 事件，确保前端拿到完整来源数据
                        # 前端的 retrieved/reranked 事件可能因为时序问题被覆盖，这里再发一次
                        reranked_results = final_state.get("reranked_results", [])
                        if reranked_results:
                            yield StreamChunk(
                                chunk="",
                                done=False,
                                event_type="sources_final",
                                metadata={
                                    "count": len(reranked_results),
                                    "results": [
                                        {
                                            "content": r.get("content", "")[:300] if r.get("content") else "",
                                            "chunk_text": r.get("chunk_text", "")[:500] if r.get("chunk_text") else "",
                                            "score": r.get("rerank_score", r.get("_similarity", r.get("rrf_score", 0))),
                                            "source": r.get("source", "unknown"),
                                            "type": r.get("type", ""),
                                            "metadata": r.get("metadata", {}),
                                        }
                                        for r in reranked_results
                                    ],
                                    "sources_count": len(reranked_results),
                                },
                            )
                    else:
                        # 无回答（可能有错误）
                        error = final_state.get("error") or final_state.get("metadata", {}).get("error_details")
                        if error:
                            yield StreamChunk(chunk="", done=True, event_type="error", metadata={"error": error})
                        else:
                            yield StreamChunk(chunk="", done=True, event_type="chunk")

        except Exception as e:
            logger.error(f"[ClawAgentAdapter] 流式处理失败: {e}")
            yield StreamChunk(chunk=f"处理失败: {str(e)}", done=True, event_type="error")


# ─────────────────────────────────────────────────────────────
# Agent 注册中心
# ─────────────────────────────────────────────────────────────

class AgentRegistry:
    """
    Agent 注册中心（单例模式）

    功能：
    - 注册 Agent 适配器
    - 按类型获取 Agent 实例
    - 运行时切换默认 Agent
    - 批量对比模式

    用法示例：
      registry = AgentRegistry()
      registry.register(AgentType.SIMPLE, SimpleAgentAdapter)
      registry.register(AgentType.ADVANCED, AdvancedAgentAdapter)

      # 获取默认 Agent
      agent = registry.get()

      # 切换为特定类型
      agent = registry.get(AgentType.CLAW)

      # 批量对比
      results = await registry.compare_all("什么是 RAG？")
    """

    _instance: Optional["AgentRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        """初始化注册表"""
        self._adapters: Dict[AgentType, AgentAdapter] = {}
        self._factories: Dict[AgentType, Callable] = {}
        self._configs: Dict[AgentType, Dict[str, Any]] = {}
        self._default_type: AgentType = AgentType.CLAW  # 默认使用 claw
        self._initialized = False
        logger.info("[AgentRegistry] 初始化完成")

    def register(
        self,
        agent_type: AgentType,
        factory: Optional[Callable] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> "AgentRegistry":
        """
        注册 Agent 工厂

        Args:
            agent_type: Agent 类型
            factory: 工厂函数或类（返回 AgentAdapter 实例）
            config: 该类型 Agent 的默认配置

        Returns:
            self（支持链式调用）
        """
        self._factories[agent_type] = factory
        self._configs[agent_type] = config or {}
        logger.info(f"[AgentRegistry] 注册 Agent: {agent_type.value}")
        return self

    def set_default(self, agent_type: AgentType) -> "AgentRegistry":
        """设置默认 Agent 类型"""
        if agent_type not in self._factories:
            raise ValueError(f"Agent 类型 {agent_type.value} 未注册")
        self._default_type = agent_type
        logger.info(f"[AgentRegistry] 设置默认 Agent: {agent_type.value}")
        return self

    def get(
        self,
        agent_type: Optional[AgentType] = None,
        fresh: bool = False,
    ) -> AgentAdapter:
        """
        获取 Agent 实例

        Args:
            agent_type: Agent 类型（为 None 时使用默认类型）
            fresh: 为 True 时强制重新创建实例

        Returns:
            AgentAdapter 实例
        """
        agent_type = agent_type or self._default_type

        if agent_type not in self._factories:
            raise ValueError(
                f"Agent 类型 {agent_type.value} 未注册，请先调用 registry.register()"
            )

        # 检查缓存
        if not fresh and agent_type in self._adapters:
            return self._adapters[agent_type]

        # 创建新实例
        factory = self._factories[agent_type]
        config = self._configs.get(agent_type, {})

        if callable(factory) and not isinstance(factory, type):
            # 工厂函数
            adapter = factory(config)
        elif inspect.isclass(factory):
            # 直接是类，创建实例后检查是否符合AgentAdapter接口
            adapter = factory(config)
            # 检查是否有必要的属性和方法
            if not hasattr(adapter, 'name') or not hasattr(adapter, 'agent_type') or not hasattr(adapter, 'process'):
                raise TypeError(f"Factory {factory.__name__} does not produce AgentAdapter instances")
        else:
            raise TypeError(f"Invalid factory for {agent_type.value}: {factory}")

        self._adapters[agent_type] = adapter
        logger.info(f"[AgentRegistry] 获取 Agent 实例: {agent_type.value}")
        return adapter

    def list_registered(self) -> List[Dict[str, str]]:
        """列出所有已注册的 Agent 类型"""
        return [
            {
                "type": at.value,
                "is_default": at == self._default_type,
            }
            for at in self._factories.keys()
        ]

    async def compare_all(
        self,
        query: str,
        session_id: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None,
        callbacks: Optional[List] = None,
    ) -> Dict[str, UnifiedResponse]:
        """
        批量对比所有已注册的 Agent

        Args:
            query: 查询文本
            session_id: 会话 ID（每个 Agent 会生成独立的 session_id）
            chat_history: 对话历史
            callbacks: LangChain callbacks（透传给 process 方法）
        
        Returns:
            { agent_type: UnifiedResponse } 字典
        """
        logger.info(f"[AgentRegistry] 开始对比所有 Agent: {query}")
        results = {}

        for agent_type in self._factories.keys():
            try:
                agent = self.get(agent_type)
                response = await agent.process(
                    query=query,
                    session_id=f"{session_id}_{agent_type.value}" if session_id else None,
                    chat_history=chat_history,
                    callbacks=callbacks,
                )
                results[agent_type.value] = response
            except Exception as e:
                logger.error(f"[AgentRegistry] 对比模式失败 ({agent_type.value}): {e}")
                results[agent_type.value] = UnifiedResponse(
                    content=f"Agent 执行失败: {str(e)}",
                    agent_type=agent_type.value,
                    session_id=str(uuid.uuid4()),
                    error=str(e),
                )

        return results

    def reset(self) -> "AgentRegistry":
        """重置注册表（清除所有缓存实例）"""
        self._adapters.clear()
        logger.info("[AgentRegistry] 重置完成")
        return self


# ─────────────────────────────────────────────────────────────
# 全局注册中心实例（便于 API 层直接导入使用）
# ─────────────────────────────────────────────────────────────

_global_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """获取全局 Agent 注册中心实例"""
    global _global_registry
    if _global_registry is None:
        _global_registry = AgentRegistry()
    return _global_registry


def setup_registry(
    claw_memory_manager=None,
    claw_session_store=None,
    default_type: AgentType = AgentType.CLAW,
) -> AgentRegistry:
    """
    设置全局 Agent 注册中心（推荐在应用启动时调用一次）

    Args:
        claw_memory_manager: ClawAgent 所需的 MemoryManager 实例
        claw_session_store: ClawAgent 所需的 SessionStore 实例
        default_type: 默认使用的 Agent 类型

    Returns:
        配置好的 AgentRegistry 实例
    """
    registry = get_registry()

    # 注册三种 Agent
    registry.register(AgentType.SIMPLE, SimpleAgentAdapter)
    registry.register(AgentType.ADVANCED, AdvancedAgentAdapter)
    registry.register(
        AgentType.CLAW,
        lambda cfg: ClawAgentAdapter({
            **cfg,
            "memory_manager": claw_memory_manager,
            "session_store": claw_session_store,
        }),
    )

    # 设置默认类型
    registry.set_default(default_type)

    logger.info(f"[AgentRegistry] Agent 注册中心配置完成，默认: {default_type.value}")
    return registry
