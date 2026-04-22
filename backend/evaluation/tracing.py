"""
统一 Tracer 追踪封装 — Phoenix / Langfuse / None 快速切换

通过环境变量 TRACER_BACKEND 一键切换追踪后端：
  - "phoenix"  → Arize Phoenix（本地运行，零基础设施）
  - "langfuse" → Langfuse（自托管或云服务，更完整的平台功能）
  - "none"     → 关闭追踪（默认）

使用方式：
  1. 应用启动时调用 setup_tracing()
  2. Agent 调用时传入 get_callbacks() → config={"callbacks": get_callbacks()}
  3. 切换后端只需改 .env 中的 TRACER_BACKEND

架构设计：
  ┌─────────────────────────────────────────────────┐
  │            evaluation/tracing.py                  │
  │  ┌───────────┐  ┌───────────┐  ┌──────────────┐ │
  │  │  Phoenix   │  │  Langfuse │  │   No Trace   │ │
  │  │  (OTEL)   │  │ (Callback)│  │   (空操作)    │ │
  │  └─────┬─────┘  └─────┬─────┘  └──────┬───────┘ │
  │        └───────────────┴───────────────┘         │
  │                   ↓                              │
  │          统一对外接口                              │
  │     setup_tracing() / get_callbacks()            │
  └─────────────────────────────────────────────────┘

Phoenix 接入方式：
  - 全局 OpenTelemetry Instrumentation（启动时挂载，不需要 callback）
  - openinference-instrumentation-langchain 自动拦截所有 LangChain/LangGraph 调用
  - 数据发往本地 Phoenix server（pip install 后 python -m phoenix.server.main）

Langfuse 接入方式：
  - LangChain Callback Handler（per-call 注入）
  - 每次 Agent 调用时通过 config={"callbacks": [handler]} 传入
  - 数据发往 Langfuse server（自托管或 cloud.langfuse.com）
"""

import os
from typing import List, Optional, Dict, Any
from enum import Enum

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import init_logger

logger = init_logger(__name__)


# ─────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────

class TracerBackend(str, Enum):
    """追踪后端类型"""
    PHOENIX = "phoenix"
    LANGFUSE = "langfuse"
    NONE = "none"


# 从环境变量读取，默认关闭
TRACER_BACKEND = os.getenv("TRACER_BACKEND", "none").lower().strip()

# 模块级状态
_tracer_initialized = False
_phoenix_session = None


# ─────────────────────────────────────────────────────────────
# Phoenix 后端
# ─────────────────────────────────────────────────────────────

def _setup_phoenix():
    """
    初始化 Phoenix 追踪

    Phoenix 使用 OpenTelemetry 全局 Instrumentation：
    - 启动时自动拦截所有 LangChain/LangGraph 调用
    - 不需要每次调用传 callback
    - 本地运行，数据存在文件系统

    依赖：
      pip install arize-phoenix openinference-instrumentation-langchain
    """
    global _phoenix_session

    try:
        import phoenix as px

        # 启动 Phoenix server（后台进程）
        _phoenix_session = px.launch_app()
        logger.info(f"[Tracing] Phoenix 已启动 → {_phoenix_session.url}")

        # 注册 LangChain Instrumentation（全局拦截）
        from openinference.instrumentation.langchain import LangChainInstrumentor

        LangChainInstrumentor().instrument()
        logger.info("[Tracing] Phoenix LangChain Instrumentation 已注册")

    except ImportError as e:
        missing = []
        if "phoenix" in str(e):
            missing.append("arize-phoenix")
        if "openinference" in str(e):
            missing.append("openinference-instrumentation-langchain")

        msg = f"Phoenix 依赖缺失，请执行: pip install {' '.join(missing or ['arize-phoenix', 'openinference-instrumentation-langchain'])}"
        logger.error(f"[Tracing] {msg}")
        raise ImportError(msg)
    except Exception as e:
        logger.error(f"[Tracing] Phoenix 初始化失败: {e}")
        raise


def _phoenix_get_callbacks() -> List:
    """Phoenix 使用全局 Instrumentation，不需要 callback"""
    return []


# ─────────────────────────────────────────────────────────────
# Langfuse 后端
# ─────────────────────────────────────────────────────────────

def _setup_langfuse():
    """
    初始化 Langfuse 追踪

    Langfuse 使用 LangChain Callback Handler：
    - 每次调用时通过 config={"callbacks": [handler]} 传入
    - 支持自托管（Docker）或云服务

    依赖：
      pip install langfuse

    环境变量：
      LANGFUSE_PUBLIC_KEY  — Public Key
      LANGFUSE_SECRET_KEY  — Secret Key
      LANGFUSE_HOST        — 服务地址（默认 https://cloud.langfuse.com）
    """
    required_vars = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]
    missing = [v for v in required_vars if not os.getenv(v)]

    if missing:
        msg = f"Langfuse 环境变量缺失: {', '.join(missing)}。请在 .env 中配置。"
        logger.error(f"[Tracing] {msg}")
        raise ValueError(msg)

    # 验证连接
    try:
        from langfuse import Langfuse

        lf = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            base_url=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        # 简单的健康检查
        health = lf.auth_check()
        logger.info(f"[Tracing] Langfuse 连接验证: {'成功' if health else '失败'}")

    except ImportError:
        msg = "Langfuse 依赖缺失，请执行: pip install langfuse"
        logger.error(f"[Tracing] {msg}")
        raise ImportError(msg)
    except Exception as e:
        logger.warning(f"[Tracing] Langfuse 连接验证失败（服务可能未启动）: {e}")
        # 不抛异常，允许后续重试


def _langfuse_get_callbacks() -> List:
    """
    创建 Langfuse Callback Handler 实例

    每次调用都会创建新实例，确保 trace_id 隔离。

    兼容性说明：
      - langfuse v2.x: from langfuse.callback import CallbackHandler，构造函数接受 public_key/secret_key/host
      - langfuse v3+:  from langfuse.langchain import CallbackHandler，构造函数从环境变量自动读取
      - langfuse v4+:  同 v3+，LangchainCallbackHandler 不接受 secret_key 参数
    """
    try:
        # langfuse v3+/v4+ 新路径
        try:
            from langfuse.langchain import CallbackHandler as LangchainCallbackHandler
            logger.info("[Tracing] Langfuse v3+/v4+ 已加载")
            # v3+/v4+ 风格：从环境变量自动读取（LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST）
            handler = LangchainCallbackHandler()
        except ImportError:
            # 降级到 v2.x 旧路径
            from langfuse.callback import CallbackHandler as LangchainCallbackHandler
            logger.info("[Tracing] Langfuse v2.x 已加载")
            # v2.x 风格：显式传参
            handler = LangchainCallbackHandler(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )

        logger.info("[Tracing] Langfuse callback handler 已创建")
        return [handler]

    except ImportError as ie:
        logger.error(f"[Tracing] langfuse 未安装，无法创建 callback handler: {ie}")
        return []
    except Exception as e:
        logger.error(f"[Tracing] Langfuse callback 创建失败: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# None 后端（关闭追踪）
# ─────────────────────────────────────────────────────────────

def _setup_none():
    """关闭追踪"""
    logger.info("[Tracing] 追踪已禁用 (TRACER_BACKEND=none)")


def _none_get_callbacks() -> List:
    return []


# ─────────────────────────────────────────────────────────────
# 统一对外接口
# ─────────────────────────────────────────────────────────────

# 后端注册表
_BACKEND_REGISTRY = {
    TracerBackend.PHOENIX: {
        "setup": _setup_phoenix,
        "get_callbacks": _phoenix_get_callbacks,
    },
    TracerBackend.LANGFUSE: {
        "setup": _setup_langfuse,
        "get_callbacks": _langfuse_get_callbacks,
    },
    TracerBackend.NONE: {
        "setup": _setup_none,
        "get_callbacks": _none_get_callbacks,
    },
}


def setup_tracing(backend: Optional[str] = None) -> Dict[str, Any]:
    """
    应用启动时调用一次，初始化追踪后端

    Args:
        backend: 强制指定后端（覆盖环境变量）。
                 "phoenix" | "langfuse" | "none"

    Returns:
        初始化结果信息

    使用示例：
        # app.py 启动时
        from evaluation.tracing import setup_tracing
        result = setup_tracing()
        # → {"backend": "phoenix", "status": "ok", "url": "http://localhost:6006"}
    """
    global _tracer_initialized

    backend_str = (backend or TRACER_BACKEND).lower().strip()

    try:
        backend_enum = TracerBackend(backend_str)
    except ValueError:
        logger.warning(f"[Tracing] 未知的后端 '{backend_str}'，回退到 'none'")
        backend_enum = TracerBackend.NONE

    handler = _BACKEND_REGISTRY[backend_enum]

    result = {
        "backend": backend_enum.value,
        "status": "ok",
    }

    try:
        handler["setup"]()

        if backend_enum == TracerBackend.PHOENIX and _phoenix_session:
            result["url"] = _phoenix_session.url
        elif backend_enum == TracerBackend.LANGFUSE:
            result["host"] = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.error(f"[Tracing] 初始化失败: {e}")

    _tracer_initialized = True
    return result


def get_callbacks() -> List:
    """
    每次 Agent 调用时获取 callback 列表

    传入 LangChain/LangGraph 的 config 参数：
        agent.ainvoke(input, config={"callbacks": get_callbacks()})

    - Phoenix: 返回空列表（全局 instrumentation，不需要 callback）
    - Langfuse: 返回 [CallbackHandler] 实例
    - None: 返回空列表
    """
    backend_str = TRACER_BACKEND.lower().strip()

    try:
        backend_enum = TracerBackend(backend_str)
    except ValueError:
        backend_enum = TracerBackend.NONE

    handler = _BACKEND_REGISTRY[backend_enum]
    return handler["get_callbacks"]()


def get_tracing_config(session_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """
    构建 LangGraph 的完整 config 字典

    Args:
        session_id: 会话 ID（作为 trace 的 metadata）
        **kwargs: 额外的 metadata

    Returns:
        可直接传给 agent.ainvoke() 的 config 字典

    使用示例：
        config = get_tracing_config(session_id="user123", user_id="admin")
        result = await agent.ainvoke(input, config=config)
    """
    config: Dict[str, Any] = {
        "callbacks": get_callbacks(),
    }

    # 构建 metadata
    metadata = {}
    if session_id:
        metadata["session_id"] = session_id
    metadata.update(kwargs)

    if metadata:
        config["metadata"] = metadata

    return config


def get_tracer_info() -> Dict[str, Any]:
    """
    获取当前追踪配置信息（用于 /health 或调试）

    Returns:
        {
            "backend": "phoenix",
            "initialized": true,
            "url": "http://localhost:6006",
            ...
        }
    """
    backend_str = TRACER_BACKEND.lower().strip()

    try:
        backend_enum = TracerBackend(backend_str)
    except ValueError:
        backend_enum = TracerBackend.NONE

    info = {
        "backend": backend_enum.value,
        "initialized": _tracer_initialized,
    }

    if backend_enum == TracerBackend.PHOENIX and _phoenix_session:
        info["url"] = _phoenix_session.url
    elif backend_enum == TracerBackend.LANGFUSE:
        info["host"] = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        info["has_keys"] = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))

    return info
