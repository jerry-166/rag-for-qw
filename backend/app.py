import uuid
import shutil
import time
import asyncio
from pathlib import Path
from datetime import timedelta
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status, Form, Response, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from config import settings, init_logger, get_runtime
# 01-B：document_processor 顶层拉起 sentence_transformers（~15s import），且 app.py 未直接使用，延迟导入
from services.milvus_client import MilvusClient
# 圈6：PDFParser 仅 api/files.py 使用（请求路径懒加载即可），此处顶层 import 徒增 ~0.2s（requests 链）
from services.database import db
from services.auth import get_password_hash, verify_password, create_access_token, get_current_user, check_permission
from services.storage import get_storage
from services.bm25_client import get_search_client, get_backend_type

# 导入api路由
from api import api_router

# 初始化日志记录器
logger = init_logger(__name__)


async def _preheat_milvus(app_ref):
    """01-B：Milvus 连接后台预热（同步 connect 移入线程池，不阻塞 HTTP 启动）。"""
    from services.startup import readiness
    loop = asyncio.get_running_loop()
    try:
        ok = await loop.run_in_executor(None, app_ref.state['milvus_client'].connect)
        readiness.mark('milvus', None if ok else 'Milvus 连接失败（Zilliz Cloud 与本地均不可用）')
    except Exception as e:
        readiness.mark('milvus', str(e))


async def _preheat_search(app_ref):
    """01-B：搜索引擎（BM25 语料加载 / ES 连接）后台预热。"""
    from services.startup import readiness
    loop = asyncio.get_running_loop()
    try:
        client = get_search_client()
        backend_type = get_backend_type()
        if backend_type == 'bm25':
            count = await loop.run_in_executor(None, client.load_from_database)
            logger.info(f"BM25 索引加载完成，共 {count} 条 chunk")
            # 01 §7.1：内存观测汇总（分桶 chunk 分布）
            try:
                for key, docs in client._corpus.items():
                    logger.info(
                        f"BM25 分桶: bucket={key}, chunks={len(docs)}"
                    )
            except Exception:
                pass
        else:
            logger.info(f"搜索引擎已就绪: {backend_type}")
        app_ref.state['search_client'] = client
        readiness.mark('search')
    except Exception as e:
        readiness.mark('search', str(e))


def _preheat_agents_sync(app_ref):
    """同步预热部分（imports + registry 构建较重，放线程池避免阻塞事件循环）。"""
    preheat = getattr(app_ref.state, 'agent_preheat', None)
    if preheat:
        preheat['status'] = 'warming'
        preheat['started_at'] = time.time()
    logger.info("[Agent预热] 开始后台预热所有 Agent...")

    from agent.registry import setup_registry, AgentType
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


async def _preheat_agents(app_ref):
    """01-B：Agent 预热（同步部分走线程池 + reranker 异步加载），不阻塞事件循环。"""
    from services.startup import readiness
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _preheat_agents_sync, app_ref)

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

        preheat = getattr(app_ref.state, 'agent_preheat', None)
        if preheat:
            preheat['status'] = 'ready'
            preheat['finished_at'] = time.time()
        readiness.mark('agents')

    except Exception as e:
        logger.error(f"[Agent预热] 预热失败: {e}")
        preheat = getattr(app_ref.state, 'agent_preheat', None)
        if preheat:
            preheat['status'] = 'error'
            preheat['error'] = str(e)
            preheat['finished_at'] = time.time()
        readiness.mark('agents', str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    import asyncio  # 圈6：lifespan 内多处 create_task 使用；置于函数开头避免 UnboundLocalError
    # 启动时
    logger.info("正在初始化应用...")

    # 初始化应用状态
    app.state = {}

    # 初始化Milvus客户端（01-B：构造不再阻塞连接，连接移入后台预热）
    app.state['milvus_client'] = MilvusClient()

    # ── 01-B：readiness 信号（milvus / search / agents 三组件）──
    from services.startup import readiness as _readiness
    for _name in ('milvus', 'search', 'agents'):
        _readiness.set_pending(_name)
    # 搜索客户端占位：BM25 构造零成本可即时创建；ES 构造含 ping（最长数秒）留 None 待预热填充
    if get_backend_type() == 'bm25':
        app.state['search_client'] = get_search_client()
    else:
        app.state['search_client'] = None

    # 初始化存储实例
    app.state['storage'] = get_storage()
    logger.info(f"存储实例初始化完成，存储类型: {settings.STORAGE_TYPE}")

    # ── 初始化追踪后端（Phoenix / Langfuse / None）──
    # 圈6：实测同步初始化 ~1.8s（langfuse import + 客户端构建 + auth_check 网络验证），
    # 移入后台任务不阻塞 HTTP 启动；get_callbacks() 按调用自建 handler，不依赖此步完成。
    app.state['tracer_info'] = {"backend": "initializing", "initialized": False}

    async def _setup_tracing_bg():
        loop = asyncio.get_running_loop()
        try:
            from evaluation.tracing import setup_tracing, get_tracer_info
            # 同步初始化（含 auth_check 网络请求）放线程池，避免阻塞事件循环（否则仍会挡住首个 HTTP 200）
            tracing_result = await loop.run_in_executor(None, setup_tracing)
            app.state['tracer_info'] = get_tracer_info()
            logger.info(f"[Tracing] 初始化完成: backend={tracing_result['backend']}, status={tracing_result['status']}")
            if 'url' in tracing_result:
                logger.info(f"[Tracing] Phoenix UI → {tracing_result['url']}")
            elif 'host' in tracing_result:
                logger.info(f"[Tracing] Langfuse Host → {tracing_result['host']}")
        except Exception as e:
            logger.warning(f"[Tracing] 初始化失败（不影响主流程）: {e}")
            app.state['tracer_info'] = {"backend": "none", "initialized": False, "error": str(e)}
    asyncio.create_task(_setup_tracing_bg())

    # ── Agent 预热状态 ──
    app.state['agent_preheat'] = {
        'status': 'pending',
        'started_at': None,
        'finished_at': None,
        'error': None,
    }

    # ── 启动后台并发预热任务（01-B：不阻塞 HTTP 服务启动）──
    preheat_enabled = str(get_runtime("STARTUP_PREHEAT", "true")).lower() not in ("0", "false", "no")
    if preheat_enabled:
        async def _preheat_all():
            await asyncio.gather(
                _preheat_milvus(app),
                _preheat_search(app),
                _preheat_agents(app),
            )
        asyncio.create_task(_preheat_all())
        logger.info("[预热] 后台并发预热已启动：milvus / search / agents")
    else:
        from services.startup import readiness as _r
        for _name in ('milvus', 'search', 'agents'):
            _r.mark(_name)
        logger.info("[预热] STARTUP_PREHEAT=false，跳过预热（纯懒加载）")

    # ── 审计管道（文档 07）：启动后台批量落库任务 ──
    from services.audit import audit
    audit.start()

    # ── 缓存管理器（文档 08）：启动 60s 周期 stats 审计快照任务 ──
    from services.cache import get_cache_manager
    _cache_snapshot_task = asyncio.create_task(
        get_cache_manager().stats_snapshot_loop())
    logger.info("[Cache] 缓存管理器已启动（stats 快照 60s 周期）")

    yield

    # 关闭时
    logger.info("正在关闭应用...")
    # 缓存快照任务：优雅取消
    _cache_snapshot_task.cancel()
    # 审计管道：优雅停机 flush 队列残留
    await audit.stop()
    logger.info("应用已关闭")


app = FastAPI(lifespan=lifespan)


# ── 审计中间件（文档 07）：request_id 生成/透传 + 非 GET 请求兜底粗记录 ──
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    from services.audit import audit, new_request_id

    # request_id：透传已有 X-Request-ID，否则生成
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    request.state.request_id = request_id

    start = time.time()
    try:
        response = await call_next(request)
    except Exception as e:
        # 异常兜底：即时粗记录（不走队列，直接落库），保证异常请求无漏记
        try:
            from services.database import db
            from datetime import datetime, timezone as _tz
            db.insert_audit_batch([{
                'occurred_at': datetime.now(_tz.utc),
                'user_id': None,
                'action': 'request.error',
                'resource_type': 'request',
                'resource_id': request.url.path,
                'kb_id': None,
                'request_id': request_id,
                'client_ip': request.client.host if request.client else None,
                'user_agent': request.headers.get("user-agent"),
                'detail': {'method': request.method, 'path': request.url.path,
                           'error': str(e)},
            }])
        except Exception as audit_err:
            logger.error(f"[Audit] 异常兜底记录失败: {audit_err}")
        raise

    response.headers["X-Request-ID"] = request_id

    # 兜底粗记录：非 GET 的 /api 请求记录 method/path/status/耗时（与显式事件通过 request_id 关联）
    if request.method != "GET" and request.url.path.startswith("/api"):
        try:
            user_id = getattr(request.state, "audit_user_id", None)
            audit.log(
                'request.write',
                user_id=user_id,
                resource_type='request',
                resource_id=request.url.path,
                request_id=request_id,
                client_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                detail={
                    'method': request.method,
                    'path': request.url.path,
                    'status_code': response.status_code,
                    'duration_ms': round((time.time() - start) * 1000, 2),
                },
            )
        except Exception as e:
            logger.error(f"[Audit] 兜底记录入队失败: {e}")

    return response


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


@app.get("/healthz")
async def healthz():
    """01-B：就绪探针 — 全部预热组件就绪返回 200，否则 503（服务本身已可响应）。"""
    from services.startup import readiness
    snap = readiness.snapshot()
    if readiness.all_ready():
        return {"status": "ok", "components": snap}
    return JSONResponse(status_code=503, content={"status": "not_ready", "components": snap})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
