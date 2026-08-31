"""
运行时配置中心 — 可写配置的元信息 + 应用钩子

设置页 / PUT /api/settings 修改配置后：
  1. set_runtime() 写入运行时覆盖（并同步 os.environ）
  2. 按配置项执行 apply 钩子（重建 reranker / 搜索引擎 / Milvus / Agent 等）
  3. 业务代码通过 get_runtime() 读取，实现"不重启生效"
"""
import logging
import os
import re
import sys
from typing import Any, Callable, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import init_logger, get_runtime, set_runtime

logger = init_logger(__name__)


# ── 分组标签 ────────────────────────────────────────────────
GROUPS: Dict[str, str] = {
    "retrieval": "检索配置",
    "chunking": "文档切分",
    "llm": "LLM 参数",
    "session": "会话与记忆",
    "processing": "文档处理",
    "model": "模型与 LLM",
    "system": "系统配置",
    "evolving": "自进化记忆",
    "api_keys": "API Keys",
}


# ── 可写配置元信息 ──────────────────────────────────────────
# sensitive=True 的项在前端用密码框输入，GET 不回显明文
WRITABLE_CONFIGS: Dict[str, dict] = {
    # ── 检索配置（立即生效，无需重建） ──
    "RETRIEVAL_MIN_SCORE": {
        "group": "retrieval",
        "type": "float", "min": 0.0, "max": 1.0,
        "label": "检索最低相关度阈值",
        "description": "低于此分数的检索结果将被过滤（向量按相似度、关键词按 BM25 分数）",
    },
    "RETRIEVAL_TOP_K": {
        "group": "retrieval",
        "type": "int", "min": 1, "max": 100,
        "label": "检索默认 Top-K",
        "description": "检索默认返回条数（请求不传 limit 时生效；Agent 检索也会读取）",
    },
    "RERANKER_TYPE": {
        "group": "retrieval",
        "type": "enum", "enum": ["cross_encoder", "llm", "none"],
        "label": "Reranker 类型",
        "description": "重排序引擎，切换后自动重置实例",
    },
    "RRF_K": {
        "group": "retrieval",
        "type": "int", "min": 1, "max": 200,
        "label": "RRF 融合平滑常数",
        "description": "倒数排名融合（RRF）的 k 值，越大越平滑，默认 60",
    },
    "DEFAULT_RETRIEVAL_MODE": {
        "group": "retrieval",
        "type": "enum", "enum": ["native", "advanced", "hybrid", "graph"],
        "label": "默认检索模式",
        "description": "native=仅原文向量 / advanced=摘要+子问题 / hybrid=三路并行+RRF融合 / graph=实体图谱（需KB启用entity增强）",
    },
    "NUM_SUBQUESTIONS": {
        "group": "retrieval",
        "type": "int", "min": 1, "max": 5,
        "label": "查询扩展子问题数",
        "description": "查询扩展时生成的子问题数量（1-5）",
    },
    "MILVUS_NPROBE": {
        "group": "retrieval",
        "type": "int", "min": 1, "max": 1000,
        "label": "Milvus 搜索探针数",
        "description": "IVF 索引搜索时的 nprobe，越大召回越高但越慢",
    },

    # ── 文档切分（下次导入文档时生效，已导入的不受影响）──
    "CHUNK_SIZE": {
        "group": "chunking",
        "type": "int", "min": 100, "max": 2000,
        "label": "Chunk 目标大小",
        "description": "递归字符切割器的目标 chunk 大小（字符数）",
    },
    "CHUNK_OVERLAP": {
        "group": "chunking",
        "type": "int", "min": 0, "max": 500,
        "label": "Chunk 重叠字符数",
        "description": "递归切割时相邻 chunk 的重叠字符数",
    },
    "MIN_CHUNK_SIZE": {
        "group": "chunking",
        "type": "int", "min": 50, "max": 500,
        "label": "最小 Chunk 合并阈值",
        "description": "Markdown 切分后短于此值的 chunk 会被合并到相邻 chunk",
    },
    "MAX_CHUNK_SIZE": {
        "group": "chunking",
        "type": "int", "min": 500, "max": 5000,
        "label": "最大 Chunk 二次切割阈值",
        "description": "Markdown 切分后长于此值的 chunk 会被递归切割器二次切分",
    },
    "MILVUS_METRIC_TYPE": {
        "group": "chunking",
        "type": "enum", "enum": ["COSINE", "L2", "IP"],
        "label": "向量距离度量",
        "description": "Milvus 向量距离度量方式。注意：仅对新建集合生效，已有集合需删除后重建",
    },
    "EMBEDDING_DIM": {
        "group": "chunking",
        "type": "int", "min": 64, "max": 4096,
        "label": "向量维度",
        "description": "Embedding 向量维度。换 embedding 模型时需同步修改，且必须重新导入全部向量",
    },
    "MILVUS_NLIST": {
        "group": "chunking",
        "type": "int", "min": 1, "max": 65536,
        "label": "IVF 聚类中心数",
        "description": "IVF_FLAT 索引的 nlist 参数。仅建索引时生效，已有索引需重建",
    },
    "MILVUS_TIMEOUT": {
        "group": "retrieval",
        "type": "float", "min": 5, "max": 300,
        "label": "向量检索超时(秒)",
        "description": "单次 Milvus 检索超时。Zilliz serverless 冷启动可能超过 pymilvus 默认 10s，失败会触发自动重试",
    },
    "CHUNK_STRATEGY": {
        "group": "chunking",
        "type": "enum", "enum": ["auto", "markdown", "recursive"],
        "label": "切割策略",
        "description": "全局默认切割策略（auto=按内容自动探测）。知识库可单独覆盖；下次切割文档时生效",
    },
    "ENABLED_ENHANCERS": {
        "group": "chunking",
        "type": "csv", "enum": ["sub_question", "summary"],
        "label": "启用的增强器",
        "description": "逗号分隔：sub_question,summary。留空 = 全关（纯原文 RAG）。知识库可单独覆盖",
    },

    # ── LLM 参数（消费方每次请求读取，热生效）──
    "LLM_TEMPERATURE_DEFAULT": {
        "group": "llm",
        "type": "float", "min": 0.0, "max": 2.0,
        "label": "LLM 默认温度",
        "description": "Agent 默认温度（simple/advanced agent），切换后重建 Agent 实例",
    },
    "LLM_TEMPERATURE_ANSWER": {
        "group": "llm",
        "type": "float", "min": 0.0, "max": 2.0,
        "label": "回答生成温度",
        "description": "RAG Agent 生成回答时的 LLM 温度（claw_agent generate_response）",
    },
    "LLM_TEMPERATURE_GREETING": {
        "group": "llm",
        "type": "float", "min": 0.0, "max": 2.0,
        "label": "问候回答温度",
        "description": "问候意图快速回答时的 LLM 温度（claw_agent greeting_response）",
    },
    "LLM_RERANKER_MAX_TOKENS": {
        "group": "llm",
        "type": "int", "min": 100, "max": 4000,
        "label": "LLM Reranker 最大 Token",
        "description": "LLM 式 Reranker 的 max_tokens，切换后重置 Reranker 实例",
    },

    # ── 会话与记忆 ──
    "SESSION_MAX_HISTORY": {
        "group": "session",
        "type": "int", "min": 1, "max": 100,
        "label": "每会话最大保留轮数",
        "description": "advanced agent 会话保留的最大对话轮数，超出后旧轮次被摘要替代",
    },
    "SESSION_CONTEXT_WINDOW": {
        "group": "session",
        "type": "int", "min": 1, "max": 50,
        "label": "上下文窗口大小",
        "description": "拼接到 prompt 的近期对话轮数（advanced agent + claw_agent 共用）",
    },

    # ── 文档处理 ──
    "LLM_MAX_RETRIES": {
        "group": "processing",
        "type": "int", "min": 0, "max": 10,
        "label": "LLM 重试次数",
        "description": "文档处理时 ChatModel 的最大重试次数",
    },
    "LLM_TIMEOUT": {
        "group": "processing",
        "type": "int", "min": 10, "max": 600,
        "label": "LLM 超时（秒）",
        "description": "文档处理时 ChatModel 的请求超时时间",
    },

    # ── 模型与 LLM（消费方每次请求读取，热生效） ──
    "DEFAULT_MODEL": {
        "group": "model",
        "type": "str",
        "label": "默认对话模型",
        "description": "Agent / 文档处理使用的对话模型（Agent 实例将自动重建）",
    },
    "EMBEDDING_MODEL": {
        "group": "model",
        "type": "str",
        "label": "嵌入模型",
        "description": "向量化模型（换成不同向量维度的模型需重新导入向量）",
    },
    "LITELLM_BASE_URL": {
        "group": "model",
        "type": "str",
        "label": "LLM API 地址",
        "description": "LiteLLM 代理地址（.env 键名为 BASE_URL）",
    },

    # ── 系统配置（部分需要重建组件） ──
    "STARTUP_PREHEAT": {
        "group": "system",
        "type": "enum", "enum": ["true", "false"],
        "label": "启动后台预热",
        "description": "启动时后台并发预热 Milvus/搜索索引/Agent；关闭则纯懒加载（下次启动生效）",
    },
    "STARTUP_READY_TIMEOUT": {
        "group": "system",
        "type": "int", "min": 1, "max": 600,
        "label": "就绪等待超时（秒）",
        "description": "请求路径等待未就绪组件的最长秒数，超时返回 503",
    },
    "BM25_CACHE_BUCKETS": {
        "group": "system",
        "type": "int", "min": 1, "max": 10000,
        "label": "BM25 缓存桶数上限",
        "description": "内存中 BM25Okapi 模型的 LRU 桶数上限（立即生效）",
    },
    "BM25_CACHE_MAX_CHUNKS": {
        "group": "system",
        "type": "int", "min": 100, "max": 10000000,
        "label": "BM25 缓存 chunk 总量上限",
        "description": "所有桶缓存的 chunk 总量上限，超限 LRU 逐出（立即生效）",
    },
    "SEARCH_BACKEND": {
        "group": "system",
        "type": "enum", "enum": ["bm25", "elasticsearch"],
        "label": "搜索引擎后端",
        "description": "切换后自动重建索引（bm25 从 PostgreSQL 全量加载）",
    },
    "MILVUS_HOST": {
        "group": "system",
        "type": "str",
        "label": "本地 Milvus 地址",
        "description": "仅 MILVUS_URI 留空或 Zilliz Cloud 连接失败时生效",
    },
    "MILVUS_PORT": {
        "group": "system",
        "type": "str",
        "label": "本地 Milvus 端口",
        "description": "仅本地模式生效",
    },
    "MILVUS_DB_NAME": {
        "group": "system",
        "type": "str",
        "label": "Milvus 数据库",
        "description": "Zilliz Cloud Free 强制用 default；本地可自定义",
    },
    "MILVUS_URI": {
        "group": "system",
        "type": "str",
        "label": "Zilliz Cloud 地址",
        "description": "填了就走 Zilliz Cloud 云托管（省本地内存），留空走本地 Milvus。Zilliz Cloud 连不上自动降级到本地",
    },
    "MILVUS_TOKEN": {
        "group": "system",
        "type": "str", "sensitive": True,
        "label": "Zilliz Cloud Token",
        "description": "Zilliz Cloud 控制台 → API Keys 创建，仅 Zilliz Cloud 模式生效",
    },
    "MILVUS_SUMMARIES_COLLECTION": {
        "group": "system",
        "type": "str",
        "label": "摘要向量集合",
        "description": "切换后自动重连",
    },
    "MILVUS_SUBQUESTIONS_COLLECTION": {
        "group": "system",
        "type": "str",
        "label": "子问题向量集合",
        "description": "切换后自动重连",
    },
    "MILVUS_CHUNKS_COLLECTION": {
        "group": "system",
        "type": "str",
        "label": "原文向量集合",
        "description": "切换后自动重连",
    },
    "STORAGE_TYPE": {
        "group": "system",
        "type": "enum", "enum": ["local", "oss"],
        "label": "文件存储类型",
        "description": "local 本地 / oss 阿里云 OSS（需已配置 OSS 参数）",
    },
    "LOG_CONSOLE_LEVEL": {
        "group": "system",
        "type": "enum", "enum": [10, 20, 30, 40],
        "label": "控制台日志级别",
        "description": "10=DEBUG 20=INFO 30=WARNING 40=ERROR",
    },
    "LOG_FILE_LEVEL": {
        "group": "system",
        "type": "enum", "enum": [10, 20, 30, 40],
        "label": "文件日志级别",
        "description": "10=DEBUG 20=INFO 30=WARNING 40=ERROR",
    },
    "ACCESS_TOKEN_EXPIRE_MINUTES": {
        "group": "system",
        "type": "int", "min": 1, "max": 10080,
        "label": "登录 Token 有效期",
        "description": "单位：分钟，对后续登录生效",
    },

    # ── 自进化记忆（文档 06，立即生效） ──
    "FAQ_HIT_THRESHOLD": {
        "group": "evolving",
        "type": "float", "min": 0.5, "max": 1.0,
        "label": "FAQ 直返阈值",
        "description": "FAQ 召回直返的相似度阈值（宁漏勿错，默认 0.9，另有 LLM 二次确认）",
    },
    "FAQ_DEDUP_SIMILARITY": {
        "group": "evolving",
        "type": "float", "min": 0.5, "max": 1.0,
        "label": "FAQ 判重阈值",
        "description": "同一 KB 内补全问题相似度 ≥ 此值时聚合到已有记忆（hit_count 累加），默认 0.95",
    },
    "FAQ_HEAT_HALF_LIFE_DAYS": {
        "group": "evolving",
        "type": "float", "min": 0.5, "max": 90,
        "label": "热度半衰期（天）",
        "description": "FAQ 热度时间衰减半衰期，heat = hit_count × 0.5^(天数/半衰期)",
    },
    "FAQ_DISTILL_THRESHOLD_PRIVATE": {
        "group": "evolving",
        "type": "int", "min": 1, "max": 100,
        "label": "私有库蒸馏阈值",
        "description": "私有 KB（含克隆版）中 candidate 命中次数达到此值自动升格 active",
    },
    "FAQ_DISTILL_THRESHOLD_SHARED": {
        "group": "evolving",
        "type": "int", "min": 1, "max": 100,
        "label": "共享库蒸馏阈值",
        "description": "自己分享出去的共享 KB 中 candidate 升格阈值（污染面更大，默认 3）",
    },

    # ── API Keys / 密钥 ──
    "LITELLM_API_KEY": {
        "group": "api_keys",
        "type": "str", "sensitive": True,
        "label": "LiteLLM API Key",
        "description": "LLM 代理密钥（对话 / 嵌入 / 重排）",
    },
    "MINERU_BASE_URL": {
        "group": "api_keys",
        "type": "str",
        "label": "MinerU API 地址",
        "description": "PDF 解析服务地址",
    },
    "MINERU_API_KEY": {
        "group": "api_keys",
        "type": "str", "sensitive": True,
        "label": "MinerU API Key",
        "description": "PDF 解析服务密钥",
    },
    "LANGFUSE_PUBLIC_KEY": {
        "group": "api_keys",
        "type": "str", "sensitive": True,
        "label": "Langfuse Public Key",
        "description": "追踪服务公钥",
    },
    "LANGFUSE_SECRET_KEY": {
        "group": "api_keys",
        "type": "str", "sensitive": True,
        "label": "Langfuse Secret Key",
        "description": "追踪服务密钥",
    },
    "LANGFUSE_HOST": {
        "group": "api_keys",
        "type": "str",
        "label": "Langfuse 地址",
        "description": "追踪服务地址",
    },
    "POSTGRES_PASSWORD": {
        "group": "api_keys",
        "type": "str", "sensitive": True,
        "label": "PostgreSQL 密码",
        "description": "修改后自动重连数据库",
    },
    "ELASTICSEARCH_PASSWORD": {
        "group": "api_keys",
        "type": "str", "sensitive": True,
        "label": "Elasticsearch 密码",
        "description": "仅 elasticsearch 搜索模式生效",
    },
    "OSS_ENDPOINT": {
        "group": "api_keys",
        "type": "str",
        "label": "OSS Endpoint",
        "description": "阿里云 OSS 服务地址（STORAGE_TYPE=oss 时生效）",
    },
    "OSS_ACCESS_KEY_ID": {
        "group": "api_keys",
        "type": "str", "sensitive": True,
        "label": "OSS AccessKey ID",
        "description": "STORAGE_TYPE=oss 时生效",
    },
    "OSS_ACCESS_KEY_SECRET": {
        "group": "api_keys",
        "type": "str", "sensitive": True,
        "label": "OSS AccessKey Secret",
        "description": "STORAGE_TYPE=oss 时生效",
    },
    "OSS_BUCKET_NAME": {
        "group": "api_keys",
        "type": "str",
        "label": "OSS Bucket",
        "description": "STORAGE_TYPE=oss 时生效",
    },
    "OSS_PREFIX": {
        "group": "api_keys",
        "type": "str",
        "label": "OSS 前缀",
        "description": "对象存储目录前缀",
    },
}


# ── 只读配置（重启生效） ────────────────────────────────────
READONLY_CONFIGS: Dict[str, dict] = {
    "HOST": {"label": "服务监听地址", "restart_required": True},
    "PORT": {"label": "服务端口", "restart_required": True},
    "SECRET_KEY": {"label": "JWT 签名密钥", "restart_required": True},
}


# ── 应用钩子（在 set_runtime 之后执行） ────────────────────

def _reset_reranker() -> None:
    """重置 Reranker 实例。"""
    from services.reranker import reset_reranker
    reset_reranker()
    logger.info("[RuntimeConfig] Reranker 实例已重置")


def _reset_agents() -> None:
    """重置 Agent 实例缓存，下次请求按新配置重建。"""
    try:
        from agent.registry import get_registry
        registry = get_registry()
        if hasattr(registry, "_adapters") and registry._adapters:
            registry.reset()
            logger.info("[RuntimeConfig] Agent 实例已重置，下次请求按需重建")
    except Exception as e:
        logger.warning(f"[RuntimeConfig] Agent 重置失败: {e}")


def _rebuild_search_client(app_state: Dict[str, Any]) -> None:
    """根据 SEARCH_BACKEND 重建搜索引擎实例并刷新 app.state。"""
    from services.bm25_client import get_search_client, get_backend_type, reset_search_client
    reset_search_client()
    client = get_search_client()
    if get_backend_type() == "bm25":
        count = client.load_from_database()
        logger.info(f"[RuntimeConfig] BM25 索引重建完成，共 {count} 条 chunk")
    app_state["search_client"] = client
    logger.info(f"[RuntimeConfig] 搜索引擎已切换: {get_backend_type()}")


def _rebuild_milvus_client(app_state: Dict[str, Any]) -> None:
    """按新 Milvus 配置重建客户端并刷新 app.state。"""
    from services.milvus_client import MilvusClient
    old = app_state.get("milvus_client")
    if old is not None and hasattr(old, "close"):
        try:
            old.close()
        except Exception as e:
            logger.warning(f"[RuntimeConfig] 关闭旧 Milvus 连接失败: {e}")
    new_client = MilvusClient()
    app_state["milvus_client"] = new_client
    logger.info("[RuntimeConfig] Milvus 客户端已重建")


def _reconnect_db() -> None:
    """按新数据库配置重连（POSTGRES_PASSWORD 热改）。"""
    from services.database import db
    db.close()
    if not db.connect():
        raise RuntimeError("PostgreSQL 重连失败，请检查密码与连接配置")
    logger.info("[RuntimeConfig] PostgreSQL 连接已重建")


def _apply_log_levels() -> None:
    """把当前所有 logger 的 handler 级别同步为运行时值。"""
    console_level = get_runtime("LOG_CONSOLE_LEVEL", 20)
    file_level = get_runtime("LOG_FILE_LEVEL", 10)
    for name in list(logging.Logger.manager.loggerDict):
        lg = logging.Logger.manager.loggerDict[name]
        if not isinstance(lg, logging.Logger):
            continue
        for h in lg.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setLevel(int(console_level))
            elif isinstance(h, logging.FileHandler):
                h.setLevel(int(file_level))
    logger.info(f"[RuntimeConfig] 日志级别已更新: console={console_level}, file={file_level}")


# 配置项 → 应用钩子映射（多个 key 共用钩子）
_APPLY_HANDLERS: Dict[str, Callable[[Dict[str, Any]], None]] = {
    "RERANKER_TYPE": lambda st: _reset_reranker(),
    "LLM_RERANKER_MAX_TOKENS": lambda st: _reset_reranker(),
    "DEFAULT_MODEL": lambda st: (_reset_reranker(), _reset_agents()),
    "EMBEDDING_MODEL": lambda st: (_reset_reranker(), _reset_agents()),
    "LITELLM_BASE_URL": lambda st: (_reset_reranker(), _reset_agents()),
    "LITELLM_API_KEY": lambda st: (_reset_reranker(), _reset_agents()),
    "LLM_TEMPERATURE_DEFAULT": lambda st: _reset_agents(),
    "LLM_TEMPERATURE_ANSWER": lambda st: _reset_agents(),
    "LLM_TEMPERATURE_GREETING": lambda st: _reset_agents(),
    "SESSION_MAX_HISTORY": lambda st: _reset_agents(),
    "SESSION_CONTEXT_WINDOW": lambda st: _reset_agents(),
    "SEARCH_BACKEND": _rebuild_search_client,
    "MILVUS_HOST": _rebuild_milvus_client,
    "MILVUS_PORT": _rebuild_milvus_client,
    "MILVUS_URI": _rebuild_milvus_client,
    "MILVUS_TOKEN": _rebuild_milvus_client,
    "MILVUS_DB_NAME": _rebuild_milvus_client,
    "MILVUS_SUMMARIES_COLLECTION": _rebuild_milvus_client,
    "MILVUS_SUBQUESTIONS_COLLECTION": _rebuild_milvus_client,
    "MILVUS_CHUNKS_COLLECTION": _rebuild_milvus_client,
    "LOG_CONSOLE_LEVEL": lambda st: _apply_log_levels(),
    "LOG_FILE_LEVEL": lambda st: _apply_log_levels(),
    "POSTGRES_PASSWORD": lambda st: _reconnect_db(),
    "ELASTICSEARCH_PASSWORD": lambda st: _reset_es_client(),
}


def _reset_es_client() -> None:
    """重置 Elasticsearch 客户端单例。"""
    try:
        from services.elasticsearch_client import reset_es_client
        reset_es_client()
        logger.info("[RuntimeConfig] Elasticsearch 客户端已重置")
    except Exception as e:
        logger.warning(f"[RuntimeConfig] Elasticsearch 重置失败: {e}")


def apply_config_change(key: str, app_state: Dict[str, Any]) -> None:
    """执行配置变更后的应用钩子（可选的组件重建）。"""
    handler = _APPLY_HANDLERS.get(key)
    if handler is None:
        return
    handler(app_state)


# ── 设置页写盘持久化（backend/.env）──────────────────────────

def _env_file_path() -> str:
    """backend/.env 的绝对路径。"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def _read_env_lines() -> list:
    """读取 .env 全部行。"""
    path = _env_file_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def _write_env_lines(lines: list) -> None:
    """写回 .env。"""
    path = _env_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _detect_newline() -> str:
    """探测 .env 现有的换行风格，保持文件一致。"""
    for ln in _read_env_lines():
        if ln.endswith("\r\n"):
            return "\r\n"
    return "\n"


def persist_to_env(key: str, value: Any) -> None:
    """把运行时配置写回 backend/.env，保证重启后仍生效。

    规则：
      - 已有 KEY= 行 → 只替换值，保留行内注释
      - 没有 → 追加到文件末尾
    """
    lines = _read_env_lines()
    newline = _detect_newline()
    pattern = re.compile(rf"^({re.escape(key)}\s*=\s*)([^#]*?)(\s*#.*)?$")
    matched = False
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            lines[i] = f"{m.group(1)}{value}{m.group(3) or ''}{newline}"
            matched = True
            break
    if not matched:
        lines.append(f"{key}={value}{newline}")
    _write_env_lines(lines)
    logger.info(f"[RuntimeConfig] 已持久化 {key} 到 .env")


def remove_from_env(key: str) -> None:
    """从 backend/.env 删除某配置项（“清除”操作使用，恢复代码默认值）。"""
    lines = _read_env_lines()
    pattern = re.compile(rf"^({re.escape(key)}\s*=\s*).*$")
    new_lines = [ln for ln in lines if not pattern.match(ln)]
    if len(new_lines) != len(lines):
        _write_env_lines(new_lines)
        logger.info(f"[RuntimeConfig] 已从 .env 移除 {key}")


def get_config_meta() -> Dict[str, Any]:
    """组装全部配置元信息 + 当前值（sensitive 项不回显明文）。"""
    from config import settings

    writable: Dict[str, dict] = {}
    for key, meta in WRITABLE_CONFIGS.items():
        current = get_runtime(key, None)
        if current is None:
            current = getattr(settings, key, "")
        item = {
            **meta,
            "writable": True,
        }
        if meta.get("sensitive"):
            # 敏感项只返回是否已设置，不回显明文
            item["has_value"] = bool(current)
            item["current"] = ""
        else:
            item["current"] = current
        writable[key] = item

    readonly: Dict[str, dict] = {}
    for key, meta in READONLY_CONFIGS.items():
        if meta.get("hidden"):
            continue
        readonly[key] = {
            **meta,
            "current": getattr(settings, key, ""),
            "writable": False,
        }

    return {
        "groups": GROUPS,
        "writable": writable,
        "readonly": readonly,
    }


def validate_value(key: str, value: Any) -> Optional[str]:
    """校验单个配置值，返回错误信息或 None。"""
    meta = WRITABLE_CONFIGS.get(key)
    if not meta:
        return f"未知配置项: {key}"

    if meta["type"] == "float":
        try:
            v = float(value)
        except (TypeError, ValueError):
            return f"{key} 需要浮点数"
        if v < meta["min"] or v > meta["max"]:
            return f"{key} 取值范围 [{meta['min']}, {meta['max']}]"
    elif meta["type"] == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            return f"{key} 需要整数"
        if v < meta["min"] or v > meta["max"]:
            return f"{key} 取值范围 [{meta['min']}, {meta['max']}]"
    elif meta["type"] == "enum":
        # enum 值可能是 int（日志级别），统一字符串比较
        if str(value) not in [str(v) for v in meta["enum"]]:
            return f"{key} 可选值: {', '.join(str(v) for v in meta['enum'])}"
    elif meta["type"] == "csv":
        # 逗号分隔多值（文档 03）：逐项校验合法性，空串 = 全关（合法）
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
        allowed = [str(v) for v in meta.get("enum", [])]
        bad = [p for p in parts if p not in allowed]
        if bad:
            return f"{key} 含非法值: {', '.join(bad)}（可选: {', '.join(allowed)}，留空=全关）"

    return None


def normalize_value(key: str, value: Any) -> Any:
    """把输入值转为目标类型（int/float/str/csv 规范化）。"""
    meta = WRITABLE_CONFIGS.get(key, {})
    if meta.get("type") == "int":
        return int(value)
    if meta.get("type") == "float":
        return float(value)
    if meta.get("type") == "enum":
        # 枚举值是整数时（如日志级别 10/20/30/40）保留 int，避免 setLevel('30') 报错
        enum_values = meta.get("enum", [])
        if enum_values and all(isinstance(v, int) for v in enum_values):
            return int(value)
        return str(value)
    if meta.get("type") == "csv":
        # 规范化：去空格、去重保序；空输入 → 空串（全关语义）
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
        seen = []
        for p in parts:
            if p not in seen:
                seen.append(p)
        return ",".join(seen)
    return str(value)
