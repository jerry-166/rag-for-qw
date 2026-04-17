"""
Agent对比演示脚本

演示简单Agent和高级Agent的差异，展示从简单到复杂的演进过程。

运行方式：
    cd backend
    python -m agent.demo_comparison

测试场景：
1. 简单问候 - 两种Agent都能处理
2. 知识检索 - 简单Agent直接检索，高级Agent进行意图识别
3. 对比分析 - 简单Agent可能处理不好，高级Agent会拆解任务
4. 多轮对话 - 简单Agent无记忆，高级Agent支持追问
5. 异常处理 - 简单Agent简单捕获，高级Agent有完善机制
"""
import asyncio
import time
from typing import List, Dict, Any
import json

# 添加backend/agent目录到搜索路径
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入Agent
from agent.simple.agent import SimpleRAGAgent
from agent.advanced.agent import AdvancedRAGAgent


# ==================== 模拟检索工具 ====================

def mock_retriever(query: str, top_k: int = 5, **kwargs) -> List[Dict[str, Any]]:
    """模拟知识库检索"""
    knowledge_base = {
        "RAG": [
            {"content": "RAG（Retrieval-Augmented Generation）是一种结合检索和生成的技术", "score": 0.98},
            {"content": "RAG通过从知识库检索相关信息来增强LLM的回答能力", "score": 0.95},
            {"content": "RAG可以有效减少幻觉问题，提高回答的准确性", "score": 0.92},
        ],
        "机器学习": [
            {"content": "机器学习是人工智能的一个分支，让计算机从数据中学习", "score": 0.97},
            {"content": "常见的机器学习算法包括监督学习、无监督学习、强化学习", "score": 0.94},
        ],
        "LangChain": [
            {"content": "LangChain是一个用于构建LLM应用的框架", "score": 0.96},
            {"content": "LangChain提供了Chains、Agents、Memory等核心组件", "score": 0.93},
        ],
        "LlamaIndex": [
            {"content": "LlamaIndex是一个数据框架，用于将私有数据连接到LLM", "score": 0.95},
            {"content": "LlamaIndex专注于索引和检索，与LangChain互补", "score": 0.91},
        ],
    }
    
    # 简单匹配
    results = []
    for key, docs in knowledge_base.items():
        if key.lower() in query.lower():
            results.extend(docs)
    
    if not results:
        # 返回通用结果
        results = [
            {"content": f"这是关于'{query}'的通用信息", "score": 0.7},
            {"content": f"更多关于'{query}'的背景知识", "score": 0.65},
        ]
    
    return results[:top_k]


def mock_compare_tool(items: List[str], aspects: List[str] = None, **kwargs) -> str:
    """模拟对比工具"""
    if len(items) < 2:
        return "对比需要至少两个项目"
    
    comparison = f"对比分析：{items[0]} vs {items[1]}\n\n"
    comparison += f"1. {items[0]}特点：专注于简单性和易用性\n"
    comparison += f"2. {items[1]}特点：专注于数据索引和检索\n"
    comparison += f"3. 主要区别：设计目标不同，可以结合使用\n"
    
    return comparison


# ==================== 测试场景 ====================

TEST_QUERIES = [
    {
        "id": 1,
        "category": "问候",
        "query": "你好",
        "description": "简单问候，两种Agent都应正常处理",
        "expected_diff": "无明显差异",
    },
    {
        "id": 2,
        "category": "知识检索",
        "query": "什么是RAG技术？",
        "description": "简单知识检索，两种Agent都能处理",
        "expected_diff": "高级Agent会识别为RETRIEVAL意图，可能更准确",
    },
    {
        "id": 3,
        "category": "对比分析",
        "query": "对比一下LangChain和LlamaIndex的区别",
        "description": "需要对比分析，测试任务拆解能力",
        "expected_diff": "简单Agent直接检索；高级Agent会拆解为检索+对比+生成三步",
    },
    {
        "id": 4,
        "category": "深度分析",
        "query": "分析一下RAG技术的优势和局限性",
        "description": "需要深度分析，测试复杂任务处理",
        "expected_diff": "高级Agent会规划更详细的分析步骤",
    },
    {
        "id": 5,
        "category": "多轮追问",
        "query": "它还有什么特点？",
        "description": "追问上一轮的RAG话题，测试对话管理",
        "expected_diff": "简单Agent无记忆；高级Agent能识别追问并关联上下文",
    },
    {
        "id": 6,
        "category": "澄清请求",
        "query": "给我介绍一下",
        "description": "模糊的查询，测试澄清处理",
        "expected_diff": "高级Agent可能请求澄清；简单Agent会直接检索",
    },
]


# ==================== 演示类 ====================

class AgentComparisonDemo:
    """Agent对比演示"""
    
    def __init__(self):
        self.simple_agent = None
        self.advanced_agent = None
        self.results = []
    
    def setup(self):
        """初始化Agent"""
        print("=" * 80)
        print("初始化Agent...")
        print("=" * 80)
        
        # 创建简单Agent
        print("\n[1/2] 创建简单Agent...")
        self.simple_agent = SimpleRAGAgent()
        self.simple_agent.set_retriever(mock_retriever)
        print("  OK 简单Agent创建完成")
        print("  - 使用LangChain Chain结构")
        print("  - 直接调用检索工具")
        print("  - 无复杂状态管理")
        
        # 创建高级Agent
        print("\n[2/2] 创建高级Agent...")
        self.advanced_agent = AdvancedRAGAgent(config={"use_llm": False})
        self.advanced_agent.inject_retriever(mock_retriever)
        self.advanced_agent.inject_custom_tool("compare", mock_compare_tool, "对比工具")
        print("  OK 高级Agent创建完成")
        print("  - 使用LangGraph工作流")
        print("  - 意图识别 + 实体提取 + 任务规划")
        print("  - 完整对话管理 + 异常处理")
        print("  - 支持工具动态选择和调用")
    
    async def run_comparison(self):
        """运行对比测试"""
        print("\n" + "=" * 80)
        print("开始对比测试")
        print("=" * 80)
        
        session_id = "demo_session"
        
        for test_case in TEST_QUERIES:
            print(f"\n{'─' * 80}")
            print(f"测试 #{test_case['id']} [{test_case['category']}]")
            print(f"{'─' * 80}")
            print(f"查询: {test_case['query']}")
            print(f"描述: {test_case['description']}")
            print(f"预期差异: {test_case['expected_diff']}")
            
            # 测试简单Agent
            print("\n  [简单Agent]")
            simple_start = time.time()
            try:
                # 获取历史用于简单Agent
                simple_history = []
                if test_case['id'] == 5:  # 追问场景
                    simple_history = [
                        {"role": "user", "content": "什么是RAG技术？"},
                        {"role": "assistant", "content": "RAG是检索增强生成技术..."},
                    ]
                
                simple_response = await self.simple_agent.process(
                    test_case['query'],
                    chat_history=simple_history
                )
                simple_time = time.time() - simple_start
                print(f"    处理时间: {simple_time:.3f}s")
                print(f"    回答: {simple_response.content[:100]}...")
                print(f"    元数据: {json.dumps(simple_response.metadata, ensure_ascii=False)[:80]}")
            except Exception as e:
                simple_time = time.time() - simple_start
                print(f"    错误: {str(e)}")
                simple_response = None
            
            # 测试高级Agent
            print("\n  [高级Agent]")
            advanced_start = time.time()
            try:
                advanced_response = await self.advanced_agent.process(
                    test_case['query'],
                    session_id=session_id
                )
                advanced_time = time.time() - advanced_start
                print(f"    处理时间: {advanced_time:.3f}s")
                print(f"    回答: {advanced_response.content[:100]}...")
                
                # 显示意图识别
                if advanced_response.intent:
                    print(f"    识别意图: {advanced_response.intent.type.value} "
                          f"(置信度: {advanced_response.intent.confidence:.2f})")
                
                # 显示实体
                if advanced_response.entities:
                    entities_str = ", ".join([e.name for e in advanced_response.entities[:3]])
                    print(f"    提取实体: {entities_str}")
                
                # 显示子任务
                if advanced_response.subtasks:
                    print(f"    执行子任务:")
                    for task in advanced_response.subtasks:
                        print(f"      - {task.id}: {task.tool_name or 'N/A'} "
                              f"[{task.status.value}]")
                
                # 显示元数据
                meta_keys = list(advanced_response.metadata.keys())
                print(f"    元数据: {meta_keys}")
                
            except Exception as e:
                advanced_time = time.time() - advanced_start
                print(f"    错误: {str(e)}")
                advanced_response = None
            
            # 记录结果
            self.results.append({
                "test_id": test_case['id'],
                "query": test_case['query'],
                "category": test_case['category'],
                "simple_time": simple_time if simple_response else None,
                "advanced_time": advanced_time if advanced_response else None,
                "simple_success": simple_response is not None,
                "advanced_success": advanced_response is not None,
            })
        
        return self.results
    
    def print_summary(self):
        """打印总结"""
        print("\n" + "=" * 80)
        print("对比测试总结")
        print("=" * 80)
        
        # 统计
        total = len(self.results)
        simple_success = sum(1 for r in self.results if r["simple_success"])
        advanced_success = sum(1 for r in self.results if r["advanced_success"])
        
        simple_times = [r["simple_time"] for r in self.results if r["simple_time"]]
        advanced_times = [r["advanced_time"] for r in self.results if r["advanced_time"]]
        
        print(f"\n总计测试: {total} 个场景")
        print(f"简单Agent成功率: {simple_success}/{total} ({simple_success/total*100:.0f}%)")
        print(f"高级Agent成功率: {advanced_success}/{total} ({advanced_success/total*100:.0f}%)")
        
        if simple_times:
            print(f"\n简单Agent平均处理时间: {sum(simple_times)/len(simple_times):.3f}s")
        if advanced_times:
            print(f"高级Agent平均处理时间: {sum(advanced_times)/len(advanced_times):.3f}s")
        
        # 功能对比
        print("\n" + "─" * 80)
        print("功能对比表")
        print("─" * 80)
        
        features = [
            ("意图识别", "×", "✓"),
            ("实体提取", "×", "✓"),
            ("任务拆解", "×", "✓"),
            ("多轮对话", "部分", "✓"),
            ("异常处理", "基础", "完善"),
            ("工具选择", "手动", "自动"),
            ("代码复杂度", "低", "高"),
            ("适用场景", "简单查询", "复杂任务"),
        ]
        
        print(f"{'功能':<20} {'简单Agent':<15} {'高级Agent':<15}")
        print("-" * 50)
        for feature, simple, advanced in features:
            print(f"{feature:<20} {simple:<15} {advanced:<15}")
        
        # 建议
        print("\n" + "─" * 80)
        print("使用建议")
        print("─" * 80)
        print("""
简单Agent适合：
  - 快速原型开发
  - 功能单一、查询简单的场景
  - 资源受限的环境
  - 需要快速上线的MVP

高级Agent适合：
  - 复杂的问答场景
  - 需要多轮对话的应用
  - 任务类型多样的系统
  - 生产环境，需要高可靠性

演进路径：
  1. 先用简单Agent快速验证核心功能
  2. 根据实际场景识别痛点（如意图识别不准、无法处理复杂查询）
  3. 逐步引入高级Agent的模块
  4. 最终迁移到完整的LangGraph架构
""")
    
    def analyze_query(self, query: str):
        """分析单个查询"""
        print(f"\n{'=' * 80}")
        print(f"查询分析: {query}")
        print(f"{'=' * 80}")
        
        analysis = self.advanced_agent.analyze_query(query)
        print(f"\n快速意图识别: {analysis['quick_intent']}")
        print(f"提取实体: {[e['name'] for e in analysis['entities']]}")
        print(f"知识库: {analysis['knowledge_base'] or '未指定'}")


# ==================== 主函数 ====================

async def main():
    """主函数"""
    demo = AgentComparisonDemo()
    
    # 初始化
    demo.setup()
    
    # 演示查询分析
    print("\n")
    demo.analyze_query("在《产品文档》知识库中查找关于LangChain的RAG实现")
    demo.analyze_query("对比一下LangChain和LlamaIndex的区别")
    
    # 运行对比
    await demo.run_comparison()
    
    # 打印总结
    demo.print_summary()
    
    # 显示高级Agent统计
    print("\n" + "=" * 80)
    print("高级Agent运行统计")
    print("=" * 80)
    stats = demo.advanced_agent.get_stats()
    print(json.dumps(stats, indent=2, default=str))


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                          Agent系统对比演示                                    ║
║                                                                              ║
║  本演示对比两种Agent实现：                                                    ║
║  1. 简单Agent: 基于LangChain Chain，代码简洁                                  ║
║  2. 高级Agent: 基于LangGraph，具备完整功能模块                                ║
║                                                                              ║
║  目的：展示从简单到复杂的演进过程，帮助理解各模块价值                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
    
    # 检查依赖
    try:
        import langgraph
        print("OK LangGraph 已安装")
    except ImportError:
        print("ERROR LangGraph 未安装，请先运行: pip install langgraph")
        exit(1)
    
    try:
        import langchain_core
        print("OK LangChain 已安装")
    except ImportError:
        print("ERROR LangChain 未安装，请先运行: pip install langchain-core")
        exit(1)
    
    print("\n开始演示...\n")
    asyncio.run(main())
