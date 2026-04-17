"""
Agent基础类和类型定义
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class IntentType(Enum):
    """意图类型枚举"""
    RETRIEVAL = "retrieval"           # 知识检索
    SUMMARIZATION = "summarization"   # 内容摘要
    COMPARISON = "comparison"         # 对比分析
    ANALYSIS = "analysis"             # 深度分析
    CLARIFICATION = "clarification"   # 澄清问题
    GREETING = "greeting"             # 问候
    UNKNOWN = "unknown"               # 未知意图


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Entity:
    """实体信息"""
    name: str
    type: str
    value: Any
    confidence: float = 1.0
    start_pos: Optional[int] = None
    end_pos: Optional[int] = None


@dataclass
class Intent:
    """意图识别结果"""
    type: IntentType
    confidence: float
    sub_intents: List['Intent'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubTask:
    """子任务定义"""
    id: str
    description: str
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


@dataclass
class AgentMessage:
    """Agent消息"""
    role: str  # user, assistant, system, tool
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AgentState:
    """Agent状态"""
    session_id: str
    messages: List[AgentMessage] = field(default_factory=list)
    current_intent: Optional[Intent] = None
    entities: List[Entity] = field(default_factory=list)
    subtasks: List[SubTask] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """Agent响应"""
    content: str
    intent: Optional[Intent] = None
    entities: List[Entity] = field(default_factory=list)
    subtasks: List[SubTask] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_time: float = 0.0


@dataclass
class StreamChunk:
    """流式响应块"""
    chunk: str
    done: bool
    event_type: str = "chunk"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        data = {
            "type": self.event_type,
            "chunk": self.chunk,
            "done": self.done,
            **self.metadata
        }
        import json
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class BaseAgent(ABC):
    """Agent基础类"""
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self.tools: Dict[str, Callable] = {}
        self._setup_tools()
    
    @abstractmethod
    def _setup_tools(self):
        """设置可用工具"""
        pass
    
    @abstractmethod
    async def process(self, query: str, session_id: Optional[str] = None, 
                     **kwargs) -> AgentResponse:
        """处理用户查询"""
        pass
    
    def register_tool(self, name: str, func: Callable):
        """注册工具"""
        self.tools[name] = func
    
    async def execute_tool(self, tool_name: str, **params) -> Any:
        """执行工具"""
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not found")
        return await self.tools[tool_name](**params) if asyncio.iscoroutinefunction(
            self.tools[tool_name]
        ) else self.tools[tool_name](**params)


import asyncio
