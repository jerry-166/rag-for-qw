"""
数据飞轮 Step 1 验证脚本 — 跑通 9 月 20 条 session 样本

流程：
  1. load testsets/all_sessions_20260901.json（20 条，GT 全空，status=approved 是默认值）
  2. 给每条调 generate_ground_truth() 生成 GT 草稿
  3. LLM 自评 GT 质量（0-1 分），>=0.8 自动 approve；<0.8 标 pending
  4. 跑 RagasEvaluator.evaluate()（绕过 30 条门控，验证用）
  5. 对比 4 月 5 条手集基线（faithfulness 0.666 / answer_relevancy 0.428）

用法：
  cd d:/workspace/rag-for-qw/backend
  .venv/Scripts/python.exe ../work/data-flywheel/step1_baseline_run.py

注意：
  - 直接 import backend 模块，绕过 REST API 30 条门控（生产保护不动）
  - 评估 judge LLM 用 litellm 接的 gpt-4o（与被评同模型，self-judge 偏差报告会声明）
  - 9 月这批样本从 session 提取自带 answer+contexts，不需要 fill_dataset
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── 路径修复：让脚本能 import backend 模块 ──
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# 切到 backend 工作目录，让 settings 的相对路径生效
os.chdir(BACKEND_DIR)

from config import settings, init_logger
from evaluation.dataset import EvaluationDataset, TESTSET_DIR, REPORT_DIR
from evaluation.evaluator import RagasEvaluator
from evaluation.gt_generator import generate_ground_truth

logger = init_logger("step1_flywheel")


# ── LLM 自评 GT 质量 ──

async def llm_score_gt(question: str, gt: str, contexts: list) -> float:
    """
    让 LLM 给生成的 GT 打 0-1 分：
    - 是否覆盖问题核心
    - 是否仅基于 contexts 不编造

    返回 [0, 1] 浮点；异常返回 0.5（保守不自动 approve）
    """
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
        )
        context_text = "\n\n---\n\n".join(c[:500] for c in contexts[:3])
        prompt = (
            "你是一个评分员。给下面的「标准参考答案」打 0 到 1 分。\n"
            "评分维度：\n"
            "1. 覆盖问题核心（0-0.5）\n"
            "2. 是否仅基于上下文不编造（0-0.5）\n\n"
            f"## 问题\n{question}\n\n"
            f"## 上下文（节选）\n{context_text}\n\n"
            f"## 候选参考答案\n{gt}\n\n"
            "只输出一个浮点数（0 到 1），不要任何解释。"
        )
        resp = await client.chat.completions.create(
            model=settings.DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=20,
        )
        text = resp.choices[0].message.content.strip()
        # 兜底解析：取第一个浮点数
        import re
        m = re.search(r"([01](?:\.\d+)?|0?\.\d+)", text)
        return float(m.group(1)) if m else 0.5
    except Exception as e:
        logger.warning(f"GT 自评失败，保守返回 0.5: {e}")
        return 0.5


# ── Step 1 主流程 ──

async def run_step1():
    print("=" * 70)
    print("数据飞轮 Step 1 — 跑通 9 月 20 条 session 样本")
    print("=" * 70)

    # ── 1. 加载测试集 ──
    dataset_path = TESTSET_DIR / "all_sessions_20260901.json"
    if not dataset_path.exists():
        print(f"[ERR] 测试集不存在: {dataset_path}")
        return
    dataset = EvaluationDataset.load(str(dataset_path))
    print(f"\n[1/5] 加载测试集: {dataset.name}，共 {len(dataset)} 条样本")
    stats = dataset.stats()
    print(f"     complete={stats['complete']}, with_gt={stats['with_ground_truth']}, evaluable={stats['evaluable']}")

    # ── 2. 批量生成 GT + LLM 自评 ──
    print(f"\n[2/5] 批量生成 GT 草稿（调 generate_ground_truth + LLM 自评）...")
    approved_count = 0
    score_threshold = 0.8  # >=0.8 自动 approve
    for i, sample in enumerate(dataset.samples):
        if not sample.contexts:
            print(f"  [{i+1:2d}/{len(dataset)}] 跳过：无 contexts")
            continue
        # 调 generate_ground_truth（同步函数，套 to_thread）
        gt = await asyncio.to_thread(
            generate_ground_truth, sample.question, sample.contexts)
        if not gt:
            print(f"  [{i+1:2d}/{len(dataset)}] GT 生成失败，保持空")
            sample.status = "pending"
            continue
        sample.ground_truth = gt
        # LLM 自评
        score = await llm_score_gt(sample.question, gt, sample.contexts)
        if score >= score_threshold:
            sample.status = "approved"
            approved_count += 1
            tag = f"✓ approved (score={score:.2f})"
        else:
            sample.status = "pending"
            tag = f"⚠ pending  (score={score:.2f})"
        print(f"  [{i+1:2d}/{len(dataset)}] {tag}  q={sample.question[:40]}")

    # 保存（带 GT 的版本）
    dataset.save()
    print(f"\n  → 已批量生成 GT，自动 approve {approved_count}/{len(dataset)} 条（阈值 {score_threshold}）")
    stats_after = dataset.stats()
    print(f"  → 现在 with_gt={stats_after['with_ground_truth']}, evaluable={stats_after['evaluable']}")

    # ── 3. 检查是否够评估 ──
    evaluable = [s for s in dataset.samples if s.is_evaluable()]
    if not evaluable:
        print("\n[3/5] 没有可评估样本（GT 全空或未 approved），终止")
        return
    print(f"\n[3/5] 可评估样本 {len(evaluable)} 条（绕过生产 30 条门控，验证用）")

    # ── 4. 跑 RAGAS 评估 ──
    print(f"\n[4/5] 跑 RagasEvaluator.evaluate()（judge LLM={settings.DEFAULT_MODEL}）...")
    print(f"     注：judge 与被评同模型，self-judge 偏差报告需声明")
    evaluator = RagasEvaluator()
    report = await evaluator.evaluate(dataset)
    print(report.summary())
    report_path = report.save()
    print(f"\n  → 报告已保存: {report_path}")

    # ── 5. 对比 4 月基线 ──
    print(f"\n[5/5] 对比 4 月基线（5 条手动集）")
    baseline = {
        "faithfulness": 0.6657616892911011,
        "answer_relevancy": 0.4277726909472417,
        "context_precision": 0.19999999998,
        "context_recall": 0.5,
    }
    print(f"\n  {'指标':<20} {'4月基线':<10} {'9月这批':<10} {'变化':<10}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10}")
    for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        old = baseline[metric]
        new = report.scores.get(metric, 0)
        if new > old:
            delta = f"+{new-old:.3f} ↑"
        elif new < old:
            delta = f"-{old-new:.3f} ↓"
        else:
            delta = "0.000"
        print(f"  {metric:<20} {old:<10.3f} {new:<10.3f} {delta}")

    # ── 输出策略反馈建议（Step 3 雏形）──
    print(f"\n{'='*70}")
    print("策略反馈建议（Step 3 — 复用 EvaluationReport.build_suggested_actions）")
    print(f"{'='*70}")
    suggestions = report.build_suggested_actions()
    if not suggestions:
        print("  无低分样本，无需调整")
    else:
        for s in suggestions:
            print(f"\n  [{s['category']}] sample q={s['question'][:60]}")
            print(f"    低分指标: {s['low_metrics']}")
            print(f"    建议动作: {s['action']}")

    print(f"\n{'='*70}")
    print("Step 1 完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(run_step1())
