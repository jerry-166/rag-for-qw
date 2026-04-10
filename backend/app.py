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
from services.elasticsearch_client import es_client

# 导入api路由
from api import api_router

# 初始化日志记录器
logger = init_logger(__name__)



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

    # 初始化存储实例
    app.state['storage'] = get_storage()
    logger.info(f"存储实例初始化完成，存储类型: {settings.STORAGE_TYPE}")

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
