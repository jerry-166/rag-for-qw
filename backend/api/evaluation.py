"""
评估 API 接口

提供 REST API 触发评估任务、查询结果、管理测试集。

端点：
  POST /api/evaluation/run              - 触发批量评估（异步任务）
  GET  /api/evaluation/status/{task_id} - 查询评估任务状态
  GET  /api/evaluation/reports          - 列出所有历史报告
  GET  /api/evaluation/reports/{name}   - 获取指定报告内容
  POST /api/evaluation/dataset/from-sessions - 从 session 历史生成测试集
  GET  /api/evaluation/dataset/list     - 列出所有测试集
  POST /api/evaluation/fill             - 填充测试集（调用 Agent 填充 answer/contexts）
"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import init_logger
from services.auth import get_current_user

logger = init_logger(__name__)
router = APIRouter(prefix="/evaluation", tags=["evaluation"])

# 内存中的任务状态存储（生产环境可换成 Redis）
_tasks: Dict[str, Dict] = {}


# ─────────────────────────────────────────────────────────────
# 追踪配置
# ─────────────────────────────────────────────────────────────

@router.get("/tracing/info")
async def tracing_info(
    current_user=Depends(get_current_user),
):
    """
    查询当前追踪后端配置

    返回追踪后端类型、状态、连接信息等。
    用于前端展示追踪状态或调试。
    """
    from evaluation.tracing import get_tracer_info
    return get_tracer_info()


@router.post("/tracing/switch")
async def switch_tracing_backend(
    backend: str,
    current_user=Depends(get_current_user),
):
    """
    运行时切换追踪后端（需要重新 setup）

    ⚠️ 此操作会重新初始化追踪后端，正在进行的 trace 可能丢失。
    建议在低峰期操作。

    Args:
        backend: "phoenix" | "langfuse" | "none"
    """
    valid_backends = {"phoenix", "langfuse", "none"}
    if backend not in valid_backends:
        raise HTTPException(
            status_code=400,
            detail=f"无效的后端: {backend}，可选值: {list(valid_backends)}"
        )

    from evaluation.tracing import setup_tracing, get_tracer_info
    result = setup_tracing(backend=backend)

    return {
        "status": "success",
        "previous_backend": get_tracer_info().get("backend"),
        "current_info": get_tracer_info(),
        "setup_result": result,
    }


# ─────────────────────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────────────────────

class EvaluationRunRequest(BaseModel):
    """触发评估任务的请求"""
    dataset_name: str = Field(default="default", description="测试集名称（位于 evaluation/testsets/）")
    metrics: Optional[List[str]] = Field(
        default=None,
        description="指定指标，为空则自动选择。可选: faithfulness, answer_relevancy, context_precision, context_recall"
    )
    knowledge_base_id: Optional[int] = Field(default=None, description="指定知识库（填充 answer 时使用）")
    auto_fill: bool = Field(default=True, description="是否自动填充缺少 answer/contexts 的样本")
    agent_type: str = Field(default="claw", description="填充用的 Agent 类型")
    trace_fill: bool = Field(
        default=False,
        description="是否对 fill 阶段的 Agent 调用启用追踪。开启后可在 Langfuse/Phoenix 查看每条样本的检索过程，适合调试用。批量评估建议保持 False。"
    )


class DatasetFromSessionsRequest(BaseModel):
    """从 session 生成测试集的请求"""
    session_id: Optional[str] = Field(default=None, description="指定 session_id，为空则从所有 session 提取")
    dataset_name: Optional[str] = Field(default=None, description="新测试集名称")
    min_sources_count: int = Field(default=1, description="最少检索文档数（过滤质量差的对话）")
    max_samples: int = Field(default=100, description="最多提取样本数")
    save: bool = Field(default=True, description="是否自动保存到文件")


# ─────────────────────────────────────────────────────────────
# 后台任务
# ─────────────────────────────────────────────────────────────

async def _run_evaluation_task(
    task_id: str,
    dataset_name: str,
    metrics: Optional[List[str]],
    knowledge_base_id: Optional[int],
    auto_fill: bool,
    agent_type: str,
    trace_fill: bool = False,
):
    """后台评估任务"""
    _tasks[task_id]["status"] = "running"
    _tasks[task_id]["started_at"] = datetime.now().isoformat()

    try:
        from evaluation.dataset import EvaluationDataset, TESTSET_DIR
        from evaluation.evaluator import RagasEvaluator

        # 加载测试集
        dataset_path = str(TESTSET_DIR / f"{dataset_name}.json")
        if not os.path.exists(dataset_path):
            raise FileNotFoundError(f"测试集不存在: {dataset_name}.json")

        dataset = EvaluationDataset.load(dataset_path)
        _tasks[task_id]["total_samples"] = len(dataset)

        # 自动填充
        if auto_fill:
            _tasks[task_id]["status"] = "filling"
            evaluator = RagasEvaluator()
            dataset = await evaluator.fill_dataset(
                dataset,
                knowledge_base_id=knowledge_base_id,
                agent_type=agent_type,
                trace_fill=trace_fill,
            )
            # 填充后保存
            dataset.save()

        # 执行评估
        _tasks[task_id]["status"] = "evaluating"
        evaluator = RagasEvaluator()
        report = await evaluator.evaluate(dataset, metrics=metrics)

        # 保存报告
        report_path = report.save()

        _tasks[task_id].update({
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
            "report_path": report_path,
            "scores": report.scores,
            "total_samples": report.total_samples,
            "skipped_samples": report.skipped_samples,
            "metrics_used": report.metrics_used,
            "summary": report.summary(),
        })

        logger.info(f"[Evaluation API] 任务 {task_id} 完成: {report.scores}")

    except Exception as e:
        logger.error(f"[Evaluation API] 任务 {task_id} 失败: {e}")
        _tasks[task_id].update({
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now().isoformat(),
        })


# ─────────────────────────────────────────────────────────────
# API 端点
# ─────────────────────────────────────────────────────────────

@router.post("/run")
async def run_evaluation(
    request: EvaluationRunRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    """
    触发批量评估任务（异步）

    返回 task_id，通过 GET /status/{task_id} 查询进度。
    """
    task_id = f"eval_{uuid.uuid4().hex[:8]}"
    _tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "dataset_name": request.dataset_name,
        "created_at": datetime.now().isoformat(),
    }

    background_tasks.add_task(
        _run_evaluation_task,
        task_id=task_id,
        dataset_name=request.dataset_name,
        metrics=request.metrics,
        knowledge_base_id=request.knowledge_base_id,
        auto_fill=request.auto_fill,
        agent_type=request.agent_type,
        trace_fill=request.trace_fill,
    )

    logger.info(f"[Evaluation API] 评估任务已提交: {task_id}, 数据集: {request.dataset_name}")

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": f"评估任务已提交，通过 GET /api/evaluation/status/{task_id} 查询进度",
    }


@router.get("/status/{task_id}")
async def get_task_status(
    task_id: str,
    current_user=Depends(get_current_user),
):
    """查询评估任务状态"""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    return _tasks[task_id]


@router.get("/tasks")
async def list_tasks(
    current_user=Depends(get_current_user),
):
    """列出所有评估任务"""
    return {
        "tasks": list(_tasks.values()),
        "total": len(_tasks),
    }


@router.get("/reports")
async def list_reports(
    current_user=Depends(get_current_user),
):
    """列出所有历史评估报告"""
    from evaluation.dataset import REPORT_DIR

    reports = []
    if REPORT_DIR.exists():
        for f in sorted(REPORT_DIR.glob("eval_*.json"), reverse=True):
            try:
                with open(f, encoding="utf-8") as fp:
                    data = json.load(fp)
                reports.append({
                    "filename": f.name,
                    "dataset_name": data.get("dataset_name"),
                    "evaluated_at": data.get("evaluated_at"),
                    "scores": data.get("scores", {}),
                    "total_samples": data.get("total_samples", 0),
                    "metrics_used": data.get("metrics_used", []),
                })
            except Exception:
                pass

    return {"reports": reports, "total": len(reports)}


@router.get("/reports/{filename}")
async def get_report(
    filename: str,
    current_user=Depends(get_current_user),
):
    """获取指定报告的完整内容"""
    from evaluation.dataset import REPORT_DIR

    filepath = REPORT_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"报告不存在: {filename}")

    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


@router.get("/dataset/list")
async def list_datasets(
    current_user=Depends(get_current_user),
):
    """列出所有可用的测试集"""
    from evaluation.dataset import TESTSET_DIR

    datasets = []
    if TESTSET_DIR.exists():
        for f in sorted(TESTSET_DIR.glob("*.json")):
            try:
                with open(f, encoding="utf-8") as fp:
                    data = json.load(fp)
                datasets.append({
                    "name": data.get("name", f.stem),
                    "filename": f.name,
                    "count": data.get("count", 0),
                    "updated_at": data.get("updated_at"),
                })
            except Exception:
                pass

    return {"datasets": datasets, "total": len(datasets)}


@router.post("/dataset/from-sessions")
async def create_dataset_from_sessions(
    request: DatasetFromSessionsRequest,
    current_user=Depends(get_current_user),
):
    """从 session 历史中自动提取测试集"""
    try:
        from evaluation.dataset import EvaluationDataset

        if request.session_id:
            dataset = EvaluationDataset.from_session_history(
                session_id=request.session_id,
                name=request.dataset_name,
                min_sources_count=request.min_sources_count,
                max_samples=request.max_samples,
            )
        else:
            dataset = EvaluationDataset.from_all_sessions(
                name=request.dataset_name,
                min_sources_count=request.min_sources_count,
                max_samples=request.max_samples,
            )

        result = {
            "status": "success",
            "dataset_name": dataset.name,
            "stats": dataset.stats(),
            "message": f"成功提取 {len(dataset)} 条样本",
        }

        if request.save and len(dataset) > 0:
            path = dataset.save()
            result["saved_to"] = path

        return result

    except Exception as e:
        logger.error(f"[Evaluation API] 生成测试集失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成测试集失败: {str(e)}")


@router.post("/fill/{dataset_name}")
async def fill_dataset(
    dataset_name: str,
    knowledge_base_id: Optional[int] = Query(default=None),
    agent_type: str = Query(default="claw"),
    trace_fill: Optional[bool] = Query(default=False),
    current_user=Depends(get_current_user),
):
    """
    填充测试集中缺少 answer/contexts 的样本（同步执行，小数据集用）

    大数据集建议通过 /run 接口异步执行（设置 auto_fill=true）。

    Args:
        trace_fill: 是否对 fill 阶段启用追踪（默认 False，调试时可开启）
    """
    try:
        from evaluation.dataset import EvaluationDataset, TESTSET_DIR
        from evaluation.evaluator import RagasEvaluator

        dataset_path = str(TESTSET_DIR / f"{dataset_name}.json")
        dataset = EvaluationDataset.load(dataset_path)

        before_stats = dataset.stats()
        evaluator = RagasEvaluator()
        dataset = await evaluator.fill_dataset(
            dataset,
            knowledge_base_id=knowledge_base_id,
            agent_type=agent_type,
            trace_fill=trace_fill,
        )
        after_stats = dataset.stats()

        dataset.save()

        return {
            "status": "success",
            "dataset_name": dataset_name,
            "before": before_stats,
            "after": after_stats,
            "filled": after_stats["complete"] - before_stats["complete"],
        }

    except Exception as e:
        logger.error(f"[Evaluation API] 填充测试集失败: {e}")
        raise HTTPException(status_code=500, detail=f"填充失败: {str(e)}")
