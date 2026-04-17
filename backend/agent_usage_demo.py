"""
Agent 框架使用演示

演示可插拔 Agent 架构的多种使用方式：
1. 注册并切换 Agent
2. 单 Agent 对话
3. 流式对话（SSE）
4. 多 Agent 对比模式
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from agent.registry import (
    AgentType,
    setup_registry,
    get_registry,
    UnifiedResponse,
    StreamChunk,
)


# ─────────────────────────────────────────────────────────────
# 真实检索函数（使用 Milvus + ES 混合检索）
# ─────────────────────────────────────────────────────────────

from agent.retrieval import get_retriever_for_simple, get_retriever_for_advanced


# ─────────────────────────────────────────────────────────────
# 演示 1: 基本使用 — 注册 & 切换 Agent
# ─────────────────────────────────────────────────────────────

async def demo_switch_agent():
    """演示如何在运行时切换不同的 Agent"""
    print("\n" + "=" * 60)
    print("演示 1: Agent 切换")
    print("=" * 60)

    # 初始化注册中心
    registry = setup_registry()

    # 列出已注册的 Agent
    print("\n📋 已注册的 Agent:")
    for agent_info in registry.list_registered():
        default_tag = " [默认]" if agent_info["is_default"] else ""
        print(f"   • {agent_info['type']}{default_tag}")

    # 获取默认 Agent（claw）
    agent_default = registry.get()
    print(f"\n🔰 默认 Agent: {agent_default.name} ({agent_default.agent_type.value})")

    # 切换到 simple
    agent_simple = registry.get(AgentType.SIMPLE)
    print(f"🔰 切换到 Simple: {agent_simple.name}")

    # 切换到 advanced
    agent_advanced = registry.get(AgentType.ADVANCED)
    print(f"🔰 切换到 Advanced: {agent_advanced.name}")

    # 切换回 claw
    agent_claw = registry.get(AgentType.CLAW)
    print(f"🔰 切换回 Claw: {agent_claw.name}")


# ─────────────────────────────────────────────────────────────
# 演示 2: 单 Agent 对话
# ─────────────────────────────────────────────────────────────

async def demo_single_chat():
    """演示使用单个 Agent 处理对话"""
    print("\n" + "=" * 60)
    print("演示 2: 单 Agent 对话")
    print("=" * 60)

    registry = setup_registry()

    test_queries = [
        "你好，请介绍一下你自己",
        "什么是 RAG 技术？",
        "RAG 和 Fine-tuning 相比有什么优势？",
    ]

    for agent_type in [AgentType.SIMPLE, AgentType.ADVANCED, AgentType.CLAW]:
        print(f"\n{'─' * 50}")
        print(f"Agent: {agent_type.value.upper()}")
        print(f"{'─' * 50}")

        agent = registry.get(agent_type)

        for query in test_queries[:1]:  # 只演示一个查询
            print(f"\nUser: {query}")

            response = await agent.process(
                query=query,
                session_id=f"demo_session_{agent_type.value}",
            )

            print(f"\nAgent 回答:")
            # 过滤掉非ASCII字符，避免编码错误
            content = response.content[:200]
            content = ''.join([c if ord(c) < 128 else ' ' for c in content])
            print(f"   {content}...")
            print(f"\n   处理时间: {response.processing_time:.2f}s")
            print(f"   Agent 类型: {response.agent_type}")
            if response.intent:
                print(f"   意图识别: {response.intent} (置信度: {response.confidence:.0%})" if response.confidence else "")
            if response.sources_count:
                print(f"   检索文档数: {response.sources_count}")


# ─────────────────────────────────────────────────────────────
# 演示 3: 流式对话
# ─────────────────────────────────────────────────────────────

async def demo_stream_chat():
    """演示流式对话（模拟）"""
    print("\n" + "=" * 60)
    print("演示 3: 流式对话")
    print("=" * 60)

    registry = setup_registry()
    agent = registry.get(AgentType.CLAW)

    query = "RAG 技术在企业知识管理中有哪些应用场景？"
    print(f"\nUser: {query}")
    print(f"\nAgent 回答 (流式输出):\n   ", end="")

    collected_chunks = []
    async for chunk in agent.stream_process(query, session_id="demo_stream"):
        if chunk.event_type == "thinking":
            print(f"\n   Thinking: {chunk.metadata.get('message', 'thinking...')}")
        elif chunk.event_type == "chunk":
            print(chunk.chunk, end="", flush=True)
            collected_chunks.append(chunk.chunk)
        elif chunk.event_type == "intent":
            print(f"\n   Intent: {chunk.metadata.get('intent')}")

    print(f"\n\n   OK 流式输出完成，共 {len(collected_chunks)} 个字符")


# ─────────────────────────────────────────────────────────────
# 演示 4: 多 Agent 对比
# ─────────────────────────────────────────────────────────────

async def demo_compare():
    """演示多 Agent 对比模式"""
    print("\n" + "=" * 60)
    print("演示 4: 多 Agent 对比")
    print("=" * 60)

    registry = setup_registry()

    query = "解释一下什么是向量数据库，它在 RAG 中起什么作用？"
    print(f"\n用户: {query}")

    # 对比所有已注册的 Agent
    results = await registry.compare_all(query, session_id="demo_compare")

    print("\n" + "─" * 60)

    for agent_type, response in results.items():
        print(f"\n{'='*30} {agent_type.upper()} {'='*30}")
        # 过滤掉非ASCII字符，避免编码错误
        content = response.content[:300]
        content = ''.join([c if ord(c) < 128 else ' ' for c in content])
        print(f"回答: {content}...")
        print(f"\n处理信息:")
        print(f"   • Agent 类型: {response.agent_type}")
        print(f"   • 处理时间: {response.processing_time:.2f}s")
        print(f"   • 意图识别: {response.intent or '无'}")
        if response.confidence:
            print(f"   • 置信度: {response.confidence:.0%}")
        if response.sources_count:
            print(f"   • 检索文档数: {response.sources_count}")
        if response.error:
            print(f"   ERROR: {response.error}")


# ─────────────────────────────────────────────────────────────
# 演示 5: API 请求示例
# ─────────────────────────────────────────────────────────────

def demo_api_examples():
    """展示 API 调用示例"""
    print("\n" + "=" * 60)
    print("演示 5: API 调用示例")
    print("=" * 60)

    api_examples = """
    # ── API 端点说明 ──────────────────────────────────────────

    # 1. 列出所有 Agent
    GET /api/agent/list

    # 2. 健康检查
    GET /api/agent/health

    # 3. 单 Agent 对话
    POST /api/agent/chat
    {
    "query": "RAG 技术是什么？",
    "agent_type": "claw",       // simple | advanced | claw
    "session_id": "user123",    // 可选
    "stream": false
    }

    # 4. 流式对话
    POST /api/agent/chat/stream
    {
    "query": "RAG 和 Fine-tuning 的区别？",
    "agent_type": "claw",
    "stream": true
    }
    # 返回 SSE 事件流，包含:
    # - type: connected    → 连接成功
    # - type: thinking     → 正在思考
    # - type: intent       → 意图识别
    # - type: retrieved    → 检索完成
    # - type: reranked     → 精排完成
    # - type: chunk        → 回答内容块
    # - type: done         → 结束

    # 5. 多 Agent 对比
    POST /api/agent/compare
    {
    "query": "什么是 RAG？",
    "agent_types": ["simple", "advanced", "claw"]  // 空则全部对比
    }

    # 6. 获取会话历史
    GET /api/agent/session/{session_id}/history

    # 7. 清空会话
    DELETE /api/agent/session/{session_id}
    """
    print(api_examples)


# ─────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────

async def main():
    print("""
================================================================
        可插拔 Agent 架构演示

    三种 Agent 对比:
    - simple   → 轻量 Chain，适合快速原型
    - advanced → 完整 Agent，适合生产环境
    - claw     → RAG 专属，适合知识库问答
================================================================
    """)

    # 注入真实检索工具（Simple/Advanced Agent 需要）
    registry = setup_registry()

    # 为 Simple Agent 注入真实检索工具
    simple_agent = registry.get(AgentType.SIMPLE)
    if hasattr(simple_agent, '_agent'):
        simple_agent._agent.set_retriever(get_retriever_for_simple())
    print("[OK] 已为 Simple Agent 注入真实检索工具（Milvus + ES 混合检索）")

    # 为 Advanced Agent 注入真实检索工具
    advanced_agent = registry.get(AgentType.ADVANCED)
    if hasattr(advanced_agent, '_agent'):
        advanced_agent._agent.inject_retriever(get_retriever_for_advanced())
    print("[OK] 已为 Advanced Agent 注入真实检索工具（Milvus + ES 混合检索）")

    # 运行演示
    # await demo_switch_agent()
    # await demo_single_chat()
    await demo_stream_chat()
    await demo_compare()
    # demo_api_examples()

    print("\n" + "=" * 60)
    print("演示完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
