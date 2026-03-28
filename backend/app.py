import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings, init_logger
from services.document_processor import DocumentProcessor
from services.milvus_client import MilvusClient
from services.pdf_parser import PDFParser

# 初始化日志记录器
logger = init_logger(__name__)

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的前端地址
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 临时存储目录
TEMP_DIR = settings.TEMP_DIR
TEMP_DIR.mkdir(exist_ok=True)


# 数据模型
class ParseRequest(BaseModel):
    file_path: str


class MilvusImportRequest(BaseModel):
    file_id: str


# 支持metadata过滤
class QueryRequest(BaseModel):
    query: str
    limit: int = 5
    metadata_filter: dict = None


# 存储处理结果
processing_results = {}


@app.post("/api/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """上传PDF文件"""
    logger.info(f"开始处理PDF上传请求，文件名: {file.filename}")
    try:
        # 生成唯一文件ID
        file_id = str(uuid.uuid4())
        file_path = TEMP_DIR / f"{file_id}.pdf"

        # 保存文件
        with open(file_path, "wb") as f:
            f.write(await file.read())
        logger.debug(f"文件保存成功: {file_path}")

        # 初始化PDF解析器
        parser = PDFParser()

        # 解析PDF
        result = parser.parse_pdf(file_path)
        logger.debug(f"PDF解析成功，生成Markdown: {result['markdown_path']}")

        # 存储结果
        processing_results[file_id] = {
            "file_path": str(file_path),
            "markdown_path": result["markdown_path"],
            "images_dir": result.get("images_dir"),
            "status": "parsed"
        }

        logger.info(f"PDF上传并解析成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "status": "success",
            "markdown_path": result["markdown_path"],
            "message": "PDF上传并解析成功"
        }
    except Exception as e:
        logger.error(f"上传失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@app.get("/api/markdown/{file_id}")
async def get_markdown(file_id: str):
    """获取解析后的Markdown内容"""
    logger.info(f"开始获取Markdown内容，文件ID: {file_id}")
    try:
        if file_id not in processing_results:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        result = processing_results[file_id]
        if result["status"] != "parsed":
            logger.warning(f"文件尚未解析完成，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件尚未解析完成")

        markdown_path = Path(result["markdown_path"])
        if not markdown_path.exists():
            logger.warning(f"Markdown文件未找到，路径: {markdown_path}")
            raise HTTPException(status_code=404, detail="Markdown文件未找到")

        with open(markdown_path, "r", encoding="utf-8") as f:
            content = f.read()

        logger.info(f"获取Markdown内容成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "content": content,
            "status": "success"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Markdown失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取Markdown失败: {str(e)}")


@app.post("/api/process/document/{file_id}")
async def process_document(file_id: str):
    """切分文档并生成子问题和摘要"""
    logger.info(f"开始处理文档，文件ID: {file_id}")
    try:
        if file_id not in processing_results:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        result = processing_results[file_id]
        if result["status"] != "parsed":
            logger.warning(f"文件尚未解析完成，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件尚未解析完成")

        # 初始化文档处理器
        processor = DocumentProcessor()

        # 处理文档
        process_result = processor.process_document(result["markdown_path"])
        logger.debug(f"文档处理完成，生成 {len(process_result['chunks'])} 个段落")

        # 更新处理状态
        processing_results[file_id].update({
            "status": "processed",
            "chunks": process_result["chunks"],
            "sub_questions": process_result["sub_questions"],
            "summaries": process_result["summaries"],  # 不重复，ky为后面的查询简化
            "datas": process_result["datas"]
        })

        chunks_count = len(process_result["chunks"])
        sub_questions_count = sum(len(sq) for sq in process_result["sub_questions"])
        logger.info(f"文档处理成功，文件ID: {file_id}, 段落数: {chunks_count}, 子问题数: {sub_questions_count}")
        return {
            "file_id": file_id,
            "status": "success",
            "chunks_count": chunks_count,
            "sub_questions_count": sub_questions_count,
            "message": "文档处理成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文档处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"文档处理失败: {str(e)}")


@app.get("/api/process/result/{file_id}")
async def get_process_result(file_id: str):
    """获取文档处理结果"""
    logger.info(f"开始获取文档处理结果，文件ID: {file_id}")
    try:
        if file_id not in processing_results:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        result = processing_results[file_id]
        if result["status"] != "processed":
            logger.warning(f"文件尚未处理完成，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件尚未处理完成")

        logger.info(f"获取文档处理结果成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "chunks": result.get("chunks", []),
            "sub_questions": result.get("sub_questions", []),
            "summaries": result.get("summaries", []),
            "status": "success"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取处理结果失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取处理结果失败: {str(e)}")


@app.post("/api/milvus/import/{file_id}")
async def import_to_milvus(file_id: str):
    """将数据导入到Milvus"""
    logger.info(f"开始导入数据到Milvus，文件ID: {file_id}")
    try:
        if file_id not in processing_results:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        result = processing_results[file_id]
        if result["status"] != "processed":
            logger.warning(f"文件尚未处理完成，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件尚未处理完成")

        # 初始化Milvus客户端
        milvus_client = MilvusClient()

        # 导入数据
        import_result = milvus_client.import_data(result["datas"])
        logger.debug(f"数据导入完成: {import_result}")

        # 更新状态
        processing_results[file_id]["milvus_imported"] = True

        logger.info(f"数据导入Milvus成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "status": "success",
            "import_result": import_result,
            "message": "数据导入Milvus成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入Milvus失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导入Milvus失败: {str(e)}")


@app.post("/api/milvus/query")
async def query_milvus(request: QueryRequest):
    """查询Milvus数据"""
    logger.info(f"开始查询Milvus数据，查询内容: {request.query}")
    try:
        # 初始化Milvus客户端
        milvus_client = MilvusClient()

        # 执行查询
        results = milvus_client.query(
            query_text=request.query,
            limit=request.limit,
            metadata_filter=request.metadata_filter
        )
        logger.debug(f"查询完成，返回 {len(results)} 条结果")

        logger.info(f"查询Milvus数据成功")
        return {
            "status": "success",
            "query": request.query,
            "results": results
        }
    except Exception as e:
        logger.error(f"查询失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@app.get("/api/milvus/info")
async def get_milvus_info():
    """获取Milvus集合信息"""
    logger.info("开始获取Milvus集合信息")
    try:
        # 初始化Milvus客户端
        milvus_client = MilvusClient()

        # 获取集合信息
        info = milvus_client.get_collection_info()
        logger.debug(f"获取集合信息: {info}")

        logger.info("获取Milvus集合信息成功")
        return {
            "status": "success",
            "info": info
        }
    except Exception as e:
        logger.error(f"获取Milvus信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取Milvus信息失败: {str(e)}")


@app.get("/")
async def root():
    """根路径"""
    logger.info("访问根路径")
    return {"message": "RAG System API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
