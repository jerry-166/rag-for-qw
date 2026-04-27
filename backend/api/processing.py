from fastapi import APIRouter, HTTPException, Depends, Request
import time

from config import init_logger, settings
from services.database import db
from services.auth import get_current_user
from services.document_processor import DocumentProcessor, StoredData
from services.milvus_client import MilvusClient
from services.storage import get_storage

logger = init_logger(__name__)
router = APIRouter()


@router.post("/split/{file_id}")
async def split_document(file_id: str, req: Request, current_user=Depends(get_current_user)):
    """MD切割接口"""
    logger.info(f"开始切割文档，文件ID: {file_id}")
    start_time = time.time()
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 只要文件不是处理失败状态，就可以进行文档切割
        if doc["status"] == "failed":
            logger.warning(f"文件处理失败，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件处理失败")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        # 检查数据库中是否已经存在切割结果
        existing_chunks = db.get_document_chunks(file_id)
        if existing_chunks and len(existing_chunks) > 0:
            logger.info(f"文档已切割，直接返回数据库中的切割结果，文件ID: {file_id}")
            chunks = [chunk["content"] for chunk in existing_chunks]
            chunks_count = len(chunks)
            # 计算平均chunk大小
            total_size = sum(len(chunk) for chunk in chunks)
            avg_chunk_size = total_size / chunks_count if chunks_count > 0 else 0
            # 使用数据库中已有的split_time，而不是重新计算
            processing_time_ms = doc.get("split_time") or (time.time() - start_time) * 1000
            return {
                "file_id": file_id,
                "status": "success",
                "chunks": chunks,
                "chunks_count": chunks_count,
                "avg_chunk_size": avg_chunk_size,
                "processing_time_ms": processing_time_ms,
                "message": "文档已切割，直接返回数据库中的切割结果"
            }

        # 初始化文档处理器
        processor = DocumentProcessor()
        storage = get_storage()

        # 读取Markdown内容
        markdown_content = storage.read(doc["enhanced_md_path"])
        if not markdown_content:
            raise HTTPException(status_code=404, detail="Markdown文件未找到")

        # 切割文档
        process_result = processor.split_document(markdown_content)
        logger.debug(f"文档切割完成，生成 {len(process_result['chunks'])} 个段落")

        # 存储文档块到PostgreSQL并索引到Elasticsearch
        chunks = process_result['chunks']
        chunk_ids = []
        for i, chunk in enumerate(chunks):
            # 添加到PostgreSQL
            chunk_id = db.add_document_chunk(
                document_id=file_id,
                chunk_index=i,
                content=chunk,
                metadata={"source": doc["filename"]},
                knowledge_base_id=doc["knowledge_base_id"]
            )
            if chunk_id:
                chunk_ids.append(chunk_id)
                # 索引到搜索引擎（BM25 或 ES）
                search_client = req.app.state['search_client']
                search_client.index_chunk(
                    chunk_id=chunk_id,
                    user_id=current_user["id"],
                    document_id=file_id,
                    knowledge_base_id=doc["knowledge_base_id"],
                    chunk_index=i,
                    content=chunk,
                    metadata={"source": doc["filename"]}
                )

        # 计算处理时间（毫秒）
        processing_time_ms = (time.time() - start_time) * 1000
        # 确保时间不为0，否则存储为NULL
        split_time = processing_time_ms if processing_time_ms > 0.1 else None
        
        # 更新数据库中的文档状态和处理时间
        db.update_document(
            file_id,
            status="chunk_done",
            es_indexed=True,
            split_time=split_time
        )

        # 记录工作流日志
        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=file_id,
            operation="split_document",
            status="completed",
            message=f"文档切割成功，生成 {len(chunks)} 个段落",
            knowledge_base_id=doc["knowledge_base_id"],
            processing_time=processing_time
        )

        chunks_count = len(process_result["chunks"])
        # 计算平均chunk大小
        total_size = sum(len(chunk) for chunk in process_result["chunks"])
        avg_chunk_size = total_size / chunks_count if chunks_count > 0 else 0
        # 计算处理时间（毫秒）
        processing_time_ms = (time.time() - start_time) * 1000
        logger.info(f"文档切割成功，文件ID: {file_id}, 段落数: {chunks_count}")
        return {
            "file_id": file_id,
            "status": "success",
            "chunks": process_result["chunks"],
            "chunks_count": chunks_count,
            "avg_chunk_size": avg_chunk_size,
            "processing_time_ms": processing_time_ms,
            "message": "文档切割成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        doc = db.get_document(file_id)
        if doc:
            db.add_workflow_log(
                document_id=file_id,
                operation="split_document",
                status="failed",
                message=str(e),
                knowledge_base_id=doc["knowledge_base_id"]
            )
        logger.error(f"文档切割失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"文档切割失败: {str(e)}")


@router.post("/generate/{file_id}")
async def generate_sub_questions_and_summary(file_id: str, current_user=Depends(get_current_user)):
    """生成子问题和摘要接口（支持增量模式，断点续跑）"""
    logger.info(f"开始生成子问题和摘要，文件ID: {file_id}")
    start_time = time.time()
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 只要文件不是处理失败状态，就可以生成增强内容
        if doc["status"] == "failed":
            logger.warning(f"文件处理失败，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件处理失败")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        # 从数据库中获取文档块
        chunks = db.get_document_chunks(file_id)

        # ==============================================================
        # 增量缓存检查：只有 ALL chunks 都有 sub_questions + summary
        # 才算缓存命中，避免部分生成时返回不完整数据
        # ==============================================================
        all_complete = True
        results = {}
        for chunk in chunks:
            sub_questions = db.get_sub_questions_by_chunk(chunk["id"])
            summary = db.get_chunk_summary(chunk["id"])
            chunk_index = chunk["chunk_index"]
            results[chunk_index] = {
                "sub_questions": [sq["content"] for sq in sub_questions],
                "summary": summary["content"] if summary else "",
            }
            if not sub_questions or not summary:
                all_complete = False

        if all_complete and chunks:
            # 缓存命中：已全部生成，直接返回
            if doc["status"] not in ["generated", "completed"]:
                db.update_document(file_id, status="generated")

            sub_questions_count = sum(len(r["sub_questions"]) for r in results.values())
            summaries_count = sum(1 for r in results.values() if r["summary"])
            processing_time_ms = doc.get("generate_time") or (time.time() - start_time) * 1000
            logger.info(f"文档已生成增强内容（全部完成），直接返回，文件ID: {file_id}")
            return {
                "file_id": file_id,
                "status": "success",
                "results": results,
                "sub_questions_count": sub_questions_count,
                "summaries_count": summaries_count,
                "processing_time_ms": processing_time_ms,
                "message": "文档已生成增强内容（全部完成），直接返回数据库中的结果",
            }

        # ==============================================================
        # 需要增量生成
        # ==============================================================
        processor = DocumentProcessor()

        # 构建数据对象（带 chunk_id，方便 processor 增量检查和写 DB）
        datas = []
        for i, chunk in enumerate(chunks):
            data = StoredData(
                id=f"doc_{chunk['id']}",
                chunk=chunk["content"],
                sub_questions=[],
                subq_embeddings=[],
                summary="",
                summary_embedding=[],
                metadata={
                    "source": doc["filename"],
                    "document_id": file_id,
                    "chunk_id": chunk["id"],      # 传给 processor 用于 DB 操作
                    "chunk_index": chunk["chunk_index"],
                },
            )
            datas.append(data)

        # 增量调用：processor 内部自动跳过已有块，每批次完成后立即写 DB
        await processor.generate_batches_async_concurrent(
            datas,
            batch_size=16,
            max_concurrency=8,
            document_id=file_id,
            knowledge_base_id=doc["knowledge_base_id"],
        )

        # 重新从 DB 读取结果（processor 已写入）
        results = {}
        for chunk in chunks:
            sub_questions = db.get_sub_questions_by_chunk(chunk["id"])
            summary = db.get_chunk_summary(chunk["id"])
            chunk_index = chunk["chunk_index"]
            results[chunk_index] = {
                "sub_questions": [sq["content"] for sq in sub_questions],
                "summary": summary["content"] if summary else "",
            }

        sub_questions_count = sum(len(r["sub_questions"]) for r in results.values())
        summaries_count = sum(1 for r in results.values() if r["summary"])

        # 计算处理时间（毫秒）
        processing_time_ms = (time.time() - start_time) * 1000
        generate_time = processing_time_ms if processing_time_ms > 0.1 else None

        db.update_document(file_id, status="generated", generate_time=generate_time)

        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=file_id,
            operation="generate_sub_questions_and_summary",
            status="completed",
            message=f"生成子问题和摘要成功（增量模式），生成 {sub_questions_count} 个子问题",
            knowledge_base_id=doc["knowledge_base_id"],
            processing_time=processing_time,
        )

        logger.info(f"生成子问题和摘要成功（增量），文件ID: {file_id}, 子问题数: {sub_questions_count}")
        return {
            "file_id": file_id,
            "status": "success",
            "results": results,
            "sub_questions_count": sub_questions_count,
            "summaries_count": summaries_count,
            "processing_time_ms": processing_time_ms,
            "message": "生成子问题和摘要成功（增量模式）",
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        doc = db.get_document(file_id)
        if doc:
            db.add_workflow_log(
                document_id=file_id,
                operation="generate_sub_questions_and_summary",
                status="failed",
                message=str(e),
                knowledge_base_id=doc["knowledge_base_id"]
            )
        logger.error(f"生成子问题和摘要失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成子问题和摘要失败: {str(e)}")


@router.post("/import/{file_id}")
async def import_to_milvus(file_id: str, request: Request, current_user=Depends(get_current_user)):
    """导入到Milvus"""
    logger.info(f"开始导入到Milvus，文件ID: {file_id}")
    start_time = time.time()
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 【硬保险】已完成的文档直接返回已有数据，绝不重复导入
        # 即使前端因状态不同步而误发请求，后端也能正确幂等处理
        if doc["status"] == "completed":
            logger.info(f"文档已完成入库，跳过重复嵌入和导入（服务端幂等命中），文件ID: {file_id}")
            
            # 获取统计数据用于返回
            chunks = db.get_document_chunks(file_id)
            chunk_count = len(chunks)
            sub_question_count = 0
            for chunk in chunks:
                sub_questions = db.get_sub_questions_by_chunk(chunk["id"])
                sub_question_count += len(sub_questions)
            
            vector_count = chunk_count + sub_question_count
            processing_time_ms = doc.get("import_time") or (time.time() - start_time) * 1000
            
            logger.info(f"导入到Milvus成功（缓存），文件ID: {file_id}")
            return {
                "file_id": file_id,
                "status": "success",
                "chunk_count": chunk_count,
                "vector_count": vector_count,
                "sub_question_count": sub_question_count,
                "vector_dim": 1024,
                "processing_time_ms": processing_time_ms,
                "message": "文档已完成入库，直接返回结果"
            }

        if doc["status"] not in ["generated", "importing"]:
            logger.warning(f"文件状态错误，文件ID: {file_id}, 当前状态: {doc['status']}")
            raise HTTPException(status_code=400, detail="文件尚未生成子问题和摘要")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        # 初始化文档处理器和Milvus客户端
        processor = DocumentProcessor()
        # 从请求对象中获取应用实例，再获取app_state
        app_state = request.app.state
        milvus_client = app_state['milvus_client']

        # 从数据库中获取文档块、子问题和摘要
        chunks = db.get_document_chunks(file_id)
        
        # 构建数据对象
        datas = []
        for i, chunk in enumerate(chunks):
            # 获取子问题
            sub_questions = db.get_sub_questions_by_chunk(chunk["id"])
            sub_questions_list = [sq["content"] for sq in sub_questions]
            
            # 获取摘要
            summary = db.get_chunk_summary(chunk["id"])
            summary_text = summary["content"] if summary else ""
            
            # 创建数据对象
            data = StoredData(
                id=f"doc_{chunk['id']}",
                chunk=chunk["content"],
                sub_questions=sub_questions_list,
                subq_embeddings=[],
                summary=summary_text,
                summary_embedding=[],
                metadata={"source": doc["filename"], "document_id": file_id}
            )
            datas.append(data)
        
        # 幂等保护：只有当文档状态不是 completed 时才执行嵌入和导入
        if doc["status"] != "completed":
            try:
                # 设置处理中状态（防并发：标记为 importing）
                db.update_document(file_id, status="importing")
                logger.info(f"文档状态已设为 importing（防并发），文件ID: {file_id}")
                
                # 生成嵌入向量
                await processor.generate_and_fill_embeddings(datas)
                
                # 批量导入到Milvus
                import_result = milvus_client.import_data(
                    datas,
                    user_id=current_user["id"],
                    knowledge_base_id=doc["knowledge_base_id"]
                )

                # 计算处理时间（毫秒）
                processing_time_ms = (time.time() - start_time) * 1000
                # 确保时间不为0，否则存储为NULL
                import_time = processing_time_ms if processing_time_ms > 0.1 else None
                
                # 更新数据库中的文档状态和处理时间
                db.update_document(
                    file_id,
                    status="completed",
                    import_time=import_time
                )
            except Exception as inner_err:
                # 导入失败时回滚状态到 generated，允许重试
                logger.error(f"嵌入导入失败，回滚文档状态: {str(inner_err)}")
                try:
                    db.update_document(file_id, status="generated")
                except Exception as rollback_err:
                    logger.error(f"回滚文档状态失败: {str(rollback_err)}")
                raise inner_err  # 继续向上抛出，由外层 catch 处理
        else:
            logger.info(f"文档已完成，跳过嵌入生成和导入（幂等命中），文件ID: {file_id}")
            # 使用数据库中已有的import_time，而不是重新计算
            processing_time_ms = doc.get("import_time") or (time.time() - start_time) * 1000

        # 计算统计数据
        chunk_count = len(chunks)
        sub_question_count = 0
        vector_count = 0
        vector_dim = 0
        
        # 计算子问题数量和向量数量
        for i, chunk in enumerate(chunks):
            data = datas[i]
            sub_question_count += len(data.sub_questions)
            # 每个chunk有一个向量
            vector_count += 1
            # 每个子问题有一个向量
            vector_count += len(data.sub_questions)
            # 获取向量维度（假设所有向量维度相同）
            if data.summary_embedding:
                vector_dim = len(data.summary_embedding)
            elif data.subq_embeddings and len(data.subq_embeddings) > 0:
                vector_dim = len(data.subq_embeddings[0])

        # 记录工作流日志
        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=file_id,
            operation="import_to_milvus",
            status="completed",
            message="导入到Milvus成功",
            knowledge_base_id=doc["knowledge_base_id"],
            processing_time=processing_time
        )

        logger.info(f"导入到Milvus成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "status": "success",
            "chunk_count": chunk_count,
            "vector_count": vector_count,
            "sub_question_count": sub_question_count,
            "vector_dim": vector_dim,
            "processing_time_ms": processing_time_ms,
            "message": "导入到Milvus成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        doc = db.get_document(file_id)
        if doc:
            db.add_workflow_log(
                document_id=file_id,
                operation="import_to_milvus",
                status="failed",
                message=str(e),
                knowledge_base_id=doc["knowledge_base_id"]
            )
        logger.error(f"导入到Milvus失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导入到Milvus失败: {str(e)}")


@router.post("/full/{file_id}")
async def full_process(file_id: str, current_user=Depends(get_current_user)):
    """一键式完整处理接口"""
    logger.info(f"开始一键式完整处理，文件ID: {file_id}")
    start_time = time.time()
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        # 步骤1: 切割文档（如果尚未切割）
        if doc["status"] == "uploaded":
            logger.info(f"开始切割文档，文件ID: {file_id}")
            # 调用切割接口
            split_response = await split_document(file_id, current_user)
            doc = db.get_document(file_id)  # 重新获取文档信息

        # 步骤2: 生成子问题和摘要（如果尚未生成）
        generate_results = {}
        if doc["status"] == "chunk_done":
            logger.info(f"开始生成子问题和摘要，文件ID: {file_id}")
            # 调用生成接口
            generate_response = await generate_sub_questions_and_summary(file_id, current_user)
            generate_results = generate_response.get("results", {})
            doc = db.get_document(file_id)  # 重新获取文档信息

        # 步骤3: 导入到Milvus（如果尚未导入）
        if doc["status"] == "generated":
            logger.info(f"开始导入到Milvus，文件ID: {file_id}")
            # 调用导入接口
            import_response = await import_to_milvus(file_id, current_user)
            doc = db.get_document(file_id)  # 重新获取文档信息

        # 记录工作流日志
        processing_time = time.time() - start_time
        db.add_workflow_log(
            document_id=file_id,
            operation="full_process",
            status="completed",
            message="一键式完整处理成功",
            knowledge_base_id=doc["knowledge_base_id"],
            processing_time=processing_time
        )

        logger.info(f"一键式完整处理成功，文件ID: {file_id}")
        # todo：一键处理也可展示所有中间结果呢
        return {
            "file_id": file_id,
            "status": "success",
            "message": "一键式完整处理成功",
            "document_status": doc["status"],
            "results": generate_results
        }
    except HTTPException:
        raise
    except Exception as e:
        # 记录失败日志
        doc = db.get_document(file_id)
        if doc:
            db.add_workflow_log(
                document_id=file_id,
                operation="full_process",
                status="failed",
                message=str(e),
                knowledge_base_id=doc["knowledge_base_id"]
            )
        logger.error(f"一键式完整处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"一键式完整处理失败: {str(e)}")


@router.get("/result/{file_id}")
async def get_process_result(file_id: str, current_user=Depends(get_current_user)):
    """获取文档处理结果"""
    logger.info(f"开始获取文档处理结果，文件ID: {file_id}")
    try:
        # 从数据库中获取文档信息
        doc = db.get_document(file_id)
        if not doc:
            logger.warning(f"文件未找到，文件ID: {file_id}")
            raise HTTPException(status_code=404, detail="文件未找到")

        # 验证用户权限
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            logger.warning(
                f"用户无权限访问知识库，用户: {current_user['username']}, 知识库ID: {doc['knowledge_base_id']}")
            raise HTTPException(status_code=403, detail="无权限访问该文档")

        if doc["status"] != "completed":
            logger.warning(f"文件尚未处理完成，文件ID: {file_id}")
            raise HTTPException(status_code=400, detail="文件尚未处理完成")

        # 从数据库中获取文档块、子问题和摘要
        chunks = db.get_document_chunks(file_id)

        # 构建结果
        chunks_list = []
        sub_questions_list = []
        summaries_list = []

        for chunk in chunks:
            chunks_list.append(chunk["content"])

            # 获取子问题
            sub_questions = db.get_sub_questions_by_chunk(chunk["id"])
            sub_questions_list.append([sq["content"] for sq in sub_questions])

            # 获取摘要
            summary = db.get_chunk_summary(chunk["id"])
            summaries_list.append(summary["content"] if summary else "")

        logger.info(f"获取文档处理结果成功，文件ID: {file_id}")
        return {
            "file_id": file_id,
            "chunks": chunks_list,
            "sub_questions": sub_questions_list,
            "summaries": summaries_list,
            "status": doc["status"],  # 返回文档的实际处理状态
            "upload_time": doc.get("upload_time"),
            "split_time": doc.get("split_time"),
            "generate_time": doc.get("generate_time"),
            "import_time": doc.get("import_time")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取处理结果失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取处理结果失败: {str(e)}")
