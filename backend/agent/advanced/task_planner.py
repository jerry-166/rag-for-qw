"""
任务规划模块

将复杂查询拆解为可执行的子任务序列，支持：
- 任务分解与依赖分析
- 执行顺序规划
- 并行任务识别
- 动态任务调整
"""
import json
import uuid
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

import sys
import os

# 添加backend/agent目录到搜索路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from config import settings, init_logger
logger = init_logger(__name__)
# 直接导入base模块
from base import SubTask, TaskStatus, Intent, IntentType


class TaskPlanOutput(BaseModel):
    """任务规划输出结构"""
    tasks: List[Dict[str, Any]] = Field(
        ...,
        description="子任务列表，每个任务包含id, description, tool_name, parameters, dependencies"
    )
    reasoning: str = Field(..., description="任务分解的推理过程")
    parallel_groups: List[List[str]] = Field(
        default=[],
        description="可以并行执行的task id组"
    )


class TaskPlanner:
    """
    任务规划器
    
    将用户意图和查询分解为可执行的子任务序列
    """
    
    # 工具定义
    AVAILABLE_TOOLS = {
        "knowledge_retrieval": {
            "description": "从知识库检索相关信息",
            "parameters": {
                "query": "检索查询",
                "knowledge_base": "知识库名称（可选）",
                "top_k": "返回结果数量（默认5）",
            },
        },
        # todo: 文档搜索工具
        "document_search": {
            "description": "搜索特定文档",
            "parameters": {
                "doc_name": "文档名称",
                "keywords": "搜索关键词",
            },
        },
        "summarize": {
            "description": "总结内容",
            "parameters": {
                "content": "需要总结的内容",
                "max_length": "最大长度",
            },
        },
        "compare": {
            "description": "对比两个或多个事物",
            "parameters": {
                "items": "要对比的项目列表",
                "aspects": "对比维度",
            },
        },
        "analyze": {
            "description": "深度分析内容",
            "parameters": {
                "content": "需要分析的内容",
                "analysis_type": "分析类型（如：原因分析、可行性分析等）",
            },
        },
        "generate_answer": {
            "description": "基于上下文生成最终回答",
            "parameters": {
                "context": "上下文信息",
                "question": "用户问题",
            },
        },
        "clarify": {
            "description": "请求用户澄清",
            "parameters": {
                "question": "澄清问题",
                "options": "可选答案",
            },
        },
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.use_llm = self.config.get("use_llm", True)
        
        # 初始化_static_prompt_parts属性
        self._static_prompt_parts = {}
        
        if self.use_llm:
            self.llm = ChatOpenAI(
                model=self.config.get("model", settings.DEFAULT_MODEL),
                base_url=settings.LITELLM_BASE_URL,
                api_key=settings.LITELLM_API_KEY,
                temperature=0.2,
            )
            self._build_chain()
        else:
            self.llm = None
            self.chain = None
        
        logger.info("任务规划器初始化完成")
    
    def _build_chain(self):
        """构建任务规划Chain"""
        
        tools_desc = "\n".join([
            f"- {name}: {info['description']}\n  参数: {', '.join(info['parameters'].keys())}"
            for name, info in self.AVAILABLE_TOOLS.items()
        ])
        
        system_prompt = f"""你是一个任务规划专家。请将用户的查询分解为可执行的子任务序列。

可用工具：
{tools_desc}

请按以下JSON格式输出：
{{
    "tasks": [
        {{
            "id": "task_1",
            "description": "任务描述",
            "tool_name": "使用的工具名称",
            "parameters": {{}},
            "dependencies": []  # 依赖的其他任务id
        }}
    ],
    "reasoning": "任务分解的推理过程",
    "parallel_groups": [["task_1", "task_2"]]  # 可以并行执行的任务组
}}

规划原则：
1. 将复杂任务分解为2-5个子任务
2. 明确任务间的依赖关系
3. 识别可以并行执行的任务
4. 最后一步通常是generate_answer生成最终回答
5. 如果信息不足，使用clarify工具请求用户澄清
"""
        
        # 构建完整提示（不使用任何模板系统，避免大括号解析问题）
        from langchain_core.messages import HumanMessage
        
        # 存储静态的系统提示部分（不包含任何大括号变量）
        self._static_prompt_parts = {
            "tools_desc": tools_desc,
            "system_prompt": system_prompt,
        }
    
    async def plan(self, intent: Intent, query: str, entities: List[Dict]) -> List[SubTask]:
        """
        规划任务
        
        Args:
            intent: 识别出的意图
            query: 用户查询
            entities: 提取的实体
            
        Returns:
            List[SubTask]: 子任务列表
        """
        logger.info(f"[TaskPlanner] 开始规划任务，意图类型: {intent.type.value}")
        # 根据意图类型选择规划策略
        if intent.type == IntentType.GREETING:
            return self._plan_greeting()
        elif intent.type == IntentType.CLARIFICATION:
            return self._plan_clarification(query)
        elif intent.confidence < 0.5:
            # 低置信度时请求澄清
            return self._plan_clarification(query, low_confidence=True)
        
        # 使用LLM规划复杂任务
        try:
            logger.info(f"[TaskPlanner] 开始使用LLM规划任务")
            return await self._plan_with_llm(intent, query, entities)
        except Exception as e:
            # LLM规划失败时使用备用策略
            logger.error(f"[TaskPlanner] LLLM任务规划失败: {e}")
            return self._plan_fallback(intent, query, entities)
    
    async def _plan_with_llm(self, intent: Intent, query: str, entities: List[Dict]) -> List[SubTask]:
        """使用LLM规划任务"""

        # 检查LLM是否可用
        if not self.llm:
            logger.error("LLM not available")
            raise Exception("LLM not available")
        
        # 检查_static_prompt_parts是否包含system_prompt
        if 'system_prompt' not in self._static_prompt_parts:
            raise Exception("System prompt not initialized")
        
        # 格式化输入
        intent_str = f"{intent.type.value} (置信度: {intent.confidence:.2f})"
        entities_str = json.dumps([{"name": e.get("name"), "type": e.get("type")} for e in entities], ensure_ascii=False)
        
        # 手动构建完整提示
        full_prompt = f"""{self._static_prompt_parts['system_prompt']}

用户意图: {intent_str}
用户查询: {query}
提取的实体: {entities_str}

请规划任务序列："""
        
        # 直接调用LLM
        from langchain_core.messages import HumanMessage
        response = await self.llm.ainvoke([HumanMessage(content=full_prompt)])
        
        # 解析JSON
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        result = json.loads(content.strip())
        
        # 构建SubTask列表
        subtasks = []
        for task_data in result.get("tasks", []):
            # 处理knowledge_retrieval工具，移除不存在的知识库名称
            parameters = task_data.get("parameters", {})
            if task_data.get("tool_name") == "knowledge_retrieval":
                # 移除knowledge_base参数，因为系统可能没有这个知识库
                if "knowledge_base" in parameters:
                    del parameters["knowledge_base"]
                    logger.warning("[TaskPlanner] 移除了不存在的知识库参数")
            
            subtasks.append(SubTask(
                id=task_data.get("id", f"task_{uuid.uuid4().hex[:8]}"),
                description=task_data.get("description", ""),
                tool_name=task_data.get("tool_name"),
                parameters=parameters,
                dependencies=task_data.get("dependencies", []),
                status=TaskStatus.PENDING,
            ))
        
        logger.info(f"[TaskPlanner] LLM规划任务成功，任务数量: {len(subtasks)}")
        return subtasks
    
    def _plan_fallback(self, intent: Intent, query: str, entities: List[Dict]) -> List[SubTask]:
        """备用规划策略（基于规则的简单规划）"""
        subtasks = []
        logger.info(f"[TaskPlanner] 开始使用备用规划策略，意图类型: {intent.type.value}")
        
        # 根据意图类型生成默认任务序列
        if intent.type == IntentType.RETRIEVAL:
            subtasks = [
                SubTask(
                    id="task_1",
                    description="从知识库检索相关信息",
                    tool_name="knowledge_retrieval",
                    parameters={"query": query, "top_k": 5},
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_2",
                    description="基于检索结果生成回答",
                    tool_name="generate_answer",
                    parameters={"question": query},
                    dependencies=["task_1"],
                    status=TaskStatus.PENDING,
                ),
            ]
        
        elif intent.type == IntentType.SUMMARIZATION:
            subtasks = [
                SubTask(
                    id="task_1",
                    description="检索需要总结的内容",
                    tool_name="knowledge_retrieval",
                    parameters={"query": query, "top_k": 10},
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_2",
                    description="总结检索到的内容",
                    tool_name="summarize",
                    parameters={},
                    dependencies=["task_1"],
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_3",
                    description="生成最终回答",
                    tool_name="generate_answer",
                    parameters={"question": query},
                    dependencies=["task_2"],
                    status=TaskStatus.PENDING,
                ),
            ]
        
        elif intent.type == IntentType.COMPARISON:
            # 从实体中提取对比项
            items = [e.get("name", "") for e in entities if e.get("type") in ["TECHNOLOGY", "CONCEPT", "DOCUMENT"]]
            
            subtasks = [
                SubTask(
                    id="task_1",
                    description=f"检索{item}的相关信息" if (item := items[0] if items else "第一个对比项") else "检索第一个对比项",
                    tool_name="knowledge_retrieval",
                    parameters={"query": items[0] if items else query, "top_k": 3},
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_2",
                    description=f"检索{item}的相关信息" if (item := items[1] if len(items) > 1 else "第二个对比项") else "检索第二个对比项",
                    tool_name="knowledge_retrieval",
                    parameters={"query": items[1] if len(items) > 1 else query, "top_k": 3},
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_3",
                    description="对比分析检索结果",
                    tool_name="compare",
                    parameters={"items": items if items else []},
                    dependencies=["task_1", "task_2"],
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_4",
                    description="生成对比报告",
                    tool_name="generate_answer",
                    parameters={"question": query},
                    dependencies=["task_3"],
                    status=TaskStatus.PENDING,
                ),
            ]
        
        elif intent.type == IntentType.ANALYSIS:
            subtasks = [
                SubTask(
                    id="task_1",
                    description="收集分析所需的背景信息",
                    tool_name="knowledge_retrieval",
                    parameters={"query": query, "top_k": 8},
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_2",
                    description="深度分析收集的信息",
                    tool_name="analyze",
                    parameters={"analysis_type": "综合分析"},
                    dependencies=["task_1"],
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_3",
                    description="生成分析报告",
                    tool_name="generate_answer",
                    parameters={"question": query},
                    dependencies=["task_2"],
                    status=TaskStatus.PENDING,
                ),
            ]
        
        else:
            # 默认任务序列
            subtasks = [
                SubTask(
                    id="task_1",
                    description="检索相关知识",
                    tool_name="knowledge_retrieval",
                    parameters={"query": query, "top_k": 5},
                    status=TaskStatus.PENDING,
                ),
                SubTask(
                    id="task_2",
                    description="生成回答",
                    tool_name="generate_answer",
                    parameters={"question": query},
                    dependencies=["task_1"],
                    status=TaskStatus.PENDING,
                ),
            ]
        
        logger.info(f"[TaskPlanner] 备用规划任务成功，任务数量: {len(subtasks)}")
        return subtasks
    
    def _plan_greeting(self) -> List[SubTask]:
        """规划问候任务"""
        logger.info(f"[TaskPlanner] 开始规划问候任务")
        return [
            SubTask(
                id="task_greeting",
                description="回复问候",
                tool_name="generate_answer",
                parameters={"question": "你好"},
                status=TaskStatus.PENDING,
            ),
        ]
    
    def _plan_clarification(self, query: str, low_confidence: bool = False) -> List[SubTask]:
        """规划澄清任务"""
        logger.info(f"[TaskPlanner] 开始规划澄清任务，意图类型: {intent.type.value}")
        if low_confidence:
            question = f"我不太确定您的意图，您是想了解关于'{query}'的什么信息呢？"
        else:
            question = "我需要更多信息来回答您的问题，能否详细说明一下您的需求？"
        
        return [
            SubTask(
                id="task_clarify",
                description="请求用户澄清",
                tool_name="clarify",
                parameters={"question": question},
                status=TaskStatus.PENDING,
            ),
        ]
    
    def optimize_execution_order(self, subtasks: List[SubTask]) -> List[List[str]]:
        """
        优化任务执行顺序，识别可并行任务
        
        Returns:
            List[List[str]]: 并行任务组，每组内部可以并行执行
        """
        logger.info(f"[TaskPlanner] 开始优化任务执行顺序，任务数量: {len(subtasks)}")
        # 构建依赖图
        task_map = {t.id: t for t in subtasks}
        completed = set()
        parallel_groups = []
        
        while len(completed) < len(subtasks):
            # 找出当前可执行的任务（依赖已完成）
            executable = []
            for task in subtasks:
                if task.id in completed:
                    continue
                if all(dep in completed for dep in task.dependencies):
                    executable.append(task.id)
            
            if not executable:
                # 存在循环依赖，按原顺序执行
                remaining = [t.id for t in subtasks if t.id not in completed]
                parallel_groups.append(remaining)
                break
            
            parallel_groups.append(executable)
            completed.update(executable)
        
        logger.info(f"[TaskPlanner] 任务执行顺序优化完成，并行任务组数量: {len(parallel_groups)}")
        return parallel_groups


# 测试
if __name__ == "__main__":
    async def test():
        # 禁用LLM，只测试导入和基本功能
        planner = TaskPlanner(config={"use_llm": True})
        
        # 模拟意图和实体
        class MockIntent:
            def __init__(self, type, confidence=0.9):
                self.type = type
                self.confidence = confidence
                self.metadata = {}
        
        test_cases = [
            {
                "intent": MockIntent(IntentType.RETRIEVAL),
                "query": "什么是RAG技术？",
                "entities": [{"name": "RAG", "type": "CONCEPT"}],
            },
            {
                "intent": MockIntent(IntentType.COMPARISON),
                "query": "对比一下LangChain和LlamaIndex",
                "entities": [
                    {"name": "LangChain", "type": "TECHNOLOGY"},
                    {"name": "LlamaIndex", "type": "TECHNOLOGY"},
                ],
            },
        ]
        
        for case in test_cases:
            print(f"\n查询: {case['query']}")
            subtasks = await planner.plan(case["intent"], case["query"], case["entities"])
            print(f"规划了 {len(subtasks)} 个子任务:")
            for task in subtasks:
                deps = f" [依赖: {', '.join(task.dependencies)}]" if task.dependencies else ""
                print(f"  - {task.id}: {task.description} (工具: {task.tool_name}){deps}")
    
    import asyncio
    asyncio.run(test())
