"""
多轮对话管理模块

管理对话状态、上下文和追问识别，支持：
- 会话管理
- 上下文窗口
- 追问检测
- 对话摘要
"""
import uuid
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import OrderedDict

import sys
import os
# 获取backend目录的绝对路径
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, backend_dir)

from config import settings, init_logger
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

logger = init_logger(__name__)

@dataclass
class ConversationTurn:
    """对话回合"""
    turn_id: str
    query: str
    response: str
    timestamp: datetime
    intent: Optional[str] = None
    entities: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationSession:
    """对话会话"""
    session_id: str
    created_at: datetime
    last_activity: datetime
    turns: List[ConversationTurn] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    summary: Optional[str] = None


class ConversationManager:
    """
    对话管理器
    
    管理多轮对话的状态和上下文
    """
    
    # 追问关键词
    FOLLOW_UP_INDICATORS = [
        "它", "这个", "那个", "这些", "那些",
        "还有", "另外", "除此之外", "那",
        "为什么", "怎么样", "如何",
    ]
    
    # 非追问的明确开头
    NEW_TOPIC_INDICATORS = [
        "请问", "我想问", "告诉我", "解释一下",
        "什么是", "如何", "为什么", "介绍一下",
    ]
    
    def __init__(self, max_history: int = 10, context_window: int = 5, config: Optional[Dict[str, Any]] = None):
        """
        初始化对话管理器
        
        Args:
            max_history: 每会话最大保留轮数
            context_window: 上下文窗口大小
            config: 配置参数，包含LLM相关配置
        """
        self.max_history = max_history
        self.context_window = context_window
        self.sessions: Dict[str, ConversationSession] = {}
        
        # 初始化LLM
        self.config = config or {}
        self.llm = ChatOpenAI(
            model=self.config.get("model", settings.DEFAULT_MODEL),
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
            temperature=0.3,  # 适中温度，生成更自然的摘要
        )
        
        logger.info("[ConversationManager] 对话管理器初始化完成")
    
    def get_or_create_session(self, session_id: str) -> ConversationSession:
        """获取或创建会话"""
        if session_id not in self.sessions:
            now = datetime.now()
            self.sessions[session_id] = ConversationSession(
                session_id=session_id,
                created_at=now,
                last_activity=now,
            )
            logger.info(f"[ConversationManager] 会话 {session_id} 创建")
        else:
            logger.info(f"[ConversationManager] 会话 {session_id} 已存在")
        return self.sessions[session_id]
    
    def add_turn(
        self,
        session_id: str,
        query: str,
        response: str,
        intent: Optional[str] = None,
        entities: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> ConversationTurn:
        """
        添加对话回合
        
        Args:
            session_id: 会话ID
            query: 用户查询
            response: 系统回答
            intent: 意图类型
            entities: 提取的实体
            metadata: 元数据
            
        Returns:
            ConversationTurn: 创建的对话回合
        """
        session = self.get_or_create_session(session_id)
        
        turn = ConversationTurn(
            turn_id=f"{session_id}_{len(session.turns)}",
            query=query,
            response=response,
            timestamp=datetime.now(),
            intent=intent,
            entities=entities or [],
            metadata=metadata or {},
        )
        
        session.turns.append(turn)
        session.last_activity = datetime.now()
        
        # 限制历史长度
        if len(session.turns) > self.max_history:
            # 保留最近的，移除最旧的
            removed = session.turns[:-self.max_history]
            session.turns = session.turns[-self.max_history:]
            
            # 如果有移除的，生成摘要
            logger.info(f"[ConversationManager] 会话 {session_id} 移除 {len(removed)} 个回合")
            if not session.summary:
                # 异步调用生成摘要
                import asyncio
                session.summary = asyncio.run(self._generate_summary(removed))
                logger.info(f"[ConversationManager] 会话 {session_id} 生成摘要: {session.summary}")
        
        logger.info(f"[ConversationManager] 会话 {session_id} 添加回合: {turn.turn_id}")

        return turn
    
    def get_context(
        self,
        session_id: str,
        window_size: Optional[int] = None,
        include_summary: bool = True,
    ) -> Dict[str, Any]:
        """
        获取对话上下文
        
        Args:
            session_id: 会话ID
            window_size: 上下文窗口大小
            include_summary: 是否包含历史摘要
            
        Returns:
            Dict: 上下文信息
        """
        session = self.sessions.get(session_id)
        if not session:
            return {"recent_turns": [], "summary": None}
        
        window = window_size or self.context_window
        recent_turns = session.turns[-window:] if len(session.turns) > window else session.turns
        
        context = {
            "recent_turns": [
                {
                    "query": t.query,
                    "response": t.response,
                    "intent": t.intent,
                    "entities": t.entities,
                }
                for t in recent_turns
            ],
            "turn_count": len(session.turns),
        }
        
        if include_summary and session.summary:
            context["summary"] = session.summary
        logger.info(f"[ConversationManager] 会话 {session_id} 获取上下文: {context}")
        return context
    
    def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        """获取会话完整历史"""
        logger.info(f"[ConversationManager] 会话 {session_id} 获取完整历史")
        session = self.sessions.get(session_id)
        if not session:
            return []
        
        return [
            {
                "query": t.query,
                "response": t.response,
                "intent": t.intent,
                "timestamp": t.timestamp.isoformat(),
            }
            for t in session.turns
        ]
    
    def is_follow_up_question(self, session_id: str, query: str) -> bool:
        """
        判断是否为追问
        
        基于以下规则：
        1. 如果没有会话历史，不是追问
        2. 如果包含追问指示词，且距离上一轮不超过阈值，可能是追问
        3. 如果包含新话题指示词，不是追问
        
        Args:
            session_id: 会话ID
            query: 用户查询
            
        Returns:
            bool: 是否为追问
        """
        session = self.sessions.get(session_id)
        if not session or not session.turns:
            return False
        
        # 检查新话题指示词
        for indicator in self.NEW_TOPIC_INDICATORS:
            if query.startswith(indicator):
                return False
        
        # 检查追问指示词
        for indicator in self.FOLLOW_UP_INDICATORS:
            if indicator in query:
                # 检查时间间隔（5分钟内）
                last_turn = session.turns[-1]
                time_diff = datetime.now() - last_turn.timestamp
                if time_diff < timedelta(minutes=5):
                    return True
        
        # 短查询（少于10字）可能是追问
        if len(query) < 10:
            last_turn = session.turns[-1]
            time_diff = datetime.now() - last_turn.timestamp
            if time_diff < timedelta(minutes=3):
                logger.info(f"[ConversationManager] 会话 {session_id} 短查询 {query} 可能是追问")
                return True
        
        logger.info(f"[ConversationManager] 会话 {session_id} 不是追问")
        return False
    
    def update_context(self, session_id: str, key: str, value: Any):
        """更新会话上下文"""
        logger.info(f"[ConversationManager] 会话 {session_id} 更新上下文: {key} -> {value}")
        session = self.get_or_create_session(session_id)
        session.context[key] = value
    
    def get_context_value(self, session_id: str, key: str) -> Optional[Any]:
        """获取上下文值"""
        logger.info(f"[ConversationManager] 会话 {session_id} 获取上下文值: {key}")
        session = self.sessions.get(session_id)
        if session:
            return session.context.get(key)
        return None
    
    def clear_session(self, session_id: str):
        """清空会话"""
        logger.info(f"[ConversationManager] 会话 {session_id} 清空")
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def cleanup_inactive_sessions(self, max_inactive_minutes: int = 30):
        """清理不活跃的会话"""
        now = datetime.now()
        to_remove = []
        
        for session_id, session in self.sessions.items():
            inactive_time = now - session.last_activity
            if inactive_time > timedelta(minutes=max_inactive_minutes):
                to_remove.append(session_id)
        
        for session_id in to_remove:
            self.clear_session(session_id)
        
        logger.info(f"[ConversationManager] 清理不活跃会话: {len(to_remove)}")
        return len(to_remove)
    
    async def _generate_summary(self, turns: List[ConversationTurn]) -> str:
        """生成对话摘要"""
        try:
            # 构建对话历史文本
            conversation_text = ""
            for i, turn in enumerate(turns):
                conversation_text += f"轮次 {i+1}:\n"
                conversation_text += f"用户: {turn.query}\n"
                conversation_text += f"系统: {turn.response}\n"
                if turn.intent:
                    conversation_text += f"意图: {turn.intent}\n"
                conversation_text += "\n"
            
            # 构建LLM提示
            prompt = f"""请对以下对话进行总结，生成一个简洁明了的摘要，概括对话的主要内容和主题：

{conversation_text}

摘要要求：
1. 总结对话的核心主题和主要内容
2. 包含关键信息和重要观点
3. 语言简洁，逻辑清晰
4. 不超过100字

请直接输出摘要："""
            
            logger.info("[ConversationManager] 调用LLM生成对话摘要...")
            
            # 调用LLM
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            summary = response.content.strip()
            
            logger.info(f"[ConversationManager] LLM生成的摘要: {summary}")
            return summary
        except Exception as e:
            # 出错时使用备用方法
            logger.error(f"[ConversationManager] LLM生成摘要失败: {str(e)}")
            # 备用方法：拼接关键信息
            topics = []
            for turn in turns:
                if turn.intent:
                    topics.append(f"[{turn.intent}]{turn.query[:20]}...")
            fallback_summary = f"历史对话主题: {', '.join(topics[:3])}"
            logger.info(f"[ConversationManager] 使用备用方法生成摘要: {fallback_summary}")
            return fallback_summary
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        logger.info(f"[ConversationManager] 获取统计信息")
        total_turns = sum(len(s.turns) for s in self.sessions.values())
        
        return {
            "active_sessions": len(self.sessions),
            "total_turns": total_turns,
            "avg_turns_per_session": total_turns / len(self.sessions) if self.sessions else 0,
        }


# 测试
if __name__ == "__main__":
    manager = ConversationManager()
    
    # 测试对话管理
    session_id = "test_session"
    
    manager.add_turn(session_id, "什么是RAG？", "RAG是检索增强生成...")
    manager.add_turn(session_id, "它有什么优势？", "RAG的优势包括...")
    manager.add_turn(session_id, "如何使用？", "使用RAG需要...")
    
    print("会话历史:")
    for turn in manager.get_session_history(session_id):
        print(f"  Q: {turn['query']}")
        print(f"  A: {turn['response'][:50]}...")
    
    print("\n上下文:")
    context = manager.get_context(session_id)
    print(f"  回合数: {context['turn_count']}")
    print(f"  最近对话: {len(context['recent_turns'])}条")
    
    print("\n追问检测:")
    test_queries = [
        "它有什么优势？",  # 追问
        "什么是机器学习？",  # 新话题
        "那具体呢？",  # 追问
    ]
    for query in test_queries:
        is_follow_up = manager.is_follow_up_question(session_id, query)
        print(f"  '{query}' -> {'追问' if is_follow_up else '新话题'}")
    
    print("\n统计:")
    print(manager.get_stats())
