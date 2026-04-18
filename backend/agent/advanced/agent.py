"""
高级RAG Agent实现

基于LangGraph的复杂Agent系统，特点：
1. 意图识别 - 准确理解用户意图
2. 实体提取 - 识别关键信息
3. 任务规划 - 复杂查询拆解
4. 工具调用 - 自动选择和调用工具
5. 对话管理 - 上下文感知的多轮交互
6. 异常处理 - 完善的错误恢复机制

适合生产环境，可处理复杂场景
"""
import time
import uuid
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime

from langchain_openai import ChatOpenAI

import sys
import os
# 添加backend/agent目录到搜索路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import settings, init_logger
logger = init_logger(__name__)
# 直接导入base模块
from base import BaseAgent, AgentResponse, IntentType
# 使用相对导入
from .intent_classifier import IntentClassifier
from .entity_extractor import EntityExtractor
from .task_planner import TaskPlanner
from .tool_manager import ToolManager, ToolStatus
from .conversation_manager import ConversationManager
from .workflow import create_agent_workflow, ResponseGenerator




class AdvancedRAGAgent(BaseAgent):
    """
    高级RAG Agent
    
    使用LangGraph构建的完整Agent系统，具备：
    - 多层意图识别
    - 混合实体提取
    - 智能任务规划
    - 健壮的工具调用
    - 多轮对话管理
    - 全面异常处理
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("AdvancedRAGAgent", config)
        
        # 初始化各模块
        self._init_modules()
        
        # 构建工作流
        self._build_workflow()
        
        # 工具实现注入标记
        self._tools_injected = False
        logger.info(f"[AdvancedRAGAgent] 初始化完成")

    
    def _init_modules(self):
        """初始化各功能模块"""
        # LLM
        self.llm = ChatOpenAI(
            model=self.config.get("model", settings.DEFAULT_MODEL),
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
            temperature=self.config.get("temperature", 0.7),
        )
        
        # 意图分类器
        self.intent_classifier = IntentClassifier(config=self.config.get("intent", {}))
        
        # 实体提取器
        self.entity_extractor = EntityExtractor(config=self.config.get("entity", {}))
        
        # 任务规划器
        self.task_planner = TaskPlanner(config=self.config.get("planner", {}))
        
        # 工具管理器
        self.tool_manager = ToolManager(
            default_timeout=self.config.get("tool_timeout", 30.0),
            max_retries=self.config.get("max_retries", 2),
        )
        
        # 注册内置工具
        self._register_builtin_tools()
        
        # 对话管理器
        self.conversation_manager = ConversationManager(
            max_history=self.config.get("max_history", 10),
            context_window=self.config.get("context_window", 5),
        )
        
        # 响应生成器
        self.response_generator = ResponseGenerator(self.llm)
    
    def _build_workflow(self):
        """构建LangGraph工作流"""
        logger.info(f"[AdvancedRAGAgent] 构建工作流")
        self.workflow = create_agent_workflow(
            intent_classifier=self.intent_classifier,
            entity_extractor=self.entity_extractor,
            task_planner=self.task_planner,
            tool_manager=self.tool_manager,
            conversation_manager=self.conversation_manager,
            response_generator=self.response_generator,
        )
    
    def _setup_tools(self):
        """设置工具（实际实现通过inject_tools注入）"""
        logger.info(f"[AdvancedRAGAgent] 设置工具")
        pass
    
    def _register_builtin_tools(self):
        """注册内置工具"""
        # 注册clarify工具
        async def clarify_tool(question, options=None, **kwargs):
            """请求用户澄清"""
            logger.info(f"[clarify_tool] 请求澄清: {question}")
            return f"需要用户澄清: {question}"
        
        # 注册generate_answer工具
        async def generate_answer_tool(context="", question="", **kwargs):
            """基于上下文生成最终回答"""
            logger.info(f"[generate_answer_tool] 生成回答: {question}")
            # 使用ResponseGenerator生成回答
            ctx = {
                "query": question,
                "intent": "unknown",
                "entities": [],
                "task_results": {},
                "chat_history": []
            }
            if context:
                ctx["task_results"]["context"] = context
            
            response = await self.response_generator.generate(ctx)
            return response
        
        # 注册 analyze 工具（默认实现，可通过 inject_analyze 覆盖）
        async def analyze_tool(content="", analysis_type="", **kwargs):
            """深度分析内容"""
            logger.info(f"[analyze_tool] 分析: {analysis_type}")
            if not content:
                return "无内容可分析"
            prompt = f"请对以下内容进行{analysis_type or '深度'}分析：\n\n{content}"
            response = await self.llm.ainvoke(prompt)
            return response.content

        # 注册 summarize 工具（默认实现，可通过 inject_summarize 覆盖）
        async def summarize_tool(content="", max_length=500, **kwargs):
            """总结内容"""
            logger.info(f"[summarize_tool] 总结, max_length={max_length}")
            if not content:
                return "无内容可总结"
            prompt = f"请将以下内容总结为不超过{max_length}字：\n\n{content}"
            response = await self.llm.ainvoke(prompt)
            return response.content

        # 注册 knowledge_retrieval 工具（占位实现，需通过 inject_retriever 注入真实实现）
        async def knowledge_retrieval_tool(query="", top_k=5, entities=None, **kwargs):
            """从知识库检索相关信息（占位，需注入实际实现）"""
            logger.warning("[knowledge_retrieval_tool] 未注入实际检索实现，返回空结果")
            return {"results": [], "message": "检索工具未配置，请先注入检索实现"}

        # 注册工具
        self.tool_manager.register_tool(
            "clarify",
            "请求用户澄清",
            clarify_tool,
            {"question": "澄清问题", "options": "可选答案"}
        )

        self.tool_manager.register_tool(
            "generate_answer",
            "基于上下文生成最终回答",
            generate_answer_tool,
            {"context": "上下文信息", "question": "用户问题"}
        )

        self.tool_manager.register_tool(
            "analyze",
            "深度分析内容",
            analyze_tool,
            {"content": "需要分析的内容", "analysis_type": "分析类型"}
        )

        self.tool_manager.register_tool(
            "summarize",
            "总结内容",
            summarize_tool,
            {"content": "需要总结的内容", "max_length": "最大长度"}
        )

        self.tool_manager.register_tool(
            "knowledge_retrieval",
            "从知识库检索相关信息",
            knowledge_retrieval_tool,
            {"query": "检索查询", "top_k": "返回结果数量", "entities": "实体列表"}
        )

        logger.info("[AdvancedRAGAgent] 注册内置工具完成")
    
    def inject_retriever(self, retriever_func: Callable):
        """
        注入检索工具实现
        
        Args:
            retriever_func: 检索函数，接收query等参数返回结果
        """
        logger.info(f"[AdvancedRAGAgent] 注入检索工具: knowledge_retrieval")
        self.tool_manager.inject_tool_impl("knowledge_retrieval", retriever_func)
        self._tools_injected = True
    
    def inject_search(self, search_func: Callable):
        """注入文档搜索工具实现"""
        self.tool_manager.inject_tool_impl("document_search", search_func)
    
    def inject_summarize(self, summarize_func: Callable):
        """注入总结工具实现"""
        logger.info(f"[AdvancedRAGAgent] 注入总结工具: summarize")
        self.tool_manager.inject_tool_impl("summarize", summarize_func)
    
    def inject_compare(self, compare_func: Callable):
        """注入对比工具实现"""
        logger.info(f"[AdvancedRAGAgent] 注入对比工具: compare")
        self.tool_manager.inject_tool_impl("compare", compare_func)
    
    def inject_analyze(self, analyze_func: Callable):
        """注入分析工具实现"""
        logger.info(f"[AdvancedRAGAgent] 注入分析工具: analyze")
        self.tool_manager.inject_tool_impl("analyze", analyze_func)
    
    def inject_custom_tool(self, name: str, func: Callable, description: str = "",
                          parameters: Optional[Dict] = None):
        """注入自定义工具"""
        logger.info(f"[AdvancedRAGAgent] 注入自定义工具: {name}")
        self.tool_manager.register_tool(name, description or name, func, parameters)
    
    async def process(self, query: str, session_id: Optional[str] = None,
                     **kwargs) -> AgentResponse:
        """
        处理用户查询
        
        Args:
            query: 用户查询
            session_id: 会话ID（可选，自动创建）
            **kwargs: 额外参数
            
        Returns:
            AgentResponse: Agent响应
        """
        logger.info(f"[AdvancedRAGAgent] 处理查询")
        start_time = time.time()
        
        # 生成会话ID
        if not session_id:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
        
        # 检查是否为追问
        is_follow_up = self.conversation_manager.is_follow_up_question(session_id, query)
        
        # 追问处理：添加上下文
        if is_follow_up:
            context = self.conversation_manager.get_context(session_id)
            # 追问可能需要澄清或补充
            if not query.strip().endswith(("？", "?", "。", ".")):
                query = query + "？"
        
        try:
            # 构建初始状态
            initial_state = {
                "query": query,
                "session_id": session_id,
                "intent": None,
                "entities": [],
                "subtasks": [],
                "current_task_index": 0,
                "task_results": {},
                "response": "",
                "final_answer": "",
                "error": None,
                "metadata": {
                    "is_follow_up": is_follow_up,
                    "start_time": datetime.now(),
                },
                "start_time": datetime.now(),
            }
            
            # 执行工作流
            result = await self.workflow.ainvoke(initial_state)
            
            processing_time = time.time() - start_time
            
            # 构建响应，提取检索文档数
            # 从工作流状态中获取检索到的文档数量
            sources_count = 0
            # 尝试从 metadata 或子任务中提取检索数量
            meta = result.get("metadata") or {}
            if isinstance(meta, dict):
                sources_count = meta.get("retrieved_count", 0) or 0
            # 如果 metadata 没有记录，尝试从 subtasks 中统计 knowledge_retrieval 结果
            if sources_count == 0:
                for st in result.get("subtasks", []):
                    tr = result.get("task_results", {}).get(st.id)
                    if tr and isinstance(tr, list):
                        sources_count = len(tr)
                        break

            return AgentResponse(
                content=result.get("final_answer", "抱歉，处理失败。"),
                intent=result.get("intent"),
                entities=result.get("entities", []),
                subtasks=result.get("subtasks", []),
                tool_calls=[
                    {"task_id": t.id, "tool": t.tool_name, "status": t.status.value}
                    for t in result.get("subtasks", [])
                ],
                metadata={
                    "session_id": session_id,
                    "is_follow_up": is_follow_up,
                    "error": result.get("error"),
                    "sources_count": sources_count,
                    **result.get("metadata", {}),
                },
                processing_time=processing_time,
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"[AdvancedRAGAgent] 处理查询时出错: {str(e)}")
            
            return AgentResponse(
                content=f"抱歉，系统处理时出错: {str(e)}",
                metadata={
                    "session_id": session_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                processing_time=processing_time,
            )
    
    async def process_stream(self, query: str, session_id: Optional[str] = None):
        """
        流式处理（模拟）
        
        由于LangGraph的限制，这里模拟流式输出
        """
        logger.info(f"[AdvancedRAGAgent] 流式处理")

        response = await self.process(query, session_id)
        
        # 模拟流式输出
        content = response.content
        chunk_size = 10  # 每10个字符输出一次
        
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i+chunk_size]
            yield {
                "chunk": chunk,
                "done": i + chunk_size >= len(content),
            }
    
    def get_session_history(self, session_id: str) -> List[Dict]:
        """获取会话历史"""
        logger.info(f"[AdvancedRAGAgent] 获取会话历史: {session_id}")
        return self.conversation_manager.get_session_history(session_id)
    
    def clear_session(self, session_id: str):
        """清空会话"""
        logger.info(f"[AdvancedRAGAgent] 清空会话: {session_id}")
        self.conversation_manager.clear_session(session_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取Agent统计信息"""
        logger.info(f"[AdvancedRAGAgent] 获取统计信息")

        return {
            "conversation": self.conversation_manager.get_stats(),
            "tools": self.tool_manager.get_tool_stats(),
        }
    
    def analyze_query(self, query: str) -> Dict[str, Any]:
        """
        分析查询（不执行，仅返回分析结果）
        
        用于调试和理解Agent的工作过程
        """
        logger.info(f"[AdvancedRAGAgent] 分析查询: {query}")
        # 快速意图识别
        quick_intent = self.intent_classifier.quick_classify(query)
        
        # 实体提取（仅规则）
        entities = self.entity_extractor._extract_by_rules(query)
        
        return {
            "query": query,
            "quick_intent": quick_intent.value,
            "entities": [
                {"name": e.name, "type": e.type, "confidence": e.confidence}
                for e in entities
            ],
        }


# 测试
if __name__ == "__main__":
    import asyncio
    
    async def test():
        # 启用LLM，测试完整功能
        agent = AdvancedRAGAgent(config={"use_llm": True})
        
        # 注入模拟检索工具
        def mock_retriever(query, top_k=5, **kwargs):
            return [
                {"content": f"关于'{query}'的检索结果1", "score": 0.95},
                {"content": f"关于'{query}'的检索结果2", "score": 0.87},
            ]
        
        agent.inject_retriever(mock_retriever)
        
        # 测试处理
        print("\n" + "=" * 50)
        print("完整处理测试")
        print("=" * 50)
        
        test_queries = [
            "你好",
            "什么是RAG技术？",
            "对比一下RAG和Fine-tuning",
        ]
        
        for query in test_queries:
            print(f"\n查询: {query}")
            
            # 测试任务规划
            # print("任务规划测试:")
            # analysis = agent.analyze_query(query)
            # quick_intent = analysis["quick_intent"]
            # entities = analysis["entities"]
            
            # 处理查询
            response = await agent.process(query)
            print(f"回答: {response.content[:100]}...")
            print(f"处理时间: {response.processing_time:.2f}s")
    
    asyncio.run(test())
