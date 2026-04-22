"""
简单RAG Agent实现

使用LangChain快速构建的Agent，特点：
1. 代码简洁，易于理解和维护
2. 使用简单的Chain结构
3. 适合快速原型开发和简单场景
4. 直接调用工具，无需复杂的状态管理

局限性：
1. 无复杂任务拆解能力
2. 无多轮对话上下文管理
3. 异常处理较简单
4. 无意图识别和实体提取
"""
import time
import asyncio
from typing import Dict, List, Any, Optional
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

import sys
import os

# 确保backend目录在sys.path中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import settings
# 使用相对导入
from ..base import BaseAgent, AgentResponse, AgentMessage, StreamChunk


class SimpleRAGAgent(BaseAgent):
    """
    简单RAG Agent
    
    使用LangChain的Chain方式快速构建，适合：
    - 快速原型验证
    - 简单问答场景
    - 学习和理解基础概念
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("SimpleRAGAgent", config)
        
        # 初始化LLM
        self.llm = ChatOpenAI(
            model=self.config.get("model", settings.DEFAULT_MODEL),
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
            temperature=self.config.get("temperature", 0.7),
        )
        
        # 构建基础Chain
        self._build_chain()
    
    def _setup_tools(self):
        """设置简单工具集"""
        # 工具将在初始化后注入
        pass
    
    def _build_chain(self):
        """构建简单的处理Chain"""
        
        # 系统提示词
        system_template = """你是一个RAG知识库助手。基于以下检索到的信息回答用户问题。
如果检索结果中没有相关信息，请明确告知用户。

检索信息：
{context}

请用中文回答，保持简洁准确。"""
        
        # 创建prompt模板
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ])
        
        # 构建chain：获取上下文 -> 格式化prompt -> 调用LLM -> 解析输出
        self.chain = (
            {
                "context": lambda x: self._get_context(x["question"]),
                "chat_history": lambda x: x.get("chat_history", []),
                "question": lambda x: x["question"],
            }
            | self.prompt
            | self.llm
            | StrOutputParser()
        )
    
    def _get_context(self, question: str) -> str:
        """
        获取检索上下文
        简单版本：直接调用检索工具
        """
        # 如果注册了检索工具，使用它
        if "retriever" in self.tools:
            try:
                results = self.tools["retriever"](question)
                if results:
                    return "\n\n".join([
                        f"[相关度: {r.get('score', 'N/A')}] {r.get('content', '')}"
                        for r in results[:3]  # 只取前3条
                    ])
            except Exception as e:
                return f"检索出错: {str(e)}"
        
        return "暂无相关检索信息"
    
    async def process(self, query: str, session_id: Optional[str] = None,
                     chat_history: Optional[List[Dict]] = None,
                     callbacks: Optional[List] = None,
                     **kwargs) -> AgentResponse:
        """
        处理用户查询
        
        Args:
            query: 用户查询
            session_id: 会话ID（简单版本不使用）
            chat_history: 对话历史
            callbacks: LangChain callbacks（用于追踪，如 Langfuse CallbackHandler）
            
        Returns:
            AgentResponse: Agent响应
        """
        start_time = time.time()
        
        try:
            # 转换对话历史格式
            history_messages = []
            if chat_history:
                for msg in chat_history[-5:]:  # 只保留最近5轮
                    if msg.get("role") == "user":
                        history_messages.append(HumanMessage(content=msg["content"]))
                    elif msg.get("role") == "assistant":
                        history_messages.append(AIMessage(content=msg["content"]))
            
            print(f"Processing query: {query}")
            print(f"Chat history: {history_messages}")
            # 获取上下文（同时统计检索结果数量）
            context = self._get_context(query)
            # print(f"Context: {context}")
            # 统计检索到的文档数量
            sources_count = 0
            if "retriever" in self.tools:
                try:
                    retriever_results = self.tools["retriever"](query)
                    sources_count = len(retriever_results) if retriever_results else 0
                except Exception:
                    pass
            
            print(f"Prompt: {self.prompt.format(context=context, question=query, chat_history=history_messages)}")
            # 执行chain，注入追踪 callbacks
            invoke_kwargs = {}
            if callbacks:
                invoke_kwargs["config"] = {"callbacks": callbacks}
            result = await self.chain.ainvoke(
                {
                    "question": query,
                    "chat_history": history_messages,
                },
                **invoke_kwargs,
            )
            
            processing_time = time.time() - start_time
            
            return AgentResponse(
                content=result,
                metadata={
                    "session_id": session_id,
                    "has_context": "暂无相关检索信息" not in self._get_context(query),
                    "sources_count": sources_count,
                },
                processing_time=processing_time
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            return AgentResponse(
                content=f"处理查询时出错: {str(e)}",
                metadata={"error": str(e)},
                processing_time=processing_time
            )
    
    def set_retriever(self, retriever_func):
        """
        设置检索函数
        
        Args:
            retriever_func: 检索函数，接收query返回结果列表
        """
        self.register_tool("retriever", retriever_func)
    
    async def stream_process(self, query: str, chat_history: Optional[List[Dict]] = None,
                              callbacks: Optional[List] = None, **kwargs):
        """
        流式处理（简单版本：异步调用 process 后模拟分块输出）

        协议要求：返回 AsyncGenerator[StreamChunk, None]

        Args:
            callbacks: LangChain callbacks（透传给 process）
        """
        result = await self.process(query, chat_history=chat_history, callbacks=callbacks)
        content = result.content
        chunk_size = 15
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            done = i + chunk_size >= len(content)
            yield StreamChunk(chunk=chunk, done=done, event_type="chunk")


# 简单的演示用法
if __name__ == "__main__":
    
    # 模拟检索函数
    def mock_retriever(query: str) -> List[Dict]:
        """模拟检索结果"""
        return [
            {"content": f"这是关于'{query}'的模拟检索结果1", "score": 0.95},
            {"content": f"这是关于'{query}'的模拟检索结果2", "score": 0.87},
        ]
    
    # 创建Agent
    agent = SimpleRAGAgent()
    agent.set_retriever(mock_retriever)
    
    # 测试
    async def test():
        response = await agent.process("什么是RAG技术？")
        print(f"回答: {response.content}")
        print(f"处理时间: {response.processing_time:.2f}s")
    
    asyncio.run(test())
