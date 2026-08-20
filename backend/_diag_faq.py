"""FAQ 召回排查脚本（临时，排查后删除）。"""
import asyncio
import sys
import traceback

sys.path.insert(0, '.')


async def test():
    try:
        from services.faq_service import faq_service
        # 直接调二次确认看 LLM 返回
        resp = await faq_service.chat.ainvoke(
            "判断下面的候选答案是否准确、完整地回答了用户问题。\n"
            "用户问题：What is RAG?\n候选答案：RAG is Retrieval-Augmented Generation.\n"
            "只回答一个字：是 或 否。"
        )
        text = resp.content if hasattr(resp, "content") else str(resp)
        print(f"[LLM resp] repr={repr(text)[:100]}")
        print(f"[LLM resp] starts_with_是={text.strip().startswith('是')}")
    except Exception as e:
        print(f"[EXC] {type(e).__name__}: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test())
