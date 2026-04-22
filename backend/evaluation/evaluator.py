"""
Ragas 核心评估器

对接本项目的数据格式，封装 Ragas 评估流程。

支持的指标：
  - faithfulness        忠实度：回答是否基于检索内容，不产生幻觉
  - answer_relevancy    答案相关性：回答是否真正回答了问题
  - context_precision   上下文精准度：检索到的内容是否都与问题相关（需 ground_truth）
  - context_recall      上下文召回率：是否召回了回答问题所需的所有信息（需 ground_truth）

指标与数据要求对应关系：
  ┌───────────────────┬──────────┬─────────┬──────────────┐
  │ 指标               │ question │ answer  │ ground_truth │
  ├───────────────────┼──────────┼─────────┼──────────────┤
  │ faithfulness       │    ✓    │    ✓    │      -       │
  │ answer_relevancy   │    ✓    │    ✓    │      -       │
  │ context_precision  │    ✓    │    -    │      ✓       │
  │ context_recall     │    ✓    │    -    │      ✓       │
  └───────────────────┴──────────┴─────────┴──────────────┘

使用 LLM-as-Judge 模式，需要配置 LiteLLM 作为评估用的 LLM。
"""

import asyncio
import json
import os
import sys
from typing import List, Optional, Dict, Any
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import settings, init_logger
from evaluation.dataset import EvaluationDataset, EvaluationSample

logger = init_logger(__name__)


class EvaluationReport:
    """评估报告"""

    def __init__(
        self,
        scores: Dict[str, float],
        sample_scores: List[Dict],
        dataset_name: str,
        metrics_used: List[str],
        evaluated_at: str = None,
        total_samples: int = 0,
        skipped_samples: int = 0,
        error: Optional[str] = None,
    ):
        self.scores = scores                      # 整体平均分
        self.sample_scores = sample_scores        # 每条样本的得分
        self.dataset_name = dataset_name
        self.metrics_used = metrics_used
        self.evaluated_at = evaluated_at or datetime.now().isoformat()
        self.total_samples = total_samples
        self.skipped_samples = skipped_samples
        self.error = error

    def to_dict(self) -> Dict:
        return {
            "dataset_name": self.dataset_name,
            "evaluated_at": self.evaluated_at,
            "metrics_used": self.metrics_used,
            "total_samples": self.total_samples,
            "skipped_samples": self.skipped_samples,
            "scores": self.scores,
            "sample_scores": self.sample_scores,
            "error": self.error,
        }

    def save(self, report_dir: str = None) -> str:
        """保存报告到 JSON 文件"""
        from evaluation.dataset import REPORT_DIR
        report_dir = report_dir or str(REPORT_DIR)
        os.makedirs(report_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"eval_{self.dataset_name}_{timestamp}.json"
        filepath = os.path.join(report_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"[EvaluationReport] 报告已保存: {filepath}")
        return filepath

    def summary(self) -> str:
        """生成可读的摘要文本"""
        lines = [
            f"📊 RAG 评估报告",
            f"─────────────────────────────",
            f"数据集：{self.dataset_name}",
            f"评估时间：{self.evaluated_at}",
            f"评估样本：{self.total_samples} 条（跳过 {self.skipped_samples} 条）",
            f"使用指标：{', '.join(self.metrics_used)}",
            f"─────────────────────────────",
        ]

        grade_map = {
            "faithfulness": "忠实度",
            "answer_relevancy": "答案相关性",
            "context_precision": "上下文精准度",
            "context_recall": "上下文召回率",
        }

        for metric, score in self.scores.items():
            label = grade_map.get(metric, metric)
            bar = self._score_bar(score)
            lines.append(f"{label:<12} {score:.3f}  {bar}")

        if self.error:
            lines.append(f"\n⚠️  错误信息: {self.error}")

        return "\n".join(lines)

    @staticmethod
    def _score_bar(score: float, width: int = 20) -> str:
        filled = int(score * width)
        return "█" * filled + "░" * (width - filled)


class RagasEvaluator:
    """
    Ragas 评估器

    自动选择可用的指标（根据数据是否包含 ground_truth）。
    支持两种工作模式：
      - batch：批量评估整个测试集（推荐）
      - single：评估单条对话（用于实时监控）
    """

    def __init__(
        self,
        llm_base_url: str = None,
        llm_api_key: str = None,
        llm_model: str = None,
    ):
        """
        初始化评估器

        Args:
            llm_base_url: LLM 接口地址，默认使用项目 LiteLLM 配置
            llm_api_key:  LLM API Key
            llm_model:    评估用 LLM 模型名，默认使用项目默认模型
        """
        self.llm_base_url = llm_base_url or settings.LITELLM_BASE_URL
        self.llm_api_key = llm_api_key or settings.LITELLM_API_KEY
        self.llm_model = llm_model or settings.DEFAULT_MODEL
        self._ragas_llm = None
        self._ragas_embeddings = None

    def _get_ragas_llm(self):
        """懒加载 Ragas 用的 LLM（包装成 Ragas 所需格式）"""
        if self._ragas_llm is None:
            try:
                from ragas.llms import LangchainLLMWrapper
                from langchain_openai import ChatOpenAI

                llm = ChatOpenAI(
                    model=self.llm_model,
                    base_url=self.llm_base_url,
                    api_key=self.llm_api_key,
                    temperature=0,  # 评估用 LLM 固定 temperature=0，保证可重复性
                )
                self._ragas_llm = LangchainLLMWrapper(llm)
                logger.info(f"[RagasEvaluator] LLM 初始化完成: {self.llm_model}")
            except ImportError:
                raise ImportError(
                    "Ragas 未安装，请执行: pip install ragas>=0.1.0"
                )
        return self._ragas_llm

    def _get_ragas_embeddings(self):
        """懒加载 Ragas 用的 Embeddings"""
        if self._ragas_embeddings is None:
            try:
                from ragas.embeddings import LangchainEmbeddingsWrapper
                from langchain_openai import OpenAIEmbeddings

                embeddings = OpenAIEmbeddings(
                    model=settings.EMBEDDING_MODEL,
                    base_url=self.llm_base_url,
                    api_key=self.llm_api_key,
                )
                self._ragas_embeddings = LangchainEmbeddingsWrapper(embeddings)
            except Exception as e:
                logger.warning(f"[RagasEvaluator] Embeddings 初始化失败（answer_relevancy 将跳过）: {e}")
        return self._ragas_embeddings

    def _build_metrics(self, has_ground_truth: bool) -> List:
        """根据数据情况选择合适的指标"""
        from ragas.metrics import faithfulness, answer_relevancy

        metrics = [faithfulness]

        # answer_relevancy 需要 embeddings
        try:
            embeddings = self._get_ragas_embeddings()
            if embeddings:
                metrics.append(answer_relevancy)
        except Exception:
            pass

        if has_ground_truth:
            try:
                from ragas.metrics import context_precision, context_recall
                metrics.extend([context_precision, context_recall])
            except ImportError:
                logger.warning("[RagasEvaluator] context_precision/recall 不可用")

        return metrics

    async def evaluate(
        self,
        dataset: EvaluationDataset,
        metrics: Optional[List[str]] = None,
    ) -> EvaluationReport:
        """
        批量评估测试集

        Args:
            dataset: EvaluationDataset 实例
            metrics: 指定评估指标列表（None 则自动选择）
                     可选: ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]

        Returns:
            EvaluationReport
        """
        logger.info(f"[RagasEvaluator] 开始评估数据集: {dataset.name}，共 {len(dataset)} 条")

        # 过滤出可用的样本（必须有 question + answer + contexts）
        valid_samples = [s for s in dataset.samples if s.is_complete()]
        skipped = len(dataset) - len(valid_samples)

        if not valid_samples:
            logger.warning("[RagasEvaluator] 没有可用样本（缺少 answer 或 contexts），请先运行 Agent 填充数据")
            return EvaluationReport(
                scores={},
                sample_scores=[],
                dataset_name=dataset.name,
                metrics_used=[],
                total_samples=0,
                skipped_samples=skipped,
                error="没有可用样本，请先通过 fill_dataset() 填充 answer 和 contexts",
            )

        has_ground_truth = any(s.ground_truth for s in valid_samples)

        try:
            from datasets import Dataset as HFDataset
            from ragas import evaluate as ragas_evaluate

            # 构建 Ragas 输入格式
            data_dict = {
                "question": [s.question for s in valid_samples],
                "answer": [s.answer for s in valid_samples],
                "contexts": [s.contexts for s in valid_samples],
            }
            if has_ground_truth:
                data_dict["ground_truth"] = [s.ground_truth or "" for s in valid_samples]

            hf_dataset = HFDataset.from_dict(data_dict)

            # 选择指标
            ragas_metrics = self._build_metrics(has_ground_truth)
            metric_names = [m.name for m in ragas_metrics]

            if metrics:
                # 过滤用户指定的指标
                name_map = {m.name: m for m in ragas_metrics}
                ragas_metrics = [name_map[n] for n in metrics if n in name_map]
                metric_names = [m.name for m in ragas_metrics]

            # 给所有指标注入 LLM 和 Embeddings
            llm = self._get_ragas_llm()
            embeddings = self._get_ragas_embeddings()
            for metric in ragas_metrics:
                metric.llm = llm
                if hasattr(metric, "embeddings") and embeddings:
                    metric.embeddings = embeddings

            logger.info(f"[RagasEvaluator] 使用指标: {metric_names}")

            # 执行评估（Ragas 是同步 API，用 to_thread 包装）
            # 显式传 llm/embeddings，避免 ragas 用默认 OpenAI 直连导致 403
            eval_kwargs = dict(
                dataset=hf_dataset,
                metrics=ragas_metrics,
                llm=llm,
            )
            if embeddings:
                eval_kwargs["embeddings"] = embeddings

            result = await asyncio.to_thread(
                ragas_evaluate,
                **eval_kwargs,
            )

            # 解析结果
            # ragas 0.4.x: EvaluationResult
            #   .scores → List[Dict[str, Any]]（每条样本各指标得分）
            #   ._repr_dict → Dict[str, float]（各指标平均分）
            #   .__getitem__(key) → List[float]（某指标全部样本得分）
            #   无 .get() 方法
            avg_scores = getattr(result, "_repr_dict", {})
            scores = {}
            for metric_name in metric_names:
                if metric_name in avg_scores:
                    val = avg_scores[metric_name]
                    scores[metric_name] = float(val) if val is not None else 0.0

            # 每条样本的得分
            # result.scores 是 List[Dict]，每个 dict 是一条样本的各指标得分
            result_scores = result.scores if hasattr(result, "scores") else []
            sample_scores = []
            for i, sample in enumerate(valid_samples):
                if i < len(result_scores):
                    row = result_scores[i]
                else:
                    row = {}
                sample_score = {
                    "question": sample.question[:100],
                    "scores": {
                        m: float(row.get(m, 0)) if m in row else 0.0
                        for m in metric_names
                    },
                    "metadata": sample.metadata,
                }
                sample_scores.append(sample_score)

            report = EvaluationReport(
                scores=scores,
                sample_scores=sample_scores,
                dataset_name=dataset.name,
                metrics_used=metric_names,
                total_samples=len(valid_samples),
                skipped_samples=skipped,
            )

            logger.info(f"[RagasEvaluator] 评估完成: {scores}")
            return report

        except ImportError as e:
            msg = f"依赖缺失: {e}. 请执行: pip install ragas datasets"
            logger.error(f"[RagasEvaluator] {msg}")
            return EvaluationReport(
                scores={}, sample_scores=[],
                dataset_name=dataset.name, metrics_used=[],
                total_samples=0, skipped_samples=skipped, error=msg,
            )
        except Exception as e:
            logger.error(f"[RagasEvaluator] 评估失败: {e}")
            return EvaluationReport(
                scores={}, sample_scores=[],
                dataset_name=dataset.name, metrics_used=[],
                total_samples=len(valid_samples), skipped_samples=skipped,
                error=str(e),
            )

    async def fill_dataset(
        self,
        dataset: EvaluationDataset,
        knowledge_base_id: Optional[int] = None,
        agent_type: str = "claw",
        trace_fill: bool = False,
    ) -> EvaluationDataset:
        """
        自动填充测试集中缺少 answer 或 contexts 的样本

        对每条 question 调用 Agent，获取 answer 和 contexts，
        然后回填到样本中。适用于只有 question + ground_truth 的手动标注集。

        Args:
            dataset: 待填充的数据集
            knowledge_base_id: 知识库 ID（覆盖样本中的 kb_id）
            agent_type: 使用哪个 Agent（默认 claw）
            trace_fill: 是否对 fill 阶段的 Agent 调用启用追踪（默认 False）。
                        开启后可在 Langfuse/Phoenix 中查看每条样本的检索与生成过程，
                        适合调试某条样本分低时使用。生产批量评估建议保持 False，
                        避免在追踪后端产生大量噪声数据。
        """
        import tempfile
        import shutil
        from pathlib import Path
        from agent.registry import get_registry, setup_registry, AgentType
        from agent.claw_agent.memory.memory_manager import MemoryManager
        from agent.claw_agent.memory.session_store import SessionStore

        # 创建临时目录用于隔离评估会话，避免污染用户会话
        tmp_dir = Path(tempfile.mkdtemp(prefix="eval_fill_"))
        tmp_session_store = SessionStore(sessions_dir=tmp_dir)

        registry = get_registry()

        # 保存原始 session_store，评估后恢复，避免影响用户对话
        original_session_store = None
        if hasattr(registry, '_configs') and AgentType.CLAW in registry._configs:
            original_session_store = registry._configs[AgentType.CLAW].get('session_store')

        # 强制重新初始化 registry，使用临时 SessionStore
        setup_registry(
            claw_memory_manager=MemoryManager(),
            claw_session_store=tmp_session_store,
        )

        # agent_type 可能是字符串（来自 API 参数），需要转成枚举
        if isinstance(agent_type, str):
            try:
                agent_type_enum = AgentType(agent_type.lower())
            except ValueError:
                valid = [e.value for e in AgentType]
                raise ValueError(f"不支持的 agent_type: {agent_type!r}，可选值: {valid}")
        else:
            agent_type_enum = agent_type

        agent = registry.get(agent_type=agent_type_enum, fresh=True)

        # 强制更新 session_store 并重新创建 workflow
        # 因为 ClawAgentAdapter 在 __init__ 时保存了 session_store 引用
        if hasattr(agent, '_session_store'):
            agent._session_store = tmp_session_store
        if hasattr(agent, '_workflow'):
            agent._workflow = None

        # 是否为 fill 阶段注入追踪 callbacks
        fill_callbacks = []
        if trace_fill:
            from evaluation.tracing import get_callbacks
            fill_callbacks = get_callbacks()
            if fill_callbacks:
                logger.info(f"[RagasEvaluator] fill_dataset 追踪已启用，tag=eval_fill/{dataset.name}")

        filled_count = 0

        for i, sample in enumerate(dataset.samples):
            if sample.is_complete():
                continue  # 已有数据，跳过

            try:
                kb_id = knowledge_base_id or sample.metadata.get("kb_id")
                response = await agent.process(
                    query=sample.question,
                    knowledge_base_id=kb_id,
                    callbacks=fill_callbacks or None,
                )

                # 提取 answer
                sample.answer = response.content or ""

                # 提取 contexts（从 metadata.sources 中获取）
                sources = response.metadata.get("sources", []) if response.metadata else []
                if not sources and hasattr(response, 'sources'):
                    sources = response.sources or []

                sample.contexts = [
                    s.get("chunk_text") or s.get("content", "")
                    for s in sources
                    if s.get("chunk_text") or s.get("content")
                ]

                filled_count += 1
                logger.info(f"[RagasEvaluator] 填充样本 {i+1}/{len(dataset)}: {sample.question[:50]} (contexts={len(sample.contexts)})")

            except Exception as e:
                logger.warning(f"[RagasEvaluator] 样本 {i} 填充失败: {e}")

        # 清理临时会话目录
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.info(f"[RagasEvaluator] 已清理临时会话目录: {tmp_dir}")
        except Exception as e:
            logger.warning(f"[RagasEvaluator] 清理临时目录失败: {e}")

        # 恢复原始 session_store，确保用户对话不受影响
        if original_session_store:
            setup_registry(
                claw_memory_manager=MemoryManager(),
                claw_session_store=original_session_store,
            )
            logger.info("[RagasEvaluator] 已恢复原始 SessionStore")

        logger.info(f"[RagasEvaluator] 共填充 {filled_count} 条样本")
        return dataset

    async def evaluate_single(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        ground_truth: str = "",
    ) -> Dict[str, float]:
        """
        评估单条对话（用于实时质量监控）

        Returns:
            各指标得分字典，如 {"faithfulness": 0.85, "answer_relevancy": 0.92}
        """
        sample = EvaluationSample(
            question=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
        )
        dataset = EvaluationDataset(samples=[sample], name="single_eval")
        report = await self.evaluate(dataset)
        return report.scores
