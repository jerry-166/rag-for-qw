"""
RAG 评估与追踪模块

基于 Ragas 框架，为本项目提供完整的 RAG 质量评估能力，
并支持 Phoenix / Langfuse 追踪后端快速切换。

模块结构：
  evaluation/
  ├── evaluator.py        - 核心评估器（对接项目数据格式）
  ├── dataset.py          - 测试集管理（手动标注 + 自动生成）
  ├── tracing.py          - 统一追踪封装（Phoenix / Langfuse / None 快速切换）
  ├── testsets/           - 测试集 JSON 文件存放目录
  └── reports/            - 评估报告存放目录

快速开始 — 评估：
  from evaluation import RagasEvaluator, EvaluationDataset
  
  evaluator = RagasEvaluator()
  dataset = EvaluationDataset.load("testsets/default.json")
  report = await evaluator.evaluate(dataset)
  report.save("reports/")

快速开始 — 追踪：
  from evaluation.tracing import setup_tracing, get_callbacks

  # 1. 应用启动时
  setup_tracing()  # 读取 TRACER_BACKEND 环境变量

  # 2. Agent 调用时
  result = await agent.ainvoke(input, config={"callbacks": get_callbacks()})

  # 3. 切换后端只需改 .env
  # TRACER_BACKEND=phoenix  → 本地 Phoenix UI
  # TRACER_BACKEND=langfuse → Langfuse 自托管/云服务
  # TRACER_BACKEND=none     → 关闭追踪
"""

from .evaluator import RagasEvaluator
from .dataset import EvaluationDataset, EvaluationSample

__all__ = [
    "RagasEvaluator",
    "EvaluationDataset",
    "EvaluationSample",
]
