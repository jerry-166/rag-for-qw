from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Optional
import time

from config import init_logger, settings, get_runtime
from services.audit import audit
from services.database import db
from services.auth import get_current_user
# 01-B：document_processor 顶层拉起 sentence_transformers（~15s import），改为请求期延迟导入
from services.milvus_client import MilvusClient
from services.storage import get_storage
from services.chunking import resolve_strategy_name
from services.enhancers import resolve_enabled_enhancers, VALID_ENHANCERS

logger = init_logger(__name__)
router = APIRouter()


def _get_processor():
    """01-B：延迟导入 DocumentProcessor / StoredData（避免顶层拉起 sentence_transformers）。"""
    from services.document_processor import DocumentProcessor, StoredData
    return DocumentProcessor, StoredData


_STAGE_BY_STATUS = {
    # Stage 5：document.status -> 流水线阶段（与前端 pipeline 四步对齐）
    "uploaded": "awaiting_split",        # 已上传，待切割
    "chunk_done": "generating",          # 已切块，generate 可在跑（状态不区分进行中，见 stage_in_progress）
    "generated": "awaiting_import",      # 增强完成，待导入
    "importing": "importing",            # 导入进行中
    "completed": "done",                 # 全部完成
    "failed": "failed",                  # 失败
}


@router.get("/progress/{file_id}")
async def get_process_progress(file_id: str, req: Request, current_user=Depends(get_current_user)):
    """轻量处理进度轮询接口（文档 05 问题 5/9 后端侧，Stage 5）。

    纯 PG 查询（document + 聚合 + 最近 workflow_log），无 LLM/embedding 开销。
    generate/import 阶段状态机只写终态，进行中的判断依据：
    - chunk_done 且缺口为 0 → generate 实际已完成（等 import）
    - importing 阶段无法给 chunk 级进度，is_running 由状态决定
    """
    doc = db.get_document(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文件未找到")
    if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
        raise HTTPException(status_code=403, detail="无权限访问该知识库")

    status = doc["status"]
    stage = _STAGE_BY_STATUS.get(status, status)

    # 阶段内进度：generate 阶段用增强聚合（按启用集口径）；split/import 无中间粒度
    agg = db.get_document_enhancement_progress(file_id)
    total = agg["total_chunks"]
    enabled = resolve_enabled_enhancers(doc["knowledge_base_id"])
    need_subq = "sub_question" in enabled
    need_summary = "summary" in enabled
    if status == "chunk_done":
        # 需求 chunk 数：启用了对应增强器的 chunk 才计入
        required = total if (need_subq or need_summary) else 0
        done = 0
        if need_subq and need_summary:
            done = min(agg["chunks_with_subq"], agg["chunks_with_summary"])
        elif need_subq:
            done = agg["chunks_with_subq"]
        elif need_summary:
            done = agg["chunks_with_summary"]
        else:
            required, done = 0, 0
    else:
        required = done = total
    stage_progress = {
        "done": done,
        "total": required,
    }

    # 最近一条 workflow 日志（失败信息来源）
    logs = db.get_document_workflow_logs(file_id)
    last_log = logs[0] if logs else None
    last_error = None
    if status == "failed" or (last_log and last_log.get("status") == "failed"):
        for lg in logs:
            if lg.get("status") == "failed":
                last_error = {"operation": lg.get("operation"), "message": lg.get("message"),
                              "at": lg.get("created_at")}
                break

    audit.log_from_request(req, "process.progress_check", user_id=current_user["id"],
              resource_type="document", resource_id=file_id, kb_id=doc["knowledge_base_id"],
              detail={"status": status, "stage": stage, "done": done, "total": required})

    return {
        "file_id": file_id,
        "document_status": status,
        "stage": stage,
        "is_running": status in ("chunk_done", "importing"),
        "stage_progress": stage_progress,
        "total_chunks": total,
        "timing_ms": {
            "split_time": doc.get("split_time"),
            "generate_time": doc.get("generate_time"),
            "import_time": doc.get("import_time"),
        },
        "updated_at": doc.get("updated_at"),
        "last_error": last_error,
    }


@router.post("/split/{file_id}")
async def split_document(file_id: str, req: Request, current_user=Depends(get_current_user),
                         strategy: Optional[str] = None):
    """MD切割接口（文档 02：策略三级解析 请求参数 > 知识库配置 > 全局配置）"""
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
        DocumentProcessor, _StoredData = _get_processor()
        processor = DocumentProcessor()
        storage = get_storage()

        # 读取Markdown内容
        markdown_content = storage.read(doc["enhanced_md_path"])
        if not markdown_content:
            raise HTTPException(status_code=404, detail="Markdown文件未找到")

        # 切割文档（文档 02：三级解析——请求参数 > KB 配置 > 全局配置，默认 auto=历史行为）
        kb = db.get_knowledge_base(doc["knowledge_base_id"]) if doc["knowledge_base_id"] else None
        strategy_name = resolve_strategy_name(
            request_strategy=strategy,
            kb_strategy=kb.get("chunk_strategy") if kb else None,
        )
        process_result = processor.split_document(markdown_content, strategy=strategy_name)
        logger.debug(f"文档切割完成（策略 {process_result.get('strategy')}），生成 {len(process_result['chunks'])} 个段落")
        audit.log_from_request(req, "process.split.done", user_id=current_user["id"],
                  resource_type="document", resource_id=file_id, kb_id=doc["knowledge_base_id"],
                  detail={"strategy": process_result.get("strategy"), "chunks": len(process_result["chunks"])})

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

        # ── 文档 08：split 阶段 chunks 已写 PG + BM25 索引 → bump KB 缓存版本 ──
        from services.cache import bump_kb_cache
        bump_kb_cache(doc["knowledge_base_id"], "split", current_user["id"])

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
async def generate_sub_questions_and_summary(file_id: str, req: Request, current_user=Depends(get_current_user)):
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
        # 增量缓存检查（文档 03：按启用集判断）——只有 ALL chunks
        # 都已生成「启用集中」的字段才算缓存命中
        # ==============================================================
        enabled = resolve_enabled_enhancers(doc["knowledge_base_id"])
        need_subq = "sub_question" in enabled
        need_summary = "summary" in enabled
        need_entity = "entity" in enabled

        # 全关：跳过 LLM 生成，直接推进状态（纯原文 RAG，import 阶段只处理 chunk 向量）
        if not (need_subq or need_summary or need_entity):
            if doc["status"] not in ["generated", "completed"]:
                db.update_document(file_id, status="generated")
            logger.info(f"增强器已全部关闭，跳过生成并推进状态，文件ID: {file_id}")
            audit.log_from_request(req, "process.generate.api_done", user_id=current_user["id"],
                      resource_type="document", resource_id=file_id, kb_id=doc["knowledge_base_id"],
                      detail={"chunks": len(chunks), "enabled_enhancers": [], "mode": "noop",
                              "processing_time_ms": round((time.time() - start_time) * 1000, 1)})
            return {
                "file_id": file_id,
                "status": "success",
                "results": {},
                "sub_questions_count": 0,
                "summaries_count": 0,
                "processing_time_ms": (time.time() - start_time) * 1000,
                "enabled_enhancers": [],
                "message": "增强器已全部关闭（纯原文 RAG），跳过生成",
            }

        all_complete = True
        results = {}
        need_entity = "entity" in enabled
        entity_covered = set()
        if need_entity:
            import json as _json
            for e in db.get_kb_entities(doc["knowledge_base_id"], limit=5000):
                src = e.get("source_chunk_ids") or []
                if isinstance(src, str):
                    try:
                        src = _json.loads(src)
                    except Exception:
                        src = []
                entity_covered.update(src)
        for chunk in chunks:
            sub_questions = db.get_sub_questions_by_chunk(chunk["id"]) if need_subq else [1]
            summary = db.get_chunk_summary(chunk["id"]) if need_summary else "1"
            chunk_index = chunk["chunk_index"]
            results[chunk_index] = {
                "sub_questions": [sq["content"] for sq in sub_questions] if need_subq else [],
                "summary": summary["content"] if (need_summary and summary) else "",
            }
            if (need_subq and not sub_questions) or (need_summary and not summary) or (
                    need_entity and chunk["id"] not in entity_covered):
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
                "enabled_enhancers": sorted(enabled),
                "message": "文档已生成增强内容（全部完成），直接返回数据库中的结果",
            }

        # ==============================================================
        # 需要增量生成
        # ==============================================================
        DocumentProcessor, StoredData = _get_processor()
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
        # 并发参数热读（文档 04 §3.1）：设置页改 BATCH_SIZE/MAX_CONCURRENCY 无需重启即生效
        await processor.generate_batches_async_concurrent(
            datas,
            batch_size=get_runtime("BATCH_SIZE", settings.BATCH_SIZE),
            max_concurrency=get_runtime("MAX_CONCURRENCY", settings.MAX_CONCURRENCY),
            document_id=file_id,
            knowledge_base_id=doc["knowledge_base_id"],
            enabled=enabled,
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

        audit.log_from_request(req, "process.generate.api_done", user_id=current_user["id"],
                  resource_type="document", resource_id=file_id, kb_id=doc["knowledge_base_id"],
                  detail={"chunks": len(chunks), "sub_questions_count": sub_questions_count,
                          "summaries_count": summaries_count, "enabled_enhancers": sorted(enabled),
                          "processing_time_ms": round((time.time() - start_time) * 1000, 1)})

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


@router.get("/generate/{file_id}/missing")
async def get_missing_enhancements(file_id: str, req: Request, current_user=Depends(get_current_user)):
    """缺口检测接口（文档 03 §3.4 补生成显性化）。

    轻量纯 PG 查询，零 LLM/embedding 调用：
    统计该文档在「当前启用集」下缺失增强内容的 chunk 数量，
    供前端显示黄色提示条 + 显性「补生成」按钮；正常流程不做隐性回补。
    """
    try:
        doc = db.get_document(file_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文件未找到")
        if not db.check_kb_permission(current_user["id"], doc["knowledge_base_id"]):
            raise HTTPException(status_code=403, detail="无权限访问该知识库")

        chunks = db.get_document_chunks(file_id)
        enabled = resolve_enabled_enhancers(doc["knowledge_base_id"])
        need_subq = "sub_question" in enabled
        need_summary = "summary" in enabled
        need_entity = "entity" in enabled

        missing_subq = 0
        missing_summary = 0
        missing_entity = 0
        missing_both = 0
        for chunk in chunks:
            miss_sq = need_subq and not db.get_sub_questions_by_chunk(chunk["id"])
            miss_sm = need_summary and not db.get_chunk_summary(chunk["id"])
            if miss_sq:
                missing_subq += 1
            if miss_sm:
                missing_summary += 1
            if miss_sq or miss_sm:
                missing_both += 1

        # 实体缺口：KB 级实体按 source_chunk_ids 求交（纯 PG，零 LLM/embedding）
        if need_entity:
            import json as _json
            chunk_ids = {c["id"] for c in chunks}
            covered = set()
            for e in db.get_kb_entities(doc["knowledge_base_id"], limit=5000):
                src = e.get("source_chunk_ids") or []
                if isinstance(src, str):
                    try:
                        src = _json.loads(src)
                    except Exception:
                        src = []
                covered |= chunk_ids & set(src)
            missing_entity = len(chunk_ids - covered)
            if missing_entity > 0:
                missing_both = max(missing_both, missing_entity)

        response = {
            "file_id": file_id,
            "enabled_enhancers": sorted(enabled),
            "total_chunks": len(chunks),
            "missing_chunks": missing_both,
            "missing": {"sub_question": missing_subq, "summary": missing_summary,
                        "entity": missing_entity},
            "need_backfill": missing_both > 0,
        }
        audit.log_from_request(req, "process.generate.missing_check", user_id=current_user["id"],
                  resource_type="document", resource_id=file_id, kb_id=doc["knowledge_base_id"],
                  detail={"enabled_enhancers": sorted(enabled), "total_chunks": len(chunks),
                          "missing_chunks": missing_both})
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"缺口检测失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"缺口检测失败: {str(e)}")


async def _sync_entity_vectors(processor, milvus_client, chunks, knowledge_base_id):
    """实体向量同步（文档 06 Phase 2）：

    找出本文档 chunk 关联的实体（PG entity.source_chunk_ids 与本文档 chunk_ids 求交），
    为其 description 生成嵌入并 upsert 到 Milvus entities 集合。
    实体是 KB 级合并的，只处理与本文档相关的，避免全量重算。
    """
    chunk_ids = {c["id"] for c in chunks}
    kb_entities = db.get_kb_entities(knowledge_base_id, limit=2000)
    related = []
    for e in kb_entities:
        src_ids = e.get("source_chunk_ids") or []
        if isinstance(src_ids, str):
            import json as _json
            try:
                src_ids = _json.loads(src_ids)
            except Exception:
                src_ids = []
        if chunk_ids & set(src_ids):
            related.append(e)
    if not related:
        logger.info("本文档无关联实体，跳过实体向量同步")
        return

    texts = [f"{e['name']}：{e.get('description') or ''}" for e in related]
    vectors = await processor.batch_embed_texts(texts)
    synced = 0
    for e, vec in zip(related, vectors):
        if milvus_client.upsert_entity_vector(e["id"], knowledge_base_id,
                                              e["name"], e.get("description"), vec):
            synced += 1
    logger.info(f"实体向量同步完成：{synced}/{len(related)} 个实体")
    audit.log("process.entity_sync", resource_type="knowledge_base",
              resource_id=knowledge_base_id, kb_id=knowledge_base_id,
              detail={"related_entities": len(related), "synced": synced})


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
        DocumentProcessor, StoredData = _get_processor()
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
                metadata={"source": doc["filename"], "document_id": file_id,
                          "chunk_id": chunk["id"], "chunk_index": chunk["chunk_index"]}
            )
            datas.append(data)
        
        # 幂等保护：只有当文档状态不是 completed 时才执行嵌入和导入
        if doc["status"] != "completed":
            try:
                # 设置处理中状态（防并发：标记为 importing）
                db.update_document(file_id, status="importing")
                logger.info(f"文档状态已设为 importing（防并发），文件ID: {file_id}")
                
                # 生成嵌入向量（文档 03：按 KB 启用集只嵌入启用的增强内容）
                enabled = resolve_enabled_enhancers(doc["knowledge_base_id"])
                await processor.generate_and_fill_embeddings(datas, enabled=enabled)

                # 生成 chunk 原文向量（Native检索）
                await processor.generate_chunk_embeddings(datas)

                # 06 Phase 2：实体向量同步到 Milvus（该文档 chunk 关联的实体）
                if "entity" in enabled:
                    try:
                        await _sync_entity_vectors(
                            processor, milvus_client, chunks, doc["knowledge_base_id"])
                    except Exception as ee:
                        logger.warning(f"实体向量同步失败（不阻断导入）: {ee}")
                
                # 批量导入到Milvus（同步方法，用 executor 避免阻塞 asyncio 事件循环）
                import asyncio
                import functools
                loop = asyncio.get_event_loop()
                import_result = await loop.run_in_executor(
                    None,
                    functools.partial(
                        milvus_client.import_data,
                        datas,
                        user_id=current_user["id"],
                        knowledge_base_id=doc["knowledge_base_id"]
                    )
                )

                # logger.info(f"导入到Milvus成功，文件ID: {file_id}")

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
                # ── 文档 08：向量导入完成 → bump KB 缓存版本
                # （上/下两个幂等早退分支内容未变，不 bump）──
                from services.cache import bump_kb_cache
                bump_kb_cache(doc["knowledge_base_id"], "import", current_user["id"])
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
        audit.log_from_request(request, "process.import.done", user_id=current_user["id"],
                  resource_type="document", resource_id=file_id, kb_id=doc["knowledge_base_id"],
                  detail={"chunks": chunk_count, "vectors": vector_count,
                          "sub_questions": sub_question_count, "vector_dim": vector_dim,
                          "processing_time_ms": round(processing_time_ms, 1) if processing_time_ms else None})
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
