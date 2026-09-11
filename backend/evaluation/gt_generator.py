"""
LLM 辅助生成 ground_truth 服务

基于检索到的 contexts，调用 LLM 为 question 生成简洁准确的标准参考答案。
仅依据上下文，不编造；上下文不足时返回"上下文不足以回答"。

用途：测试集审核时一键生成 GT 草稿，人工修改后 PATCH 保存。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import init_logger, get_runtime, settings

logger = init_logger(__name__)


def generate_ground_truth(question: str, contexts: list) -> str:
    """
    基于 contexts 为 question 生成 ground_truth 草稿

    Args:
        question: 用户问题
        contexts: 检索到的文档片段列表

    Returns:
        生成的参考答案字符串；异常时返回空串
    """
    if not question or not contexts:
        logger.warning("[GT Generator] question 或 contexts 为空，跳过生成")
        return ""

    try:
        from openai import OpenAI

        base_url = get_runtime("LITELLM_BASE_URL", settings.LITELLM_BASE_URL)
        api_key = get_runtime("LITELLM_API_KEY", settings.LITELLM_API_KEY)
        model = get_runtime("DEFAULT_MODEL", settings.DEFAULT_MODEL)

        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        # 拼接上下文
        context_text = "\n\n---\n\n".join(contexts)

        system_prompt = (
            "你是一个严谨的问答助手。请根据下方检索到的上下文，为用户问题生成一个简洁准确的标准参考答案。"
            "要求：\n"
            "1. 仅依据上下文内容回答，不编造或补充外部信息\n"
            "2. 答案应简洁直接，覆盖问题核心\n"
            "3. 如果上下文信息不足以回答问题，请回答：上下文不足以回答该问题\n"
            "4. 用中文回答"
        )

        user_prompt = (
            f"## 检索到的上下文\n\n{context_text}\n\n"
            f"## 问题\n\n{question}\n\n"
            f"## 请生成标准参考答案"
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,  # 低温度确保答案稳定
            max_tokens=500,
        )

        result = response.choices[0].message.content.strip()
        logger.info(f"[GT Generator] 已生成 GT 草稿，长度 {len(result)} 字符")
        return result

    except Exception as e:
        logger.error(f"[GT Generator] 生成 ground_truth 失败: {e}")
        return ""
