"""
Reranker 服务模块 — 独立的重排序服务

支持多种 Reranker 实现，通过 RERANKER_TYPE 配置切换:
  - llm          → LLM Prompt 式（默认，兼容原有行为）
  - cross_encoder → Cross-Encoder 模型（推荐用于生产环境）
  - none         → 空操作（不重排，直接截断）

用法:
    from services.reranker import get_reranker
    reranker = get_reranker()
    results = reranker.rerank(query, raw_results, top_k=5)
"""

from abc import ABC, abstractmethod
import asyncio
from typing import List, Dict, Optional

from config import settings, init_logger

logger = init_logger(__name__)


class BaseReranker(ABC):
    """Reranker 抽象基类 — 统一接口"""

    @abstractmethod
    async def rerank(self, query: str, results: List[Dict], top_k: int = 5) -> List[Dict]:
        """
        对搜索结果进行重排序。

        Args:
            query: 用户查询文本
            results: 待排序的结果列表，每项至少包含 content 或 chunk_text 字段
            top_k: 返回前 K 条

        Returns:
            重排后的结果列表
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查该 Reranker 是否可用。"""
        pass


class LLMReranker(BaseReranker):
    """
    基于 LLM 的 Prompt 式 Reranker。

    将查询和搜索结果通过 prompt 发送给大模型，
    让模型返回排序后的编号列表。
    """

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self._client = None
        self._api_key = api_key or settings.LITELLM_API_KEY
        self._base_url = base_url or settings.LITELLM_BASE_URL
        self._model = model or getattr(settings, 'LLM_MODEL', 'gpt-4o')

    def _get_client(self):
        """懒加载 OpenAI 客户端（复用连接）。"""
        if self._client is None:
            from langchain_openai import OpenAI
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    def is_available(self) -> bool:
        return bool(self._api_key and self._base_url)

    async def rerank(self, query: str, results: List[Dict], top_k: int = 5) -> List[Dict]:
        if not results:
            return []

        try:
            client = self._get_client()

            # 构建 prompt
            content_lines = []
            for i, result in enumerate(results, 1):
                text = result.get('content', result.get('chunk_text', ''))
                content_lines.append(f"{i}. {text[:500]}")

            prompt = (
                f"请根据以下查询语句，对搜索结果按相关性从高到低排序。\n\n"
                f"查询语句：{query}\n\n"
                f"搜索结果：\n"
                + "\n".join(content_lines)
                + "\n\n"
                "请以 JSON 格式返回，例如：{\"order\": [1,3,2,5,4]}"
            )

            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的信息检索助手，擅长根据查询语句对搜索结果进行相关性排序。"
                            "只返回 JSON，不要包含其他文字。"
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=200,
            )

            # 解析响应
            raw_content = response.choices[0].message.content.strip()

            # 尝试 JSON 解析
            import json, re
            order = list(range(len(results)))  # 默认顺序作为降级

            try:
                parsed = json.loads(raw_content)
                order = parsed.get("order", order)
            except json.JSONDecodeError:
                # 降级：尝试从纯数字列表解析
                numbers = re.findall(r'\d+', raw_content)
                if numbers:
                    order = [int(n) - 1 for n in numbers]

            valid_indices = [idx for idx in order if 0 <= idx < len(results)]
            return [results[idx] for idx in valid_indices[:top_k]]

        except Exception as e:
            logger.error(f"LLM Rerank 失败: {e}")
            return results[:top_k]


class CrossEncoderReranker(BaseReranker):
    """
    基于 Cross-Encoder 的语义 Reranker。

    使用 sentence-transformers 的 CrossEncoder 模型对 (query, doc) 打分，
    效果通常优于 LLM Prompt 方式，且延迟更低、更稳定。

    需要安装: pip install sentence-transformers

    线程安全：模型加载使用 asyncio.Lock 保护，防止并发请求重复加载。
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self._model = None
        self._model_name = model_name
        self._load_lock = None  # 延迟创建，避免 event loop 未就绪时报错

    def _get_load_lock(self):
        """延迟创建 asyncio.Lock（必须在 event loop 内创建）。"""
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        return self._load_lock

    async def _ensure_model_loaded(self):
        """
        加载 CrossEncoder 模型（带并发锁保护）。

        解决 asyncio.gather 并行检索时多个协程同时触发懒加载的竞态问题：
        - 第一个协程获取锁，加载模型
        - 其余协程等待锁释放后，发现 self._model 已不为 None，直接跳过加载
        """
        if self._model is not None:
            return  # 模型已加载，快速返回

        lock = self._get_load_lock()
        async with lock:
            # double-check：拿到锁后再检查一次，避免等待期间另一个协程已加载
            if self._model is not None:
                return

            from sentence_transformers import CrossEncoder
            logger.info(f"[CrossEncoderReranker] 开始加载模型: {self._model_name}...")
            self._model = CrossEncoder(self._model_name)
            logger.info(f"[CrossEncoderReranker] 模型加载完成: {self._model_name}")

    def _get_model(self):
        """同步获取模型（仅用于兼容场景，推荐用 _ensure_model_loaded）。"""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)
            logger.info(f"CrossEncoder 模型加载完成: {self._model_name}")
        return self._model

    def is_available(self) -> bool:
        try:
            import sentence_transformers
            return True
        except ImportError:
            logger.warning("sentence_transformers 未安装，CrossEncoderReranker 不可用")
            return False

    async def rerank(self, query: str, results: List[Dict], top_k: int = 5) -> List[Dict]:
        if not results:
            return []

        try:
            await self._ensure_model_loaded()
            model = self._model

            # 构造 (query, doc) 对
            pairs = [
                (query, r.get('content', r.get('chunk_text', ''))[:512])
                for r in results
            ]

            scores = model.predict(pairs)

            # 按分数降序排列
            scored = list(zip(results, scores))
            scored.sort(key=lambda x: x[1], reverse=True)

            # 返回带 rerank_score 字段的结果
            return [
                {**r, "rerank_score": float(s)}
                for r, s in scored[:top_k]
            ]

        except Exception as e:
            logger.error(f"CrossEncoder Rerank 失败: {e}")
            return results[:top_k]


class NoopReranker(BaseReranker):
    """不做任何重排，直接截断返回前 K 条。用于调试或低延迟场景。"""

    def is_available(self) -> bool:
        return True

    async def rerank(self, query: str, results: List[Dict], top_k: int = 5) -> List[Dict]:
        return results[:top_k]


# ============================================================
# 工厂函数 & 全局实例缓存
# ============================================================

_reranker_instance: Optional[BaseReranker] = None


def get_reranker() -> BaseReranker:
    """
    根据 RERANKER_TYPE 配置返回对应的 Reranker 实例。

    全局只创建一个实例，避免重复初始化模型/客户端。
    通过修改配置即可切换实现方式，无需改动业务代码。
    """
    global _reranker_instance

    if _reranker_instance is not None:
        return _reranker_instance

    reranker_type = getattr(settings, 'RERANKER_TYPE', 'cross_encoder').lower().strip()

    if reranker_type in ('cross_encoder', 'cross-encoder'):
        model_name = getattr(settings, 'RERANKER_MODEL', 'BAAI/bge-reranker-v2-m3')
        instance = CrossEncoderReranker(model_name=model_name)
        if not instance.is_available():
            logger.warning(
                f"配置为 CrossEncoderReranker 但依赖不可用，回退到 LLMReranker"
            )
            instance = LLMReranker()

    elif reranker_type in ('none', 'noop', 'no', 'skip'):
        instance = NoopReranker()

    else:  # default: llm
        instance = LLMReranker()

    _reranker_instance = instance
    logger.info(f"Reranker 初始化完成，类型: {type(instance).__name__}")

    return _reranker_instance


def reset_reranker():
    """重置 Reranker 实例（主要用于测试）。"""
    global _reranker_instance
    _reranker_instance = None
