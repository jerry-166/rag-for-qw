from fastapi import APIRouter

api_router = APIRouter()

from .auth import router as auth_router
from .knowledge_bases import router as knowledge_bases_router
from .documents import router as documents_router
from .files import router as files_router
from .processing import router as processing_router
from .search import router as search_router
from .stats import router as stats_router
from .agent import router as agent_router
from .evaluation import router as evaluation_router

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(knowledge_bases_router, prefix="/knowledge-bases", tags=["knowledge-bases"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(files_router, prefix="", tags=["files"])
api_router.include_router(processing_router, prefix="/process", tags=["processing"])
api_router.include_router(search_router, tags=["search"])
api_router.include_router(stats_router, prefix="/stats", tags=["stats"])
api_router.include_router(agent_router, tags=["agent"])
api_router.include_router(evaluation_router, tags=["evaluation"])
