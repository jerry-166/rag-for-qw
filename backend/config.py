import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

# 显式加载 .env 文件到系统环境变量，确保所有 os.getenv() 都能读取到
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)


class Settings(BaseSettings):
    """配置类"""
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8003"))

    # 应用配置
    APP_NAME: str = "RAG System API"
    APP_VERSION: str = "1.0.0"

    # 存储配置
    TEMP_DIR: Path = Path("temp")
    OUTPUT_DIR: Path = Path("output")
    STORAGE_TYPE: str = os.getenv("STORAGE_TYPE", "local")  # 存储类型：local 或 oss
    DOC_STORAGE_DIR: Path = Path("data/doc_storage")  # 本地存储根目录
    
    # OSS配置
    OSS_ENDPOINT: str = os.getenv("OSS_ENDPOINT", "")
    OSS_ACCESS_KEY_ID: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    OSS_ACCESS_KEY_SECRET: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    OSS_BUCKET_NAME: str = os.getenv("OSS_BUCKET_NAME", "")
    OSS_PREFIX: str = os.getenv("OSS_PREFIX", "docs/")

    # MinerU API配置
    MINERU_BASE_URL: str = os.getenv("MINERU_BASE_URL", "https://mineru.net")
    MINERU_API_KEY: str = os.getenv("MINERU_API_KEY", "")

    # LiteLLM配置
    LITELLM_BASE_URL: str = os.getenv("BASE_URL", "http://localhost:4000")
    LITELLM_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", os.getenv("LITELLM_API_KEY", ""))

    # 模型配置
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "github_copilot/text-embedding-ada-002")
    # 分离：embedding 用 DashScope text-embedding-v4（dim=1536），LLM 用智谱 GLM-4-Flash
    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    EMBEDDING_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", os.getenv("EMBEDDING_API_KEY", ""))
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gpt-4o")

    # Milvus配置
    MILVUS_HOST: str = os.getenv("MILVUS_HOST", "localhost")
    MILVUS_PORT: str = os.getenv("MILVUS_PORT", "19530")
    MILVUS_DB_NAME: str = os.getenv("MILVUS_DB_NAME", "rag_system")
    # Zilliz Cloud 配置（云托管 Milvus，留空则用本地 Milvus）
    # 设置 MILVUS_URI 后，milvus_client.py 自动切换到 Zilliz Cloud 连接模式
    MILVUS_URI: str = os.getenv("MILVUS_URI", "")
    MILVUS_TOKEN: str = os.getenv("MILVUS_TOKEN", "")
    MILVUS_SUMMARIES_COLLECTION: str = os.getenv("MILVUS_SUMMARIES_COLLECTION", "chunk_summaries")
    MILVUS_SUBQUESTIONS_COLLECTION: str = os.getenv("MILVUS_SUBQUESTIONS_COLLECTION", "chunk_subquestions")
    MILVUS_CHUNKS_COLLECTION: str = os.getenv("MILVUS_CHUNKS_COLLECTION", "chunk_vectors")  # chunk原文向量集合名
    MILVUS_FAQ_COLLECTION: str = os.getenv("MILVUS_FAQ_COLLECTION", "faq_vectors")  # 06：FAQ 记忆召回集合名
    MILVUS_ENTITIES_COLLECTION: str = os.getenv("MILVUS_ENTITIES_COLLECTION", "entity_vectors")  # 06 Phase 2：实体向量集合名

    # 自进化 RAG（文档 06，Stage 3）
    FAQ_HIT_THRESHOLD: float = float(os.getenv("FAQ_HIT_THRESHOLD", "0.9"))  # FAQ 直返相似度阈值（宁漏勿错）；score 语义按 COSINE，MILVUS_METRIC_TYPE 改非 COSINE 会方向反转，FAQ 召回仅支持 COSINE
    FAQ_DEDUP_SIMILARITY: float = float(os.getenv("FAQ_DEDUP_SIMILARITY", "0.95"))  # 同 KB 判重阈值（≥则聚合 hit_count）
    FAQ_HEAT_HALF_LIFE_DAYS: float = float(os.getenv("FAQ_HEAT_HALF_LIFE_DAYS", "7"))  # 热度半衰期（天）
    FAQ_DISTILL_THRESHOLD_PRIVATE: int = int(os.getenv("FAQ_DISTILL_THRESHOLD_PRIVATE", "2"))  # 私有 KB 蒸馏阈值
    FAQ_DISTILL_THRESHOLD_SHARED: int = int(os.getenv("FAQ_DISTILL_THRESHOLD_SHARED", "3"))  # 自有共享 KB 蒸馏阈值

    # PostgreSQL配置
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "rag_system")

    # 搜索引擎后端选择
    # 'bm25'          → 纯内存 BM25（推荐，零外部依赖，节省内存）
    # 'elasticsearch'  → Elasticsearch（需要 ES 服务）
    SEARCH_BACKEND: str = os.getenv("SEARCH_BACKEND", "bm25")

    # Elasticsearch配置（仅在 SEARCH_BACKEND=elasticsearch 时生效）
    ELASTICSEARCH_HOST: str = os.getenv("ELASTICSEARCH_HOST", "localhost")
    ELASTICSEARCH_PORT: int = int(os.getenv("ELASTICSEARCH_PORT", "9200"))
    ELASTICSEARCH_USER: str = os.getenv("ELASTICSEARCH_USER", "elastic")
    ELASTICSEARCH_PASSWORD: str = os.getenv("ELASTICSEARCH_PASSWORD", "")

    # 处理配置
    MAX_WAIT_TIME: int = int(os.getenv("MAX_WAIT_TIME", "600"))  # 最长等待时间（秒）
    POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "3"))  # 轮询间隔（秒）
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "16"))  # 批处理大小
    MAX_CONCURRENCY: int = int(os.getenv("MAX_CONCURRENCY", "8"))  # 最大并发数
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))  # 嵌入批处理大小
    EMBEDDING_BATCH_FACTOR: int = int(os.getenv("EMBEDDING_BATCH_FACTOR", "4"))  # 嵌入批处理因子

    # 日志配置
    LOG_DIR: Path = Path("logs")  # 日志目录
    LOG_FILE: str = "app.log"  # 日志文件名
    LOG_MAX_BYTES: int = 1024 * 1024 * 5  # 单个日志文件最大5MB
    LOG_BACKUP_COUNT: int = 10  # 保留的历史日志文件总数
    LOG_TIME_ROTATE_WHEN: str = "D"  # 时间轮转单位：D=按天，H=按小时，M=按分钟
    LOG_TIME_ROTATE_INTERVAL: int = 1  # 时间轮转间隔
    LOG_ENCODING: str = "utf-8"  # 日志文件编码
    LOG_CONSOLE_LEVEL: int = logging.INFO  # 控制台日志级别
    LOG_FILE_LEVEL: int = logging.DEBUG  # 文件日志级别
    
    # Reranker 配置
    RERANKER_TYPE: str = os.getenv("RERANKER_TYPE", "cross_encoder")  # llm / cross_encoder / cohere / none
    RERANKER_MODEL: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
    # Cohere 云端 rerank（替换本地 BGE 避 torch 超订阅；RERANKER_TYPE=cohere 时生效）
    COHERE_API_KEY: str = os.getenv("COHERE_API_KEY", "")
    COHERE_MODEL: str = os.getenv("COHERE_MODEL", "rerank-v3.5")  # rerank-v3.5 多语言

    # RAG 检索配置
    RETRIEVAL_MIN_SCORE: float = float(os.getenv("RETRIEVAL_MIN_SCORE", "0.3"))  # 检索结果最低相关度阈值（0-1），低于此分数的结果将被丢弃
    RETRIEVAL_TOP_K: int = int(os.getenv("RETRIEVAL_TOP_K", "5"))  # 检索默认 Top-K 条数

    # 文档切分配置（document_processor.py / services/chunking/）
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "400"))  # 递归切割器目标大小
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))  # 切割重叠字符数
    MIN_CHUNK_SIZE: int = int(os.getenv("MIN_CHUNK_SIZE", "100"))  # 短 chunk 合并阈值
    MAX_CHUNK_SIZE: int = int(os.getenv("MAX_CHUNK_SIZE", "800"))  # 长 chunk 二次切割阈值
    # 切割策略（文档 02）：auto=内容探测（默认，=历史行为）/ markdown / recursive
    CHUNK_STRATEGY: str = os.getenv("CHUNK_STRATEGY", "auto")
    # 启用的增强器（文档 03）：逗号分隔，可选 sub_question / summary；空 = 全关（纯原文 RAG）
    ENABLED_ENHANCERS: str = os.getenv("ENABLED_ENHANCERS", "sub_question,summary")

    # 向量索引与检索参数（milvus_client.py / rag_tools.py / retrieval_strategies.py）
    MILVUS_NPROBE: int = int(os.getenv("MILVUS_NPROBE", "10"))  # IVF 搜索探针数
    MILVUS_NLIST: int = int(os.getenv("MILVUS_NLIST", "128"))  # IVF_FLAT 聚类中心数（仅建索引时生效）
    MILVUS_METRIC_TYPE: str = os.getenv("MILVUS_METRIC_TYPE", "COSINE")  # 距离度量
    MILVUS_TIMEOUT: float = float(os.getenv("MILVUS_TIMEOUT", "30"))  # 单次向量检索超时秒数（Zilliz serverless 冷启动可能远超 pymilvus 默认 10s）
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1536"))  # 向量维度（换模型需同步）
    RRF_K: int = int(os.getenv("RRF_K", "60"))  # 倒数排名融合平滑常数
    DEFAULT_RETRIEVAL_MODE: str = os.getenv("DEFAULT_RETRIEVAL_MODE", "advanced")  # 默认检索模式: native|advanced|hybrid
    NUM_SUBQUESTIONS: int = int(os.getenv("NUM_SUBQUESTIONS", "3"))  # 查询扩展子问题数
    GRAPH_RELATION_MIN_SCORE: float = float(os.getenv("GRAPH_RELATION_MIN_SCORE", "0.5"))  # LLM 关系重排保留阈值
    GRAPH_HOP: int = int(os.getenv("GRAPH_HOP", "1"))  # 图谱检索跳数（默认1）

    # LLM 温度配置（散布在 agent / rag_workflow / reranker）
    LLM_TEMPERATURE_DEFAULT: float = float(os.getenv("LLM_TEMPERATURE_DEFAULT", "0.7"))  # 默认温度
    LLM_TEMPERATURE_ANSWER: float = float(os.getenv("LLM_TEMPERATURE_ANSWER", "0.5"))  # 回答生成温度
    LLM_TEMPERATURE_GREETING: float = float(os.getenv("LLM_TEMPERATURE_GREETING", "0.8"))  # 问候回答温度
    LLM_RERANKER_MAX_TOKENS: int = int(os.getenv("LLM_RERANKER_MAX_TOKENS", "200"))  # LLM Reranker 最大 token

    # 会话与记忆（conversation_manager.py / rag_workflow.py）
    SESSION_MAX_HISTORY: int = int(os.getenv("SESSION_MAX_HISTORY", "10"))  # 每会话最大保留轮数
    SESSION_CONTEXT_WINDOW: int = int(os.getenv("SESSION_CONTEXT_WINDOW", "5"))  # 上下文窗口大小

    # 文档处理（document_processor.py）
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))  # ChatModel 重试次数
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))  # ChatModel 超时（秒）

    # BM25 内存缓存 LRU 双上限（01 §7.1）
    BM25_CACHE_BUCKETS: int = int(os.getenv("BM25_CACHE_BUCKETS", "16"))  # BM25Okapi 模型桶数上限
    BM25_CACHE_MAX_CHUNKS: int = int(os.getenv("BM25_CACHE_MAX_CHUNKS", "100000"))  # 所有桶缓存 chunk 总量上限

    # 认证配置
    SECRET_KEY: str = os.getenv("SECRET_KEY", "lrj669761379123")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    class Config:
        env_file = Path(__file__).parent / ".env"
        case_sensitive = True
        extra = "allow"  # 允许额外字段


# 创建配置实例
settings = Settings()

# ── 运行时覆盖层（用于 /api/settings 动态修改，不重启生效）──
_runtime_overrides: dict = {}
_env_baseline: dict = {}

def get_runtime(key: str, default=None):
    """优先返回运行时覆盖值，否则 fallback 到 settings 属性。"""
    # LLM 智谱 GLM-4-Flash（系统环境变量 LITELLM_API_KEY 是旧 litellm key，绕过用 ZHIPU_API_KEY）
    if key == "LITELLM_API_KEY" and key not in _runtime_overrides:
        zhipu = os.getenv("ZHIPU_API_KEY")
        if zhipu:
            return zhipu
    # embedding DashScope text-embedding-v4（分离：embedding 用 DASHSCOPE_API_KEY）
    if key == "EMBEDDING_API_KEY" and key not in _runtime_overrides:
        ds = os.getenv("DASHSCOPE_API_KEY")
        if ds:
            return ds
    if key in _runtime_overrides:
        return _runtime_overrides[key]
    return getattr(settings, key, default)

def set_runtime(key: str, value):
    """
    写入运行时覆盖值。

    同时同步到进程环境变量，确保直接使用 os.getenv() 的模块
    （tracing / elasticsearch 等）也能立即读到新值。
    """
    if key not in _runtime_overrides:
        _env_baseline[key] = os.environ.get(key)
    _runtime_overrides[key] = value
    os.environ[key] = str(value)

def clear_runtime(key: str):
    """清除运行时覆盖，恢复为静态配置值（并还原进程环境变量）。"""
    if key in _runtime_overrides:
        baseline = _env_baseline.pop(key, None)
        _runtime_overrides.pop(key, None)
        if baseline is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = baseline


# 自定义双轮转处理器（继承ConcurrentTimedRotatingFileHandler，扩展大小检查）
class DualRotateFileHandler(ConcurrentTimedRotatingFileHandler):
    def __init__(self, filename, maxBytes, *args, **kwargs):
        super().__init__(filename, *args, **kwargs)
        self.maxBytes = maxBytes  # 新增大小轮转阈值

    def emit(self, record):
        """重写emit方法：写入前检查文件大小，超过则主动触发轮转"""
        # 检查当前日志文件大小是否超过阈值（若文件存在且大小超标）
        if os.path.exists(self.baseFilename) and os.path.getsize(self.baseFilename) >= self.maxBytes:
            # 主动触发轮转（调用父类的轮转方法）
            self.doRollover()
        # 执行原始的日志写入逻辑
        super().emit(record)


# 初始化日志记录器
def init_logger(name: str = None) -> logging.Logger:
    """
    初始化双轮转日志记录器，同时输出到文件和控制台
    
    Args:
        name: 日志记录器名称，默认为None（使用根记录器）
    
    Returns:
        配置好的日志记录器
    """
    # 获取logger实例
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # 清空默认处理器，避免重复输出
    logger.handlers = []
    
    # 确保日志目录存在
    settings.LOG_DIR.mkdir(exist_ok=True)
    log_file = settings.LOG_DIR / settings.LOG_FILE
    
    # 创建文件处理器（双轮转）
    file_handler = DualRotateFileHandler(
        filename=str(log_file),
        maxBytes=settings.LOG_MAX_BYTES,  # 大小轮转：5MB
        when=settings.LOG_TIME_ROTATE_WHEN,  # 时间轮转：按天
        interval=settings.LOG_TIME_ROTATE_INTERVAL,  # 每天轮转1次
        backupCount=settings.LOG_BACKUP_COUNT,  # 保留10个历史文件
        encoding=settings.LOG_ENCODING,  # 指定编码
        utc=False  # 使用本地时间（True=UTC时间）
    )
    
    # 设置文件日志格式（包含毫秒，方便精准排序）
    file_formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d - %(name)s - %(process)d - %(thread)d - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"  # 统一时间格式
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(get_runtime('LOG_FILE_LEVEL', settings.LOG_FILE_LEVEL))
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    
    # 设置控制台日志格式（简洁格式）
    console_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(get_runtime('LOG_CONSOLE_LEVEL', settings.LOG_CONSOLE_LEVEL))  # 控制台只显示INFO及以上级别
    
    # 添加处理器到logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
