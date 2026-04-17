"""
LangGraph工作流定义

定义Agent的状态图和执行流程
"""
from typing import Dict, List, Any, Optional, TypedDict, Annotated
from datetime import datetime
import operator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

import sys
import os

# 添加backend/agent目录到搜索路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# 直接导入base模块
from base import Intent, Entity, SubTask, TaskStatus, AgentMessage
from config import init_logger
logger = init_logger(__name__)

class AgentStateDict(TypedDict):
    """Agent状态定义"""
    # 输入
    query: str
    session_id: str
    
    # 中间状态
    intent: Optional[Intent]
    entities: List[Entity]
    subtasks: List[SubTask]
    current_task_index: int
    task_results: Dict[str, Any]
    
    # 输出
    response: str
    final_answer: str
    
    # 元数据
    error: Optional[str]
    metadata: Dict[str, Any]
    start_time: datetime


def create_agent_workflow(intent_classifier, entity_extractor, task_planner, 
                          tool_manager, conversation_manager, response_generator):
    """
    创建Agent工作流
    
    状态图结构：
    START -> classify_intent -> extract_entities -> plan_tasks -> execute_tasks -> generate_response -> END
                              ↓
                         handle_error (异常分支)
    """
    
    # 定义节点函数
    async def classify_intent(state: AgentStateDict) -> AgentStateDict:
        """意图识别节点"""
        try:
            logger.info(f"[workflow] 意图识别: {state['query']}")
            intent = await intent_classifier.classify(
                state["query"],
                conversation_manager.get_session_history(state["session_id"])
            )
            state["intent"] = intent
            state["metadata"]["intent_confidence"] = intent.confidence
            return state
        except Exception as e:
            logger.error(f"[workflow] 意图识别失败: {str(e)}")
            state["error"] = f"Intent classification failed: {str(e)}"
            return state
    
    async def extract_entities(state: AgentStateDict) -> AgentStateDict:
        """实体提取节点"""
        logger.info(f"[workflow] 实体提取: {state['query']}")
        if state.get("error"):
            return state
        
        try:
            context = conversation_manager.get_context_value(state["session_id"], "knowledge_base")
            entities = await entity_extractor.extract(
                state["query"],
                context={"knowledge_base": context} if context else None
            )
            state["entities"] = entities
            return state
        except Exception as e:
            logger.error(f"[workflow] 实体提取失败: {str(e)}")
            state["error"] = f"Entity extraction failed: {str(e)}"
            return state
    
    async def plan_tasks(state: AgentStateDict) -> AgentStateDict:
        """任务规划节点"""
        logger.info(f"[workflow] 任务规划: {state['query']}")
        if state.get("error"):
            return state
        
        try:
            entities_dict = [
                {"name": e.name, "type": e.type, "value": e.value}
                for e in state["entities"]
            ]
            subtasks = await task_planner.plan(
                state["intent"],
                state["query"],
                entities_dict
            )
            
            # 输出任务规划信息
            print("任务规划:")
            print(f"规划了 {len(subtasks)} 个子任务:")
            for task in subtasks:
                deps = f" [依赖: {', '.join(task.dependencies)}]" if task.dependencies else ""
                print(f"  - {task.id}: {task.description} (工具: {task.tool_name}){deps}")
            
            # 优化执行顺序并输出
            parallel_groups = task_planner.optimize_execution_order(subtasks)
            print(f"并行执行组: {parallel_groups}")
            
            state["subtasks"] = subtasks
            state["current_task_index"] = 0
            return state
        except Exception as e:
            logger.error(f"[workflow] 任务规划失败: {str(e)}")
            state["error"] = f"Task planning failed: {str(e)}"
            return state
    
    async def execute_tasks(state: AgentStateDict) -> AgentStateDict:
        """任务执行节点"""
        logger.info(f"[workflow] 任务执行: {state['query']}")
        if state.get("error"):
            return state
        
        subtasks = state["subtasks"]
        results = {}
        
        # 优化执行顺序
        parallel_groups = task_planner.optimize_execution_order(subtasks)
        
        for group in parallel_groups:
            # 准备当前组的所有任务
            tool_calls = []
            for task_id in group:
                task = next((t for t in subtasks if t.id == task_id), None)
                if task and task.tool_name:
                    # 准备参数
                    params = task.parameters.copy()
                    
                    # 注入依赖任务的结果
                    for dep_id in task.dependencies:
                        if dep_id in results:
                            if "context" not in params:
                                params["context"] = ""
                            # 确保context是字符串类型
                            if not isinstance(params["context"], str):
                                params["context"] = str(params["context"])
                            # 确保结果是字符串类型
                            result_value = results[dep_id]
                            if isinstance(result_value, dict):
                                # 如果是字典，转换为字符串
                                result_str = str(result_value)
                            else:
                                result_str = str(result_value)
                            params["context"] += f"\n[{dep_id}]: {result_str}"
                    
                    # 注入实体信息
                    if state["entities"]:
                        entity_names = [e.name for e in state["entities"]]
                        if "entities" not in params:
                            params["entities"] = entity_names
                    
                    tool_calls.append({
                        "tool_name": task.tool_name,
                        "params": params,
                    })
            
            # 并行执行
            batch_results = await tool_manager.execute_batch(tool_calls, parallel=True)
            
            # 记录结果
            for task_id, result in zip(group, batch_results):
                task = next((t for t in subtasks if t.id == task_id), None)
                if task:
                    task.status = TaskStatus.COMPLETED if result.status.value == "success" else TaskStatus.FAILED
                    task.result = result.data
                    task.error = result.error
                    results[task_id] = result.data if result.status.value == "success" else result.error
        
        state["task_results"] = results
        
        # 检查是否有任务失败
        failed_tasks = [t for t in subtasks if t.status == TaskStatus.FAILED]
        if failed_tasks:
            state["metadata"]["failed_tasks"] = [
                {"id": t.id, "error": t.error} for t in failed_tasks
            ]
        
        return state
    
    async def generate_response(state: AgentStateDict) -> AgentStateDict:
        """响应生成节点"""
        logger.info(f"[workflow] 响应生成: {state['query']}")
        
        try:
            # 收集上下文
            context = {
                "query": state["query"],
                "intent": state["intent"].type.value if state["intent"] else "unknown",
                "entities": [
                    {"name": e.name, "type": e.type} for e in state["entities"]
                ],
                "task_results": state.get("task_results", {}),
            }
            
            # 添加对话历史
            chat_history = conversation_manager.get_context(
                state["session_id"],
                window_size=3,
                include_summary=True
            )
            context["chat_history"] = chat_history.get("recent_turns", [])
            
            # 生成回答
            response = await response_generator.generate(context)
            state["final_answer"] = response
            
            # 记录对话
            conversation_manager.add_turn(
                session_id=state["session_id"],
                query=state["query"],
                response=response,
                intent=state["intent"].type.value if state["intent"] else None,
                entities=[{"name": e.name, "type": e.type} for e in state["entities"]],
                metadata=state["metadata"],
            )
            
            return state
            
        except Exception as e:
            logger.error(f"[workflow] 响应生成失败: {str(e)}")
            state["error"] = f"Response generation failed: {str(e)}"
            return state
    
    def handle_error(state: AgentStateDict) -> AgentStateDict:
        """错误处理节点"""
        logger.error(f"[workflow] 错误处理: {state['query']}")
        error_msg = state.get("error", "Unknown error")
        
        # 根据错误类型生成友好的错误消息
        if "timeout" in error_msg.lower():
            state["final_answer"] = "抱歉，处理您的请求超时了。请稍后再试，或者简化您的问题。"
        elif "not found" in error_msg.lower():
            state["final_answer"] = "抱歉，我找不到相关的信息。您可以尝试用不同的方式描述您的问题。"
        else:
            state["final_answer"] = f"抱歉，处理您的请求时出现了问题。请稍后再试。"
        
        state["metadata"]["error_details"] = error_msg
        return state
    
    def should_continue(state: AgentStateDict) -> str:
        """决定下一步"""
        logger.info(f"[workflow] 决定下一步: {state['query']}")
        if state.get("error"):
            return "error"
        return "continue"
    
    # 构建状态图
    workflow = StateGraph(AgentStateDict)
    
    # 添加节点
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("extract_entities", extract_entities)
    workflow.add_node("plan_tasks", plan_tasks)
    workflow.add_node("execute_tasks", execute_tasks)
    workflow.add_node("generate_response", generate_response)
    workflow.add_node("handle_error", handle_error)
    
    # 添加边
    workflow.set_entry_point("classify_intent")
    
    workflow.add_conditional_edges(
        "classify_intent",
        should_continue,
        {
            "continue": "extract_entities",
            "error": "handle_error",
        }
    )
    
    workflow.add_conditional_edges(
        "extract_entities",
        should_continue,
        {
            "continue": "plan_tasks",
            "error": "handle_error",
        }
    )
    
    workflow.add_conditional_edges(
        "plan_tasks",
        should_continue,
        {
            "continue": "execute_tasks",
            "error": "handle_error",
        }
    )
    
    workflow.add_conditional_edges(
        "execute_tasks",
        should_continue,
        {
            "continue": "generate_response",
            "error": "handle_error",
        }
    )
    
    workflow.add_edge("generate_response", END)
    workflow.add_edge("handle_error", END)
    
    logger.info(f"[workflow] 工作流编译完成")

    # 编译工作流
    return workflow.compile()


class ResponseGenerator:
    """响应生成器"""
    
    def __init__(self, llm):
        self.llm = llm
        logger.info(f"[ResponseGenerator] 初始化完成，LLM: {llm}")
    
    async def generate(self, context: Dict[str, Any]) -> str:
        """基于上下文生成回答"""
        logger.info(f"[ResponseGenerator] 生成回答: {context}")
        from langchain_core.prompts import ChatPromptTemplate
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的RAG知识库助手。基于提供的信息回答用户问题。

要求：
1. 回答要准确、简洁、有帮助
2. 如果信息不足，明确告知用户
3. 引用来源信息时要清晰
4. 保持专业和友好的语气"""),
            ("human", """用户问题: {query}
识别意图: {intent}
相关实体: {entities}
检索结果: {task_results}
对话历史: {chat_history}

请生成回答：""")
        ])
        
        chain = prompt | self.llm
        
        response = await chain.ainvoke(context)
        return response.content
