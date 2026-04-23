"""
Agent API 模块 — 提供统一的多 Agent 对话接口

核心功能：
1. /api/agent/chat          — 单 Agent 对话（支持 agent_type 参数切换）
2. /api/agent/chat/stream  — 流式对话（SSE）
3. /api/agent/compare       — 多 Agent 对比模式
4. /api/agent/list          — 列出已注册的 Agent
5. /api/agent/health        — Agent 健康检查

架构：
  FastAPI Request
       ↓
  agent/registry.py (AgentRegistry)
       ↓
  ┌─────────────┬──────────────┬────────────┐
  │ SimpleAgent │ AdvancedAgent│ ClawAgent  │
  │ Adapter     │ Adapter      │ Adapter    │
  └─────────────┴──────────────┴────────────┘
       ↓
  UnifiedResponse → JSON/SSE
"""

import asyncio
import os
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langfuse import observe, propagate_attributes

from config import init_logger
from services.auth import get_current_user

logger = init_logger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


# ─────────────────────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """对话请求"""
    query: str = Field(..., min_length=1, max_length=2000, description="用户查询")
    session_id: Optional[str] = Field(None, description="会话 ID，不提供则自动生成")
    agent_type: Optional[str] = Field(None, description="Agent 类型: simple | advanced | claw")
    chat_history: Optional[List[Dict[str, str]]] = Field(default=[], description="对话历史")
    knowledge_base_id: Optional[int] = Field(None, description="知识库 ID")
    stream: bool = Field(default=False, description="是否启用流式输出")


class CompareRequest(BaseModel):
    """对比请求"""
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None)
    chat_history: Optional[List[Dict[str, str]]] = Field(default=[])
    agent_types: Optional[List[str]] = Field(
        None,
        description="指定参与的 Agent 类型，为空则使用全部已注册"
    )


class AgentInfo(BaseModel):
    """Agent 信息"""
    type: str
    name: str
    is_default: bool
    capabilities: List[str]


# ─────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────

def _ensure_registry_initialized():
    """
    确保 Agent 注册中心已初始化（仅注册工厂，不实例化 Agent）
    
    这个函数在第一次需要实际使用 Agent 时调用（如 /chat、/chat/stream）。
    它只注册 Agent 工厂，真正的 Agent 实例会在 registry.get() 时按需创建。
    """
    from agent.registry import get_registry, setup_registry

    registry = get_registry()

    # 检查是否已注册工厂（注意：不是检查实例）
    if not hasattr(registry, '_factories') or not registry._factories:
        # 懒加载注册（避免循环导入）
        from agent.claw_agent.memory.memory_manager import MemoryManager
        from agent.claw_agent.memory.session_store import SessionStore

        memory_manager = MemoryManager()
        session_store = SessionStore()

        setup_registry(
            claw_memory_manager=memory_manager,
            claw_session_store=session_store,
        )
        logger.info("[Agent API] Agent 注册中心工厂已注册")

    return registry


def _parse_agent_type(agent_type_str: Optional[str]) -> str:
    """解析并验证 agent_type 参数"""
    if not agent_type_str:
        return "claw"  # 默认

    agent_type_str = agent_type_str.lower().strip()
    valid_types = {"simple", "advanced", "claw"}

    if agent_type_str not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 agent_type: {agent_type_str}，可选值: {list(valid_types)}"
        )

    return agent_type_str


# ─────────────────────────────────────────────────────────────
# API 端点
# ─────────────────────────────────────────────────────────────

@router.get("/list")
async def list_agents(
    current_user=Depends(get_current_user),
):
    """
    列出所有已注册的 Agent 类型及其能力

    返回示例：
    ```json
    {
      "agents": [
        {
          "type": "simple",
          "name": "SimpleRAGAgent",
          "is_default": false,
          "capabilities": ["retrieval", "basic-chat"]
        },
        {
          "type": "advanced",
          "name": "AdvancedRAGAgent",
          "is_default": false,
          "capabilities": ["intent-classification", "entity-extraction", "task-planning", "tool-call"]
        },
        {
          "type": "claw",
          "name": "ClawRAGAgent",
          "is_default": true,
          "capabilities": ["rag-workflow", "query-expansion", "hybrid-retrieval", "rerank", "memory", "sse-stream"]
        }
      ],
      "default": "claw"
    }
    ```
    """
    # 注意：这里不调用 _get_registry()，避免触发 Agent 实例化
    # 直接返回静态配置的 Agent 列表
    from agent.registry import AgentType

    # 定义各 Agent 的能力描述
    capabilities_map = {
        "simple": ["retrieval", "basic-chat", "chain-mode"],
        "advanced": ["intent-classification", "entity-extraction", "task-planning", "tool-call", "conversation-management"],
        "claw": ["rag-workflow", "query-expansion", "hybrid-retrieval", "rerank", "memory-management", "sse-stream"],
    }

    name_map = {
        "simple": "SimpleRAGAgent",
        "advanced": "AdvancedRAGAgent",
        "claw": "ClawRAGAgent",
    }

    # 静态返回所有支持的 Agent 类型（不触发实例化）
    agents = []
    default_type = "claw"
    for at in ["simple", "advanced", "claw"]:
        agents.append({
            "type": at,
            "name": name_map.get(at, at),
            "is_default": at == default_type,
            "capabilities": capabilities_map.get(at, []),
        })

    return {
        "agents": agents,
        "default": default_type,
    }


@router.get("/preheat-status")
async def agent_preheat_status(
    req: Request,
    current_user=Depends(get_current_user),
):
    """
    查询 Agent 预热状态

    返回后台预热线程的状态，前端可根据此状态决定是否显示加载提示。
    """
    preheat = getattr(req.app.state, 'agent_preheat', None)
    if not preheat:
        return {"status": "unknown", "message": "预热信息不可用"}

    status_map = {
        'pending': {'label': '等待中', 'ready': False},
        'warming':  {'label': '正在初始化...', 'ready': False},
        'ready':    {'label': '就绪', 'ready': True},
        'error':    {'label': '初始化失败', 'ready': False, 'error': preheat.get('error')},
    }

    result = status_map.get(preheat['status'], {"label": "未知", "ready": False})
    result['raw_status'] = preheat['status']

    # 计算已用时间
    started = preheat.get('started_at')
    if started:
        import time
        result['elapsed_s'] = round(time.time() - started, 1)

    return result





@router.get("/health")
async def agent_health(
    req: Request,
    current_user=Depends(get_current_user),
):
    """
    Agent 服务健康检查

    返回各 Agent 的初始化状态和响应时间。
    注意：首次调用会触发对应 Agent 的实例化。
    """
    registry = _ensure_registry_initialized()
    health_status = {
        "registry": "ok",
        "agents": {},
    }

    for agent_type in ["simple", "advanced", "claw"]:
        try:
            start = datetime.now()
            agent = registry.get(agent_type=agent_type)
            latency_ms = (datetime.now() - start).total_seconds() * 1000

            health_status["agents"][agent_type] = {
                "status": "ok",
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            health_status["agents"][agent_type] = {
                "status": "error",
                "error": str(e),
            }

    return health_status


@observe(as_type="span", name="chat")
@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user=Depends(get_current_user),
):
    """
    单 Agent 对话（非流式）

    通过 agent_type 参数切换不同的 Agent：
    - simple   → 轻量 Chain Agent
    - advanced → 完整 LangGraph Agent
    - claw     → RAG 专属工作流（默认）

    示例请求：
    ```json
    {
      "query": "RAG 技术是什么？",
      "agent_type": "claw",
      "knowledge_base_id": "kb123",
      "session_id": "user123_session1"
    }
    ```
    """
    registry = _ensure_registry_initialized()
    agent_type_str = _parse_agent_type(request.agent_type)

    try:
        from agent.registry import AgentType
        agent_type = AgentType(agent_type_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"未知 Agent 类型: {agent_type_str}")

    try:
        agent = registry.get(agent_type=agent_type)

        # 获取追踪 callbacks
        from evaluation.tracing import get_callbacks
        callbacks = get_callbacks()

        with propagate_attributes(session_id=request.session_id, user_id=str(current_user["id"])):
            response = await agent.process(
                query=request.query,
                session_id=request.session_id,
                chat_history=request.chat_history,
                knowledge_base_id=request.knowledge_base_id,
                callbacks=callbacks,
            )

            return {
                "status": "success",
                "response": response.to_dict(),
            }

    except Exception as e:
        logger.error(f"[Agent API] chat 失败 ({agent_type_str}): {e}")
        raise HTTPException(status_code=500, detail=f"Agent 处理失败: {str(e)}")

@observe(as_type="span", name="chat_stream")
@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    current_user=Depends(get_current_user),
):
    """
    流式对话（SSE）

    启用 Server-Sent Events 实时推送 Agent 处理进度和回答内容。

    事件类型：
    - thinking  → Agent 正在思考
    - intent    → 意图识别结果
    - retrieved → 检索完成
    - reranked  → 精排完成
    - chunk     → 回答内容块
    - error     → 错误信息
    - done      → 流式结束

    示例请求：
    ```json
    {
      "query": "RAG 和 Fine-tuning 的区别是什么？",
      "agent_type": "claw",
      "stream": true
    }
    ```
    """
    registry = _ensure_registry_initialized()
    agent_type_str = _parse_agent_type(request.agent_type)

    try:
        from agent.registry import AgentType
        agent_type = AgentType(agent_type_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"未知 Agent 类型: {agent_type_str}")

    session_id = request.session_id or str(uuid.uuid4())

    async def event_generator():
        """SSE 事件生成器"""
        try:
            agent = registry.get(agent_type=agent_type)

            # 获取追踪 callbacks
            from evaluation.tracing import get_callbacks
            callbacks = get_callbacks()

            # 发射连接成功事件
            import json
            yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id, 'agent_type': agent_type_str})}\n\n".encode("utf-8")

            with propagate_attributes(session_id=session_id, user_id=str(current_user["id"])):
                if hasattr(agent, "stream_process") and agent_type == AgentType.CLAW:
                    # ClawAgent 支持真正的流式
                    async for chunk in agent.stream_process(
                        query=request.query,
                        session_id=session_id,
                        chat_history=request.chat_history,
                        knowledge_base_id=request.knowledge_base_id,
                        callbacks=callbacks,
                    ):
                        yield chunk.to_sse().encode("utf-8")
                else:
                    # 其他 Agent 模拟流式
                    async for chunk in agent.stream_process(
                        query=request.query,
                        session_id=session_id,
                        chat_history=request.chat_history,
                        callbacks=callbacks,
                    ):
                        yield chunk.to_sse().encode("utf-8")
                # 发射结束事件
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n".encode("utf-8")

        except Exception as e:
            logger.error(f"[Agent API] 流式处理失败 ({agent_type_str}): {e}")
            import json
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n".encode("utf-8")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@router.post("/compare")
async def compare_agents(
    request: CompareRequest,
    current_user=Depends(get_current_user),
):
    """
    多 Agent 对比模式

    同时运行多个 Agent，返回各 Agent 的回答和处理信息，便于横向对比效果。

    对比维度：
    - 回答内容质量
    - 处理耗时
    - 意图识别准确性
    - 检索文档数量

    示例请求：
    ```json
    {
      "query": "什么是 RAG？",
      "agent_types": ["simple", "advanced", "claw"]
    }
    ```
    """
    registry = _ensure_registry_initialized()

    # 确定要对比的 Agent 类型
    if request.agent_types:
        try:
            from agent.registry import AgentType
            target_types = [AgentType(at) for at in request.agent_types]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"无效的 Agent 类型: {e}")
    else:
        # 使用所有已注册的
        target_types = None

    start_time = datetime.now()
    # 获取追踪 callbacks
    from evaluation.tracing import get_callbacks
    callbacks = get_callbacks()

    try:
        # 并行执行所有 Agent
        results = await registry.compare_all(
            query=request.query,
            session_id=request.session_id,
            chat_history=request.chat_history,
            callbacks=callbacks,
        )

        # 过滤指定的类型
        if target_types:
            results = {
                k: v for k, v in results.items()
                if k in [t.value for t in target_types]
            }

        # 构建对比表格
        comparison = {
            "query": request.query,
            "session_id": request.session_id,
            "total_time_ms": round((datetime.now() - start_time).total_seconds() * 1000, 2),
            "results": {
                agent_type: {
                    "content": resp.content,
                    "agent_type": resp.agent_type,
                    "intent": resp.intent,
                    "confidence": resp.confidence,
                    "sources_count": resp.sources_count,
                    "processing_time": round(resp.processing_time, 3),
                    "error": resp.error,
                }
                for agent_type, resp in results.items()
            },
        }

        return {
            "status": "success",
            "comparison": comparison,
        }

    except Exception as e:
        logger.error(f"[Agent API] compare 失败: {e}")
        raise HTTPException(status_code=500, detail=f"对比模式失败: {str(e)}")


@router.get("/session/{session_id}/history")
async def get_session_history(
    session_id: str,
    limit: int = 20,
    current_user=Depends(get_current_user),
):
    """
    获取会话历史

    支持 ClawAgent 的会话历史查询。
    """
    try:
        from agent.claw_agent.memory.session_store import SessionStore
        store = SessionStore()
        messages = store.get_messages(session_id, limit=limit)

        return {
            "status": "success",
            "session_id": session_id,
            "messages": messages,
            "count": len(messages),
        }

    except Exception as e:
        logger.error(f"[Agent API] 获取会话历史失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话历史失败: {str(e)}")


@router.get("/sessions")
async def list_all_sessions(
    limit: int = 50,
    current_user=Depends(get_current_user),
):
    """
    列出所有历史会话（按更新时间降序）

    返回 sessions/ 目录下所有 .json 会话文件的摘要信息。
    """
    try:
        from agent.claw_agent.memory.session_store import SessionStore
        store = SessionStore()
        sessions = store.list_sessions(limit=limit)

        return {
            "status": "success",
            "sessions": sessions,
            "total": len(sessions),
        }

    except Exception as e:
        logger.error(f"[Agent API] 列出会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"列出会话失败: {str(e)}")


@router.delete("/session/{session_id}")
async def delete_or_clear_session(
    session_id: str,
    action: Optional[str] = None,  # action=delete 真正删除文件，默认只清空消息
    current_user=Depends(get_current_user),
):
    """
    清空或删除指定会话

    - 无 action 参数（或 action=clear）：清空会话的所有历史消息，保留会话文件
    - action=delete：彻底删除会话文件（不可恢复）
    """
    try:
        from agent.claw_agent.memory.session_store import SessionStore
        store = SessionStore()

        if action == "delete":
            # 真正删除会话文件
            success = store.delete_session(session_id)
            if not success:
                raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
            return {
                "status": "success",
                "message": f"会话 {session_id} 已删除",
                "action": "deleted",
            }
        else:
            # 只清空消息（保留会话）
            store.clear_session(session_id)
            return {
                "status": "success",
                "message": f"会话 {session_id} 已清空",
                "action": "cleared",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Agent API] 操作会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"操作会话失败: {str(e)}")


# ─────────────────────────────────────────────────────────────
# 用户反馈（点赞 / 点踩）
# ─────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    """用户反馈请求"""
    trace_id: str = Field(..., description="Langfuse trace ID（确定性 ID，由后端 SSE 事件下发）")
    value: int = Field(..., ge=0, le=1, description="1=点赞 / 0=点踩")
    comment: Optional[str] = Field(None, max_length=500, description="可选的文字评论")
    message_index: Optional[int] = Field(None, description="消息在会话中的索引（用于区分同会话多轮）")
    session_id: Optional[str] = Field(None, description="会话 ID，用于 fallback 生成确定性 trace_id")


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    current_user=Depends(get_current_user),
):
    """
    提交消息反馈（点赞 / 点踩）并同步到 Langfuse

    将用户反馈以 Score 形式写入 Langfuse，可在 Langfuse UI 的 Traces 和 Sessions 中查看。

    - value=1 → 正向反馈（👍）
    - value=0 → 负向反馈（👎）

    trace_id 优先使用前端传来的确定性 ID；
    若 trace_id 看起来像 session_id（非 32 位 hex），则用 session_id 重新计算。

    只有 TRACER_BACKEND=langfuse 时才会实际写入 Langfuse；
    其他模式下接口依然正常返回 200，仅跳过远端写入。
    """
    tracer_backend = os.getenv("TRACER_BACKEND", "none").lower().strip()

    if tracer_backend == "langfuse":
        try:
            from langfuse import get_client, get_current_trace_id
            langfuse = get_client()

            actual_trace_id = request.trace_id

            # 如果前端没有 trace_id，尝试从当前上下文获取
            if not actual_trace_id:
                actual_trace_id = get_current_trace_id()

            if not actual_trace_id:
                logger.warning("[Agent Feedback] 无法获取 trace_id，跳过 Score 写入")
                return {
                    "status": "ok",
                    "trace_id": request.trace_id,
                    "value": request.value,
                    "synced_to_langfuse": False,
                }

            # 构造 comment
            comment_parts = []
            if request.message_index is not None:
                comment_parts.append(f"msg_idx={request.message_index}")
            if request.comment:
                comment_parts.append(request.comment)
            full_comment = " | ".join(comment_parts) if comment_parts else None

            langfuse.create_score(
                trace_id=actual_trace_id,
                name="user-feedback",
                value=float(request.value),
                comment=full_comment,
                data_type="NUMERIC",
            )
            langfuse.flush()

            logger.info(
                f"[Agent Feedback] trace_id={actual_trace_id} "
                f"value={request.value} user={current_user.get('username', '?')}"
            )
        except ImportError:
            logger.warning("[Agent Feedback] langfuse 未安装，跳过 Score 写入")
        except Exception as e:
            # 反馈不影响主流程，仅记录日志
            logger.error(f"[Agent Feedback] Langfuse score 写入失败: {e}")
    else:
        logger.debug(
            f"[Agent Feedback] TRACER_BACKEND={tracer_backend}，跳过 Langfuse 写入 "
            f"(trace_id={request.trace_id}, value={request.value})"
        )

    return {
        "status": "ok",
        "trace_id": request.trace_id,
        "value": request.value,
        "synced_to_langfuse": tracer_backend == "langfuse",
    }
