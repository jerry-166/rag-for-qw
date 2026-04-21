import uuid
import shutil
import time
from pathlib import Path
from datetime import timedelta
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from config import settings, init_logger
from services.document_processor import DocumentProcessor
from services.milvus_client import MilvusClient
from services.pdf_parser import PDFParser
from services.database import db
from services.auth import get_password_hash, verify_password, create_access_token, get_current_user, check_permission
from services.storage import get_storage
from services.bm25_client import get_search_client, get_backend_type

# 导入api路由
from api import api_router

# 初始化日志记录器
logger = init_logger(__name__)


async def _preheat_agents(app_ref):
    """
    异步预热所有 Agent（simple / advanced / claw）
    
    在事件循环内运行，避免 Windows 上后台线程文件锁冲突。
    通过 asyncio.create_task 调用，不阻塞请求处理。
    """
    try:
        preheat = getattr(app_ref.state, 'agent_preheat', None)
        if preheat:
            preheat['status'] = 'warming'
            preheat['started_at'] = time.time()
        logger.info("[Agent预热] 开始后台预热所有 Agent...")

        from agent.registry import get_registry, setup_registry, AgentType
        from agent.claw_agent.memory.memory_manager import MemoryManager
        from agent.claw_agent.memory.session_store import SessionStore

        memory_manager = MemoryManager()
        session_store = SessionStore()

        registry = setup_registry(
            claw_memory_manager=memory_manager,
            claw_session_store=session_store,
        )

        # 预热所有三种 Agent
        for at in [AgentType.SIMPLE, AgentType.ADVANCED, AgentType.CLAW]:
            start = time.time()
            registry.get(at)
            elapsed = round((time.time() - start), 2)
            logger.info(f"[Agent预热] {at.value} Agent 预热完成 ({elapsed}s)")

        # 预热 Reranker（CrossEncoder 模型约 5-8 秒，提前加载避免首请求延迟）
        try:
            from services.reranker import get_reranker
            reranker_start = time.time()
            reranker = get_reranker()
            if hasattr(reranker, '_ensure_model_loaded'):
                await reranker._ensure_model_loaded()
                elapsed = round((time.time() - reranker_start), 2)
                logger.info(f"[Agent预热] Reranker 模型预热完成 ({elapsed}s)")
            else:
                logger.info("[Agent预热] Reranker 非模型类型，跳过预热")
        except Exception as e:
            logger.warning(f"[Agent预热] Reranker 预热失败（不影响主流程）: {e}")

        if preheat:
            preheat['status'] = 'ready'
            preheat['finished_at'] = time.time()

    except Exception as e:
        logger.error(f"[Agent预热] 预热失败: {e}")
        preheat = getattr(app_ref.state, 'agent_preheat', None)
        if preheat:
            preheat['status'] = 'error'
            preheat['error'] = str(e)
            preheat['finished_at'] = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("正在初始化应用...")

    # 初始化应用状态
    app.state = {}

    # 初始化Milvus客户端
    app.state['milvus_client'] = MilvusClient()
    logger.info("Milvus客户端初始化完成")

    # 初始化搜索引擎（BM25 或 Elasticsearch）
    search_client = get_search_client()
    app.state['search_client'] = search_client
    backend_type = get_backend_type()

    # 如果是 BM25 模式，从 PG 全量加载索引到内存
    if backend_type == 'bm25':
        chunk_count = search_client.load_from_database()
        logger.info(f"BM25 索引加载完成，共 {chunk_count} 条 chunk")
    else:
        logger.info(f"搜索引擎已就绪: {backend_type}")

    # 初始化存储实例
    app.state['storage'] = get_storage()
    logger.info(f"存储实例初始化完成，存储类型: {settings.STORAGE_TYPE}")

    # ── 初始化追踪后端（Phoenix / Langfuse / None）──
    try:
        from evaluation.tracing import setup_tracing, get_tracer_info
        tracing_result = setup_tracing()
        app.state['tracer_info'] = get_tracer_info()
        logger.info(f"[Tracing] 初始化完成: backend={tracing_result['backend']}, status={tracing_result['status']}")
        if 'url' in tracing_result:
            logger.info(f"[Tracing] Phoenix UI → {tracing_result['url']}")
        elif 'host' in tracing_result:
            logger.info(f"[Tracing] Langfuse Host → {tracing_result['host']}")
    except Exception as e:
        logger.warning(f"[Tracing] 初始化失败（不影响主流程）: {e}")
        app.state['tracer_info'] = {"backend": "none", "initialized": False, "error": str(e)}

    # ── Agent 预热状态 ──
    app.state['agent_preheat'] = {
        'status': 'pending',
        'started_at': None,
        'finished_at': None,
        'error': None,
    }

    # ── 启动后台异步预热任务（不阻塞启动）──
    import asyncio
    asyncio.create_task(_preheat_agents(app))
    logger.info("[Agent预热] 后台预热异步任务已启动（预热全部 Agent）")

    yield

    # 关闭时
    logger.info("正在关闭应用...")
    # 这里可以添加清理逻辑
    logger.info("应用已关闭")


app = FastAPI(lifespan=lifespan)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的前端地址
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册api路由
app.include_router(api_router, prefix="/api")

# 临时存储目录
TEMP_DIR = settings.TEMP_DIR
TEMP_DIR.mkdir(exist_ok=True)

# 输出目录
OUTPUT_DIR = settings.OUTPUT_DIR
OUTPUT_DIR.mkdir(exist_ok=True)



@app.get("/")
async def root():
    """根路径"""
    logger.info("访问根路径")
    return {"message": "RAG System API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
