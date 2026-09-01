"""
多格式测试集导入适配器

支持格式：
- ours: 本项目格式（{name, samples: [{question, answer, contexts, ground_truth, metadata, status}]}）
- ragas: RAGAS 标准（flat list [{question, answer, contexts, ground_truth}] 或 datasets 库格式 {examples: [...]}）
- crudrag: CRUD-RAG 格式（字段名 query/answer/ctxs 或类似）
- nfcorpus: BEIR 标准格式（{queries: {id: text}, qrels: {id: {docid: rel}}, corpus: {id: {text}}}）

字段名推断来源：
- RAGAS: https://github.com/explodinggradients/ragas (datasets 库格式)
- CRUD-RAG: https://github.com/njuptjackwang/CRUD-RAG (CRUD-RAG benchmark)
- NFCorpus: BEIR 标准格式 https://github.com/beir-cellar/beir
"""

import os
import sys
from typing import List, Dict, Any, Union

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import init_logger
from evaluation.dataset import EvaluationSample

logger = init_logger(__name__)


def detect_format(data: Union[Dict, List]) -> str:
    """
    探测 JSON 结构，返回格式名称

    Args:
        data: 解析后的 JSON 数据（dict 或 list）

    Returns:
        "ours" | "ragas" | "crudrag" | "nfcorpus" | "unknown"
    """
    if isinstance(data, list):
        # flat list → 检查 RAGAS 还是 CRUD-RAG
        if len(data) == 0:
            return "unknown"
        first = data[0]
        if not isinstance(first, dict):
            return "unknown"
        # RAGAS: question/user_input + ground_truth/ground_truth_answer
        if "question" in first or "user_input" in first:
            if "ground_truth" in first or "ground_truth_answer" in first:
                return "ragas"
            # 也可能是 RAGAS 格式但缺 ground_truth
            if "contexts" in first or "context" in first:
                return "ragas"
        # CRUD-RAG: query/answer/ctxs 或类似
        if "query" in first or "ctxs" in first:
            return "crudrag"
        # fallback：有 question 的当 RAGAS
        if "question" in first:
            return "ragas"
        return "unknown"

    if isinstance(data, dict):
        # NFCorpus: BEIR 格式 {queries, qrels, corpus}
        if "queries" in data and "qrels" in data and "corpus" in data:
            return "nfcorpus"

        # 本项目格式: {name, samples: [{question, metadata}]}
        samples = data.get("samples")
        if isinstance(samples, list):
            if len(samples) > 0 and isinstance(samples[0], dict):
                first = samples[0]
                if "question" in first and "metadata" in first:
                    return "ours"
                # samples 里可能是 RAGAS 格式
                if "question" in first:
                    return "ragas"
                if "query" in first:
                    return "crudrag"
            # 空 samples 但有 name → 认为是 ours
            if "name" in data:
                return "ours"

        # RAGAS datasets 库格式: {examples: [...]}
        examples = data.get("examples")
        if isinstance(examples, list) and len(examples) > 0:
            if isinstance(examples[0], dict) and ("question" in examples[0] or "user_input" in examples[0]):
                return "ragas"

        # CRUD-RAG 包裹格式: {data: [...]} 或 {queries: [...]}
        for key in ("data", "queries", "samples"):
            sub = data.get(key)
            if isinstance(sub, list) and len(sub) > 0 and isinstance(sub[0], dict):
                if "query" in sub[0] or "ctxs" in sub[0]:
                    return "crudrag"

        return "unknown"

    return "unknown"


def convert_to_ours(data: Union[Dict, List], fmt: str = "auto") -> List[EvaluationSample]:
    """
    将外部格式数据归一化为本项目 EvaluationSample 列表

    Args:
        data: 解析后的 JSON 数据
        fmt: 格式名称；"auto" 时自动探测

    Returns:
        EvaluationSample 列表（导入样本默认 status=pending）
    """
    if fmt == "auto":
        fmt = detect_format(data)

    if fmt == "ours":
        return _convert_ours(data)
    elif fmt == "ragas":
        return _convert_ragas(data)
    elif fmt == "crudrag":
        return _convert_crudrag(data)
    elif fmt == "nfcorpus":
        return _convert_nfcorpus(data)
    else:
        logger.warning(f"[Importers] 未知格式: {fmt}，尝试 fallback 到 RAGAS")
        return _convert_ragas(data)


def _convert_ours(data: Dict) -> List[EvaluationSample]:
    """本项目格式转换（保留原 status，无则 pending）"""
    samples = data.get("samples", [])
    result = []
    for s in samples:
        result.append(EvaluationSample.from_dict(s))
    return result


def _convert_ragas(data: Union[Dict, List]) -> List[EvaluationSample]:
    """
    RAGAS 标准格式转换

    支持两种形态：
    1. flat list: [{question, answer, contexts, ground_truth}, ...]
    2. datasets 库格式: {examples: [{question/user_input, answer/response, contexts, ground_truth/ground_truth_answer}]}
    """
    if isinstance(data, dict) and "examples" in data:
        items = data["examples"]
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "samples" in data:
        items = data["samples"]
    else:
        items = [data] if isinstance(data, dict) else []

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        question = item.get("question") or item.get("user_input") or ""
        answer = item.get("answer") or item.get("response") or ""
        contexts = item.get("contexts") or item.get("context") or []
        ground_truth = item.get("ground_truth") or item.get("ground_truth_answer") or ""

        if not question:
            continue

        result.append(EvaluationSample(
            question=question,
            answer=answer,
            contexts=contexts if isinstance(contexts, list) else [str(contexts)],
            ground_truth=ground_truth,
            metadata={"source": "import_ragas"},
            status="pending",
        ))
    return result


def _convert_crudrag(data: Union[Dict, List]) -> List[EvaluationSample]:
    """
    CRUD-RAG 格式转换

    CRUD-RAG benchmark 公开格式字段名：
    - query: 用户查询
    - answer: 答案
    - ctxs / contexts: 检索到的上下文
    - gt / golden_answer: 标准答案
    """
    if isinstance(data, dict):
        for key in ("data", "queries", "samples"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        else:
            items = [data]
    elif isinstance(data, list):
        items = data
    else:
        items = []

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        question = item.get("query") or item.get("question") or ""
        answer = item.get("answer") or ""
        contexts = item.get("ctxs") or item.get("contexts") or []
        ground_truth = item.get("gt") or item.get("golden_answer") or item.get("ground_truth") or ""

        if not question:
            continue

        result.append(EvaluationSample(
            question=question,
            answer=answer,
            contexts=contexts if isinstance(contexts, list) else [str(contexts)],
            ground_truth=ground_truth,
            metadata={"source": "import_crudrag"},
            status="pending",
        ))
    return result


def _convert_nfcorpus(data: Dict) -> List[EvaluationSample]:
    """
    NFCorpus (BEIR 标准格式) 转换

    BEIR 格式：
    - queries: {query_id: query_text}
    - qrels: {query_id: {doc_id: relevance_score}}
    - corpus: {doc_id: {text: document_text, title: ...}}

    NFCorpus 无 answer/ground_truth，只有 qrel 关联：
    - answer 留空（待 fill）
    - contexts = qrel 相关文档的 corpus text 拼接
    - ground_truth = qrel 相关文档的 corpus text 拼接（作为参考答案素材）
    """
    queries = data.get("queries", {})
    qrels = data.get("qrels", {})
    corpus = data.get("corpus", {})

    result = []
    for qid, qtext in queries.items():
        if not qtext:
            continue

        # 获取相关文档
        rel_docs = qrels.get(qid, {})
        doc_texts = []
        for doc_id in rel_docs:
            doc = corpus.get(doc_id, {})
            doc_text = doc.get("text") or doc.get("title") or ""
            if doc_text:
                doc_texts.append(doc_text)

        result.append(EvaluationSample(
            question=qtext,
            answer="",  # NFCorpus 无答案，待 fill
            contexts=doc_texts,
            ground_truth="\n\n".join(doc_texts) if doc_texts else "",  # 相关文档拼接作为参考
            metadata={
                "source": "import_nfcorpus",
                "query_id": qid,
            },
            status="pending",
        ))
    return result
