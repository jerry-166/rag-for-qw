"""
RAG Agent LangGraph 工作流（重构版）

融合 mini-openclew 的设计风格：
- SSE 友好的节点事件发射（通过 state["events"] 传递）
- 完整的 RAG 专属节点链路
- 每个节点职责单一、边界清晰

工作流结构：
  START
    → classify_intent         意图分类（规则优先，LLM 兜底）
    → query_expansion         查询扩展（生成子问题）
    → hybrid_retrieval        混合检索（Milvus + ES 并行）
    → rerank                  精排（Cross-Encoder）
    → generate_response       LLM 生成回答 + 写入记忆日志
  END
    ↘ handle_error            任意节点失败均跳转此节点

特殊路径：
  greeting_intent → greeting_response（问候意图直接回答，跳过检索）
  classify_intent → clarification_response（澄清意图直接回答）
"""

import json
import asyncio
from typing import Dict, List, Any, Optional, TypedDict, Annotated
from datetime import datetime
import operator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import settings, init_logger
from agent.base import Intent, IntentType, SubTask, TaskStatus

logger = init_logger(__name__)


# State 定义
class RAGAgentState(TypedDict):
    """
    RAG Agent 全局状态

    SSE 事件通过 events 列表累积，每个节点 append 事件，
    流式输出层从 events 中消费并推送给客户端。
    """
    # ── 输入 ──────────────────────────────────────────────────
    query: str                          # 用户原始查询
    session_id: str                     # 会话 ID
    knowledge_base_id: Optional[int]    # 目标知识库 ID（可选）

    # ── 中间状态 ──────────────────────────────────────────────
    intent: Optional[Intent]            # 意图识别结果
    expanded_queries: List[str]         # 扩展后的子查询列表
    raw_results: List[Dict[str, Any]]   # 混合检索原始结果
    reranked_results: List[Dict[str, Any]]  # 精排后的结果
    context_text: str                   # 拼接的检索上下文

    # ── 输出 ──────────────────────────────────────────────────
    final_answer: str                   # 最终回答
    
    # ── SSE 事件流 ────────────────────────────────────────────
    events: List[Dict[str, Any]]        # 累积的 SSE 事件列表

    # ── 元数据 ────────────────────────────────────────────────
    error: Optional[str]
    metadata: Dict[str, Any]
    start_time: str


# 工作流构建函数
def create_rag_workflow(memory_manager=None, session_store=None):
    """
    构建 RAG Agent LangGraph 工作流

    Args:
        memory_manager: MemoryManager 实例（用于 System Prompt 拼接和记忆写入）
        session_store: SessionStore 实例（用于会话历史读写）

    Returns:
        编译后的 LangGraph 工作流
    """

    # 懒加载 LLM（避免循环导入）
    def _get_llm(temperature: float = 0.7) -> ChatOpenAI:
        return ChatOpenAI(
            model=settings.DEFAULT_MODEL,
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
            temperature=temperature,
        )

    def _emit_event(state: RAGAgentState, event_type: str, content: str, **kwargs) -> None:
        """向 state 追加 SSE 事件（供流式输出消费）"""
        event = {
            "type": event_type,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        state["events"].append(event)
        logger.debug(f"[SSE Event] {event_type}: {content[:80]}")



    # 节点 1: classify_intent
    async def classify_intent(state: RAGAgentState) -> RAGAgentState:
        """意图分类节点：使用规则优先 + LLM 兜底的混合策略"""
        _emit_event(state, "thinking", "正在分析您的查询意图...")

        try:
            from agent.advanced.intent_classifier import IntentClassifier
            classifier = IntentClassifier()

            logger.info(f"[rag_workflow] 开始意图分类，查询: {state['query']}")
            # 获取会话历史作为上下文
            chat_history = []
            if session_store:
                chat_history = session_store.get_messages(state["session_id"], limit=6)

            # 先做快速规则分类
            quick_intent = classifier.quick_classify(state["query"])

            # 问候类直接快速返回，不走 LLM
            if quick_intent == IntentType.GREETING:
                logger.info(f"[rag_workflow] 快速分类为问候: {quick_intent}")
                state["intent"] = Intent(type=IntentType.GREETING, confidence=1.0)
                _emit_event(state, "intent_classified", f"意图识别：问候")
                return state

            # 其他意图走 LLM 精确分类
            intent = await classifier.classify(state["query"], chat_history)
            logger.info(f"[rag_workflow] LLM分类为: {intent.type.value}（置信度 {intent.confidence:.0%}）")
            state["intent"] = intent
            state["metadata"]["intent_confidence"] = intent.confidence

            _emit_event(
                state,
                "intent_classified",
                f"意图识别：{intent.type.value}（置信度 {intent.confidence:.0%}）",
                intent=intent.type.value,
                confidence=intent.confidence,
            )

        except Exception as e:
            logger.error(f"[rag_workflow] 意图分类失败: {e}")
            state["intent"] = Intent(type=IntentType.RETRIEVAL, confidence=0.5)
            state["metadata"]["intent_fallback"] = True
            _emit_event(state, "intent_classified", "意图识别：检索（降级）")

        return state

    # 节点 2: query_expansion
    async def query_expansion(state: RAGAgentState) -> RAGAgentState:
        """查询扩展节点：生成子问题以提升召回率"""
        _emit_event(state, "thinking", "正在扩展查询，生成子问题...")
        logger.info(f"[rag_workflow] 开始扩展查询，查询: {state['query']}")
        intent = state.get("intent")
        query = state["query"]

        # 简单查询或问候类跳过扩展
        if intent and intent.type in (IntentType.GREETING, IntentType.CLARIFICATION):
            logger.info(f"[rag_workflow] 意图分类为问候或澄清，跳过扩展")
            state["expanded_queries"] = [query]
            return state

        if len(query) < 10:
            logger.info(f"[rag_workflow] 查询长度小于 10，跳过扩展")
            state["expanded_queries"] = [query]
            return state

        try:
            # 使用 claw_agent 内部的查询扩展工具
            from agent.claw_agent.tools.rag_tools import rag_query_expand

            # 注意：tool 是同步的，用 asyncio.to_thread 包装
            result_json = await asyncio.to_thread(
                rag_query_expand.invoke,
                {
                    "query": query,
                    "num_subquestions": 2,
                    "context_hint": None,
                }
            )

            result = json.loads(result_json)
            subquestions = result.get("subquestions", [query])

            # 去重：原始查询 + 子问题
            all_queries = [query]
            for sq in subquestions:
                if sq and sq != query:
                    all_queries.append(sq)

            state["expanded_queries"] = all_queries[:3]  # 最多 3 路检索
            state["metadata"]["key_concepts"] = result.get("key_concepts", [])
            logger.info(f"[rag_workflow] 扩展查询完成")
            
            _emit_event(
                state,
                "query_expanded",
                f"查询扩展完成，共 {len(state['expanded_queries'])} 路检索",
                subquestions=state["expanded_queries"],
            )

        except Exception as e:
            logger.warning(f"[rag_workflow] 扩展查询失败，使用原始查询: {e}")
            state["expanded_queries"] = [query]

        return state

    # 节点 3: hybrid_retrieval
    async def hybrid_retrieval(state: RAGAgentState) -> RAGAgentState:
        """混合检索节点：对每路查询并行执行 Milvus + ES 混合检索"""
        _emit_event(state, "thinking", "正在从知识库检索相关文档...")
        logger.info(f"[rag_workflow] 开始从知识库检索相关文档，查询: {state['query']}")
        
        queries = state.get("expanded_queries", [state["query"]])
        knowledge_base_id = state.get("knowledge_base_id")

        all_results = []

        # 使用 claw_agent 内部的混合检索工具
        from agent.claw_agent.tools.rag_tools import rag_hybrid_search

        async def search_one(q: str):
            try:
                result_json = await asyncio.to_thread(
                    rag_hybrid_search.invoke,
                    {
                        "query": q,
                        "knowledge_base_id": knowledge_base_id,
                        "top_k": 8,
                        "use_vector": True,
                        "use_keyword": True,
                        "use_rerank": True,
                        "rerank_top_k": 5,
                    }
                )
                data = json.loads(result_json)
                return data.get("results", [])
            except Exception as e:
                logger.warning(f"检索失败（查询: {q[:30]}...）: {e}")
                return []

        # 并行检索所有子查询
        results_list = await asyncio.gather(*[search_one(q) for q in queries])

        # 合并结果（基于 chunk_text 去重）
        seen_keys = set()
        for results in results_list:
            for r in results:
                chunk_text = r.get("chunk_text", r.get("content", ""))
                key = chunk_text[:300]  # 基于 chunk 前300字符去重
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_results.append(r)

        state["raw_results"] = all_results
        state["metadata"]["retrieved_count"] = len(all_results)
        logger.info(f"[rag_workflow] 检索完成，共获得 {len(all_results)} 个候选文档片段（去重后）")

        _emit_event(
            state,
            "retrieved",
            f"检索完成，共获得 {len(all_results)} 个候选文档片段",
            count=len(all_results),
            # 附带检索结果详情（供前端展示来源）
            results=[
                {
                    "content": r.get("content", "")[:300],
                    "chunk_text": r.get("chunk_text", "")[:400],
                    "score": r.get("_similarity", r.get("score", 0)),
                    "source": r.get("source", "unknown"),
                    "type": r.get("type", ""),
                    "metadata": r.get("metadata", {}),
                }
                for r in all_results[:10]  # 最多传10条
            ],
        )

        return state

    # 节点 4: rerank
    async def rerank(state: RAGAgentState) -> RAGAgentState:
        """精排节点：使用 Cross-Encoder 对候选文档精排"""
        raw_results = state.get("raw_results", [])
        logger.info(f"[rag_workflow] 开始精排 {len(raw_results)} 个候选文档")

        if not raw_results:
            logger.info(f"[rag_workflow] 未检索到相关文档")
            state["reranked_results"] = []
            state["context_text"] = ""
            _emit_event(state, "reranked", "未检索到相关文档")
            return state

        _emit_event(state, "thinking", f"正在精排 {len(raw_results)} 个候选文档...")

        # 由于rag_hybrid_search已经包含了精排功能，这里直接使用检索结果
        # 只需要从检索结果中提取前5个即可
        try:
            # 从原始结果中获取前5个
            reranked = raw_results[:5]
            logger.info(f"精排完成，保留 {len(reranked)} 条结果")

        except Exception as e:
            logger.warning(f"[rag_workflow] 精排失败，使用原始结果: {e}")
            reranked = raw_results[:5]

        state["reranked_results"] = reranked
        state["metadata"]["sources_count"] = len(reranked)

        # 拼接上下文文本
        context_parts = []
        for i, r in enumerate(reranked, 1):
            content = r.get("content", r.get("chunk_text", ""))
            score = r.get("rerank_score", r.get("rrf_score", 0))
            source_type = r.get("type", "unknown")
            meta = r.get("metadata", {})
            doc_name = meta.get("filename", meta.get("document_id", f"文档{i}"))

            context_parts.append(
                f"[{i}] 来源：{doc_name}（{source_type}，相关度：{score:.3f}）\n{content}"
            )

        state["context_text"] = "\n\n".join(context_parts)

        _emit_event(
            state,
            "reranked",
            f"精排完成，选取最相关的 {len(reranked)} 条文档",
            count=len(reranked),
            # 附带精排结果详情（供前端展示最终来源）
            results=[
                {
                    "content": r.get("content", "")[:300],
                    "chunk_text": r.get("chunk_text", "")[:400],
                    "score": r.get("rerank_score", r.get("_similarity", r.get("rrf_score", 0))),
                    "source": r.get("source", "unknown"),
                    "type": r.get("type", ""),
                    "metadata": r.get("metadata", {}),
                }
                for r in reranked
            ],
        )
        logger.info(f"[rag_workflow] 精排完成，选取最相关的 {len(reranked)} 条文档")
        return state

    # 节点 5: generate_response
    async def generate_response(state: RAGAgentState) -> RAGAgentState:
        """生成回答节点：基于检索上下文用 LLM 生成最终答案，并写入记忆"""
        logger.info(f"[rag_workflow] 开始回答")
        _emit_event(state, "thinking", "正在基于检索结果生成回答...")

        llm = _get_llm(temperature=0.5)

        # 构建 System Prompt
        system_prompt = "你是一个专业的 RAG 知识库助手，请基于以下检索到的文档内容回答用户问题。\n\n"
        if memory_manager:
            session_context = ""
            if session_store:
                session_context = session_store.get_recent_context(state["session_id"], window=3)
            system_prompt = memory_manager.get_system_prompt(extra_context=session_context)

        context_text = state.get("context_text", "")
        query = state["query"]

        if context_text:
            user_message = f"""请基于以下检索到的文档回答问题。

## 检索到的相关文档
{context_text}

## 用户问题
{query}

请直接回答用户问题，引用来源，如果文档中没有相关信息请明确说明。"""
        else:
            user_message = f"""用户问题：{query}

注意：知识库中未检索到相关文档，请基于通用知识回答，并提示用户知识库中可能没有相关内容。"""

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]

            answer = (await llm.ainvoke(messages)).content
            state["final_answer"] = answer

            _emit_event(
                state,
                "response_generated",
                answer,
                sources_count=state["metadata"].get("sources_count", 0),
            )

            # ── 写入会话存储 ──────────────────────────────────
            if session_store:
                logger.info(f"[rag_workflow] 写入会话存储，会话ID: {state['session_id']}")

                # 构造持久化的 sources 数据（精排结果）
                reranked_results = state.get("reranked_results", [])
                sources_data = [
                    {
                        "content": r.get("content", "")[:300],
                        "chunk_text": r.get("chunk_text", "")[:500],
                        "score": r.get("rerank_score", r.get("_similarity", r.get("rrf_score", 0))),
                        "source": r.get("source", "unknown"),
                        "type": r.get("type", ""),
                        "metadata": r.get("metadata", {}),
                    }
                    for r in reranked_results
                ]

                session_store.append_message(
                    state["session_id"], "user", query
                )
                session_store.append_message(
                    state["session_id"],
                    "assistant",
                    answer,
                    metadata={
                        "intent": state["intent"].type.value if state["intent"] else None,
                        "sources_count": state["metadata"].get("sources_count", 0),
                        "processing_time_ms": int(
                            (datetime.now() - datetime.fromisoformat(state["start_time"])).total_seconds() * 1000
                        ),
                        "sources": sources_data,
                    },
                )

            # ── 写入每日日志 ──────────────────────────────────
            if memory_manager:
                logger.info(f"[rag_workflow] 写入每日日志，会话ID: {state['session_id']}")
                
                memory_manager.write_daily_log(
                    session_id=state["session_id"],
                    query=query,
                    response=answer,
                    intent=state["intent"].type.value if state["intent"] else "",
                    metadata={"sources_count": state["metadata"].get("sources_count", 0)},
                )

        except Exception as e:
            logger.error(f"[rag_workflow] 生成回答失败: {e}")
            state["error"] = f"Response generation failed: {str(e)}"
            state["final_answer"] = "抱歉，生成回答时出现问题，请稍后重试。"
            _emit_event(state, "error", f"生成回答失败: {str(e)}")

        return state

    # 节点 6: greeting_response（快速问候回答）
    async def greeting_response(state: RAGAgentState) -> RAGAgentState:
        """问候意图快速回答，跳过检索流程"""
        logger.info(f"[rag_workflow] 开始问候回答")
        llm = _get_llm(temperature=0.8)

        system_prompt = "你是一个 RAG 知识库助手，用简洁友好的方式回应用户。"
        if memory_manager:
            system_prompt = memory_manager.get_system_prompt(include_memory=False)

        try:
            answer = (await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=state["query"]),
            ])).content
            state["final_answer"] = answer

            _emit_event(state, "response_generated", answer)

            # todo: 为啥没有daily log
            if session_store:
                logger.info(f"[rag_workflow] 写入会话存储，会话ID: {state['session_id']}")
                
                session_store.append_message(state["session_id"], "user", state["query"])
                session_store.append_message(state["session_id"], "assistant", answer)

        except Exception as e:
            logger.error(f"[rag_workflow] 生成问候回答失败: {e}, 返回默认回答")
            state["final_answer"] = "你好！我是 RAG 知识库助手，请问有什么可以帮到您？"
            _emit_event(state, "response_generated", state["final_answer"])

        return state

    # 节点 7: handle_error
    def handle_error(state: RAGAgentState) -> RAGAgentState:
        """错误处理节点：生成友好的错误提示"""
        logger.error(f"[rag_workflow] 发生错误: {state.get('error', '未知错误')}")

        error_msg = state.get("error", "未知错误")

        if "timeout" in error_msg.lower():
            state["final_answer"] = "抱歉，请求处理超时，请稍后重试或简化您的问题。"
        elif "not found" in error_msg.lower() or "找不到" in error_msg:
            state["final_answer"] = "抱歉，找不到相关信息，请尝试用不同方式描述您的问题。"
        else:
            state["final_answer"] = "抱歉，处理请求时出现了错误，请稍后重试。"

        state["metadata"]["error_details"] = error_msg
        _emit_event(state, "error", state["final_answer"])
        return state

    # 路由函数
    def route_after_intent(state: RAGAgentState) -> str:
        """意图分类后的路由决策"""
        logger.info(f"[rag_workflow] 路由中...")
        if state.get("error"):
            return "error"

        intent = state.get("intent")
        if intent and intent.type == IntentType.GREETING:
            return "greeting"

        return "continue"

    def should_continue(state: RAGAgentState) -> str:
        """通用错误检查路由"""
        if state.get("error"):
            logger.error(f"[rag_workflow] 发生错误: {state.get('error', '未知错误')}")
            return "error"
        return "continue"

    # 构建状态图
    workflow = StateGraph(RAGAgentState)

    # 添加节点
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("query_expansion", query_expansion)
    workflow.add_node("hybrid_retrieval", hybrid_retrieval)
    workflow.add_node("rerank", rerank)
    workflow.add_node("generate_response", generate_response)
    workflow.add_node("greeting_response", greeting_response)
    workflow.add_node("handle_error", handle_error)

    # 设置入口
    workflow.set_entry_point("classify_intent")

    # 添加边
    workflow.add_conditional_edges(
        "classify_intent",
        route_after_intent,
        {
            "continue": "query_expansion",
            "greeting": "greeting_response",
            "error": "handle_error",
        },
    )

    workflow.add_conditional_edges(
        "query_expansion",
        should_continue,
        {
            "continue": "hybrid_retrieval",
            "error": "handle_error",
        },
    )

    workflow.add_conditional_edges(
        "hybrid_retrieval",
        should_continue,
        {
            "continue": "rerank",
            "error": "handle_error",
        },
    )

    workflow.add_conditional_edges(
        "rerank",
        should_continue,
        {
            "continue": "generate_response",
            "error": "handle_error",
        },
    )

    workflow.add_edge("generate_response", END)
    workflow.add_edge("greeting_response", END)
    workflow.add_edge("handle_error", END)

    # 编译（使用 MemorySaver 支持 checkpointing）
    checkpointer = MemorySaver()
    compiled = workflow.compile(checkpointer=checkpointer)

    logger.info("[rag_workflow] RAG Agent 工作流编译完成")
    return compiled


# 便捷函数：构建初始状态
def build_initial_state(
    query: str,
    session_id: str,
    knowledge_base_id: Optional[int] = None,
) -> RAGAgentState:
    """构建工作流初始状态"""
    return {
        "query": query,
        "session_id": session_id,
        "knowledge_base_id": knowledge_base_id,
        "intent": None,
        "expanded_queries": [],
        "raw_results": [],
        "reranked_results": [],
        "context_text": "",
        "final_answer": "",
        "events": [],
        "error": None,
        "metadata": {
            "start_time": datetime.now().isoformat(),
        },
        "start_time": datetime.now().isoformat(),
    }
