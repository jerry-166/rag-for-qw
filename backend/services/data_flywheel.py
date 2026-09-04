"""
数据飞轮自动调度器（Step 2）— APScheduler 周期触发完整闭环

每日 02:00 跑：
  ① from_all_sessions() 增量提取昨天 session → 新测试集 flywheel_YYYYMMDD
  ② 给每条调 generate_ground_truth() 生成 GT 草稿
  ③ LLM 自评 GT 质量，>=0.8 自动 approve；<0.8 标 pending
  ④ 对 approved 样本调 RagasEvaluator.evaluate() 跑 RAGAS
  ⑤ 报告写 reports/eval_flywheel_YYYYMMDD_HHMMSS.json，附 low_score_samples + suggested_actions

环境开关（.env）：
  FLYWHEEL_ENABLED=true|false  (默认 false，需显式开启)
  FLYWHEEL_HOUR=2              (每日几点跑，默认 2 = 凌晨 2 点)
  FLYWHEEL_MAX_SAMPLES=100     (单次提取上限，默认 100)
  FLYWHEEL_GT_THRESHOLD=0.8   (GT 自评 approve 阈值，默认 0.8)

手动触发（测试用）：
  curl -X POST http://localhost:8003/api/evaluation/flywheel/trigger
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings, init_logger, get_runtime
from evaluation.dataset import EvaluationDataset
from evaluation.evaluator import RagasEvaluator, EvaluationReport
from evaluation.gt_generator import generate_ground_truth
from services.audit import audit

logger = init_logger("data_flywheel")

# ── 模块级调度器实例（app lifespan 持有）──
_scheduler: Optional[AsyncIOScheduler] = None


def _get_flywheel_config() -> dict:
    """从 runtime config 读飞轮参数（支持 .env + 运行时覆盖）"""
    return {
        "enabled": str(get_runtime("FLYWHEEL_ENABLED", "false")).lower() in ("1", "true", "yes"),
        "hour": int(get_runtime("FLYWHEEL_HOUR", "2")),
        "max_samples": int(get_runtime("FLYWHEEL_MAX_SAMPLES", "100")),
        "gt_threshold": float(get_runtime("FLYWHEEL_GT_THRESHOLD", "0.8")),
    }


# ── LLM 自评 GT 质量（与 step1 脚本一致）──

async def _llm_score_gt(question: str, gt: str, contexts: list) -> float:
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
        )
        context_text = "\n\n---\n\n".join(c[:500] for c in contexts[:3])
        prompt = (
            "你是一个评分员。给下面的「标准参考答案」打 0 到 1 分。\n"
            "评分维度：\n1. 覆盖问题核心（0-0.5）\n2. 是否仅基于上下文不编造（0-0.5）n\n"
            f"## 问题\n{question}\n\n"
            f"## 上下文（节选）\n{context_text}\n\n"
            f"## 候选参考答案\n{gt}\n\n"
            "只输出一个浮点数（0 到 1），不要任何解释。"
        )
        resp = await client.chat.completions.create(
            model=settings.DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0, max_tokens=20,
        )
        text = resp.choices[0].message.content.strip()
        import re
        m = re.search(r"([01](?:\.\d+)?|0?\.\d+)", text)
        return float(m.group(1)) if m else 0.5
    except Exception as e:
        logger.warning(f"GT 自评失败，保守返回 0.5: {e}")
        return 0.5


# ── 单次飞轮周期 ──

async def run_flywheel_cycle(triggered_by: str = "scheduler") -> dict:
    """
    跑一次完整飞轮周期。可被调度器或手动 trigger 调用。

    Returns: 摘要 dict（供 REST 接口返回）
    """
    cfg = _get_flywheel_config()
    started_at = datetime.now()
    summary = {
        "triggered_by": triggered_by,
        "started_at": started_at.isoformat(),
        "config": cfg,
        "stages": {},
    }
    logger.info(f"[Flywheel] 周期开始 triggered_by={triggered_by}")

    # ① 增量提取
    try:
        today_tag = started_at.strftime("%Y%m%d")
        dataset_name = f"flywheel_{today_tag}"
        dataset = EvaluationDataset.from_all_sessions(
            name=dataset_name, min_sources_count=1, max_samples=cfg["max_samples"])
        dataset.save()
        summary["stages"]["extract"] = {
            "status": "ok", "dataset_name": dataset_name,
            "count": len(dataset),
        }
        logger.info(f"[Flywheel] ① 提取 {len(dataset)} 条 → {dataset_name}")
        if len(dataset) == 0:
            summary["status"] = "skipped_empty"
            summary["completed_at"] = datetime.now().isoformat()
            return summary
    except Exception as e:
        logger.error(f"[Flywheel] ① 提取失败: {e}")
        summary["stages"]["extract"] = {"status": "error", "error": str(e)}
        summary["status"] = "failed"
        return summary

    # ② + ③ 批量生成 GT + 自评 approve
    approved = 0
    for i, sample in enumerate(dataset.samples):
        if not sample.contexts:
            continue
        gt = await asyncio.to_thread(
            generate_ground_truth, sample.question, sample.contexts)
        if not gt:
            sample.status = "pending"
            continue
        sample.ground_truth = gt
        score = await _llm_score_gt(sample.question, gt, sample.contexts)
        if score >= cfg["gt_threshold"]:
            sample.status = "approved"
            approved += 1
        else:
            sample.status = "pending"
    dataset.save()
    summary["stages"]["generate_gt"] = {
        "status": "ok", "approved": approved,
        "pending": len(dataset) - approved, "threshold": cfg["gt_threshold"],
    }
    logger.info(f"[Flywheel] ②/③ GT 生成 + 自评 approve={approved}/{len(dataset)}")

    # ④ 评估（仅 approved+GT 完整的样本）
    evaluable = [s for s in dataset.samples if s.is_evaluable()]
    summary["stages"]["evaluate"] = {"evaluable": len(evaluable)}
    if not evaluable:
        summary["stages"]["evaluate"]["status"] = "skipped_no_evaluable"
        summary["status"] = "skipped_no_evaluable"
        summary["completed_at"] = datetime.now().isoformat()
        return summary

    evaluator = RagasEvaluator()
    report = await evaluator.evaluate(dataset)
    report_path = report.save()
    summary["stages"]["evaluate"].update({
        "status": "ok", "report_path": report_path,
        "scores": report.scores,
        "total_samples": report.total_samples,
    })
    logger.info(f"[Flywheel] ④ 评估完成 scores={report.scores}")

    # ⑤ 策略反馈建议（Step 3 — 写入报告）
    suggestions = _build_suggested_actions(report)
    summary["stages"]["suggestions"] = {
        "count": len(suggestions),
        "items": suggestions,
    }

    # 审计落库（可追溯飞轮每次运行）
    try:
        audit.log("flywheel.cycle", user_id=None, resource_type="evaluation",
                  resource_id=None, kb_id=None,
                  detail={
                      "triggered_by": triggered_by,
                      "dataset_name": dataset_name,
                      "extracted": len(dataset),
                      "approved": approved,
                      "scores": report.scores,
                      "suggestions": len(suggestions),
                  })
    except Exception as e:
        logger.warning(f"[Flywheel] 审计落库失败（不致命）: {e}")

    summary["status"] = "completed"
    summary["completed_at"] = datetime.now().isoformat()
    logger.info(f"[Flywheel] 周期完成 status=completed")
    return summary


# ── Step 3：策略反馈建议（复用 EvaluationReport.build_suggested_actions）──

def _build_suggested_actions(report: EvaluationReport) -> list:
    """
    委托给 EvaluationReport.build_suggested_actions()，避免重复实现。
    详见 evaluator.py 中 LOW_SCORE_THRESHOLDS 与归类优先级。
    """
    return report.build_suggested_actions()


# ── 调度器生命周期 ──

def start_scheduler() -> AsyncIOScheduler:
    """启动 APScheduler，挂载飞轮 cron job。app lifespan 启动时调一次。"""
    global _scheduler
    if _scheduler is not None:
        logger.warning("[Flywheel] 调度器已存在，跳过重复启动")
        return _scheduler

    cfg = _get_flywheel_config()
    if not cfg["enabled"]:
        logger.info(f"[Flywheel] FLYWHEEL_ENABLED=false，调度器不启动（手动 trigger 仍可用）")
        return None

    sched = AsyncIOScheduler()
    # 每日 cfg['hour'] 点跑飞轮周期
    sched.add_job(
        run_flywheel_cycle,
        CronTrigger(hour=cfg["hour"], minute=0),
        id="flywheel_daily",
        kwargs={"triggered_by": "scheduler"},
        replace_existing=True,
    )
    sched.start()
    _scheduler = sched
    logger.info(f"[Flywheel] 调度器已启动，每日 {cfg['hour']:02d}:00 跑飞轮周期")
    return sched


async def stop_scheduler():
    """优雅停机。app lifespan 关闭时调。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[Flywheel] 调度器已关闭")


def get_scheduler_info() -> dict:
    """REST /api/evaluation/flywheel/info 用"""
    if _scheduler is None:
        return {"running": False, "jobs": []}
    return {
        "running": _scheduler.running,
        "jobs": [
            {"id": j.id, "next_run_time": str(j.next_run_time) if j.next_run_time else None}
            for j in _scheduler.get_jobs()
        ],
    }
