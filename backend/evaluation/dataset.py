"""
测试集管理

支持两种数据来源：
1. 手动标注：直接编写 JSON 文件（推荐用于核心场景覆盖）
2. 自动从 session 历史生成：从已有对话中抽取样本（快速积累数量）

数据格式（每条样本）：
{
  "question":      "用户问题",
  "answer":        "Agent 实际回答",         # 可为空（评估时自动调用 Agent 生成）
  "contexts":      ["检索到的文档片段1", ...], # 可为空（评估时自动检索）
  "ground_truth":  "标准参考答案",            # 用于 Context Recall 计算，可选
  "metadata": {
    "kb_id":       1,                         # 知识库 ID
    "intent":      "retrieval",               # 意图类型
    "source":      "manual | session",        # 数据来源
    "session_id":  "xxx",                     # 来源会话（若从 session 导入）
    "tags":        ["基础", "技术"]           # 场景标签
  }
}
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import init_logger

logger = init_logger(__name__)

# 测试集和报告目录（相对于本文件的位置）
TESTSET_DIR = Path(__file__).parent / "testsets"
REPORT_DIR = Path(__file__).parent / "reports"

# 确保目录存在
TESTSET_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)


@dataclass
class EvaluationSample:
    """单条评估样本"""
    question: str
    ground_truth: str = ""          # 标准参考答案（不提供则跳过 recall 类指标）
    answer: str = ""                # Agent 实际回答（可为空，运行时填充）
    contexts: List[str] = field(default_factory=list)  # 检索到的上下文（可为空，运行时填充）
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "EvaluationSample":
        return cls(
            question=d["question"],
            ground_truth=d.get("ground_truth", ""),
            answer=d.get("answer", ""),
            contexts=d.get("contexts", []),
            metadata=d.get("metadata", {}),
        )

    def is_complete(self) -> bool:
        """检查是否有足够数据进行评估（至少需要 question + answer + contexts）"""
        return bool(self.question and self.answer and self.contexts)


class EvaluationDataset:
    """测试集管理器"""

    def __init__(self, samples: List[EvaluationSample] = None, name: str = "default"):
        self.samples = samples or []
        self.name = name
        self.created_at = datetime.now().isoformat()

    def add(self, sample: EvaluationSample):
        """添加一条样本"""
        self.samples.append(sample)

    def add_manual(
        self,
        question: str,
        ground_truth: str,
        kb_id: Optional[int] = None,
        tags: List[str] = None,
    ) -> EvaluationSample:
        """
        添加手动标注的样本（仅提供问题和标准答案，运行时自动填充 answer/contexts）

        Args:
            question: 用户问题
            ground_truth: 期望的标准答案
            kb_id: 知识库 ID（评估时自动检索用）
            tags: 场景标签，如 ["基础概念", "操作指引"]
        """
        sample = EvaluationSample(
            question=question,
            ground_truth=ground_truth,
            metadata={
                "kb_id": kb_id,
                "source": "manual",
                "tags": tags or [],
            },
        )
        self.samples.append(sample)
        return sample

    def save(self, path: Optional[str] = None) -> str:
        """保存测试集到 JSON 文件"""
        if path is None:
            path = str(TESTSET_DIR / f"{self.name}.json")

        data = {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat(),
            "count": len(self.samples),
            "samples": [s.to_dict() for s in self.samples],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"[EvaluationDataset] 已保存 {len(self.samples)} 条样本到: {path}")
        return path

    @classmethod
    def load(cls, path: str) -> "EvaluationDataset":
        """从 JSON 文件加载测试集"""
        if not os.path.exists(path):
            # 尝试在 testsets 目录下查找
            alt_path = TESTSET_DIR / path
            if alt_path.exists():
                path = str(alt_path)
            else:
                raise FileNotFoundError(f"测试集文件不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        samples = [EvaluationSample.from_dict(s) for s in data.get("samples", [])]
        dataset = cls(samples=samples, name=data.get("name", "default"))
        dataset.created_at = data.get("created_at", "")

        logger.info(f"[EvaluationDataset] 已加载 {len(samples)} 条样本，来源: {path}")
        return dataset

    @classmethod
    def from_session_history(
        cls,
        session_id: str,
        name: str = None,
        min_sources_count: int = 1,
        max_samples: int = 50,
    ) -> "EvaluationDataset":
        """
        从 session 历史中自动生成测试集

        抽取规则：
        - 只取 intent=retrieval 的对话（问候/澄清类跳过）
        - sources_count >= min_sources_count（有实际检索的对话）
        - answer 和 contexts 直接从历史数据中提取

        注意：这种方式没有 ground_truth，只能计算 faithfulness 和 answer_relevancy，
        不能计算 context_recall。如需 recall，需手动补充 ground_truth。
        """
        from agent.claw_agent.memory.session_store import SessionStore

        store = SessionStore()
        messages = store.get_messages(session_id, limit=200)

        samples = []
        i = 0
        while i < len(messages) - 1 and len(samples) < max_samples:
            msg = messages[i]
            next_msg = messages[i + 1] if i + 1 < len(messages) else None

            if msg.get("role") == "user" and next_msg and next_msg.get("role") == "assistant":
                meta = next_msg.get("metadata", {}) or {}
                intent = meta.get("intent", "")
                sources_count = meta.get("sources_count", 0)
                sources = meta.get("sources", [])

                # 只取有实际检索结果的对话
                if intent not in ("greeting", "clarification") and sources_count >= min_sources_count:
                    contexts = [
                        s.get("chunk_text") or s.get("content", "")
                        for s in sources
                        if s.get("chunk_text") or s.get("content")
                    ]

                    if contexts:
                        sample = EvaluationSample(
                            question=msg["content"],
                            answer=next_msg["content"],
                            contexts=contexts,
                            ground_truth="",  # 需要手动补充
                            metadata={
                                "source": "session",
                                "session_id": session_id,
                                "intent": intent,
                                "sources_count": sources_count,
                                "processing_time_ms": meta.get("processing_time_ms", 0),
                                "tags": [],
                            },
                        )
                        samples.append(sample)

            i += 1

        dataset_name = name or f"session_{session_id[:8]}_{datetime.now().strftime('%Y%m%d')}"
        logger.info(
            f"[EvaluationDataset] 从 session {session_id} 提取了 {len(samples)} 条样本"
        )
        return cls(samples=samples, name=dataset_name)

    @classmethod
    def from_all_sessions(
        cls,
        name: str = None,
        min_sources_count: int = 1,
        max_samples: int = 100,
    ) -> "EvaluationDataset":
        """从所有历史 session 中批量提取样本"""
        from agent.claw_agent.memory.session_store import SessionStore

        store = SessionStore()
        all_sessions = store.list_sessions(limit=200)

        all_samples = []
        for session_info in all_sessions:
            sid = session_info.get("session_id", "")
            if not sid:
                continue
            try:
                ds = cls.from_session_history(
                    session_id=sid,
                    min_sources_count=min_sources_count,
                    max_samples=max_samples - len(all_samples),
                )
                all_samples.extend(ds.samples)
                if len(all_samples) >= max_samples:
                    break
            except Exception as e:
                logger.warning(f"[EvaluationDataset] 提取 session {sid} 失败: {e}")

        dataset_name = name or f"all_sessions_{datetime.now().strftime('%Y%m%d')}"
        logger.info(f"[EvaluationDataset] 从所有 session 共提取 {len(all_samples)} 条样本")
        return cls(samples=all_samples, name=dataset_name)

    def stats(self) -> Dict:
        """数据集统计信息"""
        total = len(self.samples)
        complete = sum(1 for s in self.samples if s.is_complete())
        with_gt = sum(1 for s in self.samples if s.ground_truth)
        sources = {}
        for s in self.samples:
            src = s.metadata.get("source", "unknown")
            sources[src] = sources.get(src, 0) + 1

        return {
            "total": total,
            "complete": complete,    # answer + contexts 都有
            "with_ground_truth": with_gt,
            "incomplete": total - complete,
            "sources": sources,
        }

    def __len__(self):
        return len(self.samples)

    def __repr__(self):
        stats = self.stats()
        return (
            f"EvaluationDataset(name={self.name!r}, "
            f"total={stats['total']}, "
            f"complete={stats['complete']}, "
            f"with_gt={stats['with_ground_truth']})"
        )
