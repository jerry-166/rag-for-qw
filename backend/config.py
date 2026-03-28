import os
import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler


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

    # MinerU API配置
    MINERU_BASE_URL: str = os.getenv("MINERU_BASE_URL", "https://mineru.net")
    MINERU_API_KEY: str = os.getenv("MINERU_API_KEY", "")

    # LiteLLM配置
    LITELLM_BASE_URL: str = os.getenv("BASE_URL", "http://localhost:4000")
    LITELLM_API_KEY: str = os.getenv("API_KEY", "")

    # 模型配置
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "github_copilot/text-embedding-ada-002")
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gpt-4o")

    # Milvus配置
    MILVUS_HOST: str = os.getenv("MILVUS_HOST", "localhost")
    MILVUS_PORT: str = os.getenv("MILVUS_PORT", "19530")
    MILVUS_DB_NAME: str = os.getenv("MILVUS_DB_NAME", "rag_test")
    MILVUS_SUMMARIES_COLLECTION: str = os.getenv("MILVUS_SUMMARIES_COLLECTION", "chunk_summaries")
    MILVUS_SUBQUESTIONS_COLLECTION: str = os.getenv("MILVUS_SUBQUESTIONS_COLLECTION", "chunk_subquestions")

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

    class Config:
        env_file = ".env"
        case_sensitive = True


# 创建配置实例
settings = Settings()


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
    file_handler.setLevel(settings.LOG_FILE_LEVEL)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    
    # 设置控制台日志格式（简洁格式）
    console_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(settings.LOG_CONSOLE_LEVEL)  # 控制台只显示INFO及以上级别
    
    # 添加处理器到logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
