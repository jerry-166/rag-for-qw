"""
意图识别模块

使用LLM进行多层级意图分类，支持：
- 主要意图识别
- 子意图细分
- 置信度评估
- 多标签分类
"""
import json
import asyncio
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

import sys
import os
# 获取backend目录的绝对路径
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, backend_dir)
from config import settings, init_logger
from agent.base import Intent, IntentType

logger = init_logger(__name__)


class IntentClassificationOutput(BaseModel):
    """意图识别输出结构"""
    primary_intent: str = Field(..., description="主要意图类型")
    confidence: float = Field(..., ge=0, le=1, description="置信度")
    sub_intents: List[str] = Field(default=[], description="子意图列表")
    reasoning: str = Field(..., description="推理过程")
    metadata: Dict[str, Any] = Field(default={}, description="额外元数据")


class IntentClassifier:
    """
    意图分类器
    
    基于LLM的意图识别，支持复杂查询的多意图理解
    """
    
    # 意图定义
    INTENT_DEFINITIONS = {
        IntentType.RETRIEVAL: {
            "description": "知识检索类查询，用户想查找特定信息",
            "examples": [
                "什么是机器学习？",
                "查找关于Python的文档",
                "RAG技术的原理是什么？",
            ],
            "keywords": ["什么是", "查找", "搜索", "关于", "原理", "介绍"],
        },
        IntentType.SUMMARIZATION: {
            "description": "内容摘要类查询，用户需要总结性回答",
            "examples": [
                "总结一下这份文档的主要内容",
                "给我这份文件的摘要",
                "简要说明一下",
            ],
            "keywords": ["总结", "摘要", "概括", "简要", "概述"],
        },
        IntentType.COMPARISON: {
            "description": "对比分析类查询，用户需要比较多个事物",
            "examples": [
                "对比一下RAG和Fine-tuning的区别",
                "Python和JavaScript有什么不同？",
                "哪个更好，A还是B？",
            ],
            "keywords": ["对比", "比较", "区别", "不同", "vs", "哪个", "优劣"],
        },
        IntentType.ANALYSIS: {
            "description": "深度分析类查询，需要多步骤推理",
            "examples": [
                "分析这个方案的可行性",
                "为什么会发生这种情况？",
                "帮我分析一下这个问题的原因",
            ],
            "keywords": ["分析", "为什么", "原因", "可行性", "评估"],
        },
        IntentType.CLARIFICATION: {
            "description": "澄清类查询，用户需要进一步说明",
            "examples": [
                "我不太明白，能再解释一下吗？",
                "你说的XXX是什么意思？",
                "能举个例子吗？",
            ],
            "keywords": ["不明白", "解释", "什么意思", "例子", "详细"],
        },
        IntentType.GREETING: {
            "description": "问候类查询",
            "examples": [
                "你好",
                "Hello",
                "在吗？",
            ],
            "keywords": ["你好", "hello", "hi", "在吗", "您好"],
        },
        IntentType.UNKNOWN: {
            "description": "无法识别的意图",
            "examples": [],
            "keywords": [],
        },
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.llm = ChatOpenAI(
            model=self.config.get("model", settings.DEFAULT_MODEL),
            base_url=settings.LITELLM_BASE_URL,
            api_key=settings.LITELLM_API_KEY,
            temperature=0.1,  # 低温度确保稳定的分类结果
        )
        self._build_chain()
        logger.info("[intent_classifier] 意图分类器初始化完成")
    
    def _build_chain(self):
        """构建意图识别的静态提示部分（不含变量）"""
        
        # 构建意图定义描述
        intent_descriptions = []
        for intent_type, info in self.INTENT_DEFINITIONS.items():
            examples_str = "\n  - ".join([""] + info["examples"][:2])
            intent_descriptions.append(
                f"{intent_type.value}: {info['description']}\n"
                f"  示例:{examples_str}"
            )
        
        # 存储静态的系统提示部分（不包含任何大括号变量）
        self._static_prompt_parts = {
            "intent_descriptions": chr(10).join(intent_descriptions),
            "json_example": '''{
                "primary_intent": "意图类型值",
                "confidence": 0.0-1.0之间的置信度,
                "sub_intents": ["子意图1", "子意图2"],
                "reasoning": "你的推理过程",
                "metadata": {}
            }''',
        }
    
    async def classify(self, query: str, chat_history: Optional[List[Dict]] = None) -> Intent:
        """
        分类用户意图
        
        Args:
            query: 用户查询
            chat_history: 对话历史
            
        Returns:
            Intent: 识别出的意图
        """
        try:
            # 格式化对话历史
            history_str = self._format_history(chat_history)
            
            logger.info(f"调用LLM进行意图识别...")
            logger.info(f"查询: {query}")
            
            # 手动构建完整提示（不使用任何模板系统，避免大括号解析问题）
            full_prompt = f"""你是一个意图分类专家。请分析用户的查询，识别其主要意图。

可选的意图类型：
{self._static_prompt_parts['intent_descriptions']}

请按以下JSON格式输出：
{self._static_prompt_parts['json_example']}

注意：
- primary_intent必须是上述列出的意图类型值之一
- confidence表示你对分类的确定程度
- sub_intents用于表示复合意图中的次要意图

对话历史：{history_str}

用户查询：{query}

请输出JSON格式的意图分析结果："""
            
            # 直接调用LLM，绕过模板系统
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=full_prompt)])
            
            # print(f"LLM响应: {response.content[:100]}...")
            
            # 解析JSON输出
            content = response.content
            # 提取JSON部分（处理可能的markdown代码块）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            result = json.loads(content.strip())
            print(f"解析结果: {result}")
            
            # 映射到Intent对象
            primary_intent_type = self._parse_intent_type(result.get("primary_intent", "unknown"))
            
            # 解析子意图
            sub_intents = []
            for sub_intent_str in result.get("sub_intents", []):
                sub_intent_type = self._parse_intent_type(sub_intent_str)
                sub_intents.append(Intent(
                    type=sub_intent_type,
                    confidence=result.get("confidence", 0.5) * 0.8,  # 子意图置信度降低
                ))

            logger.info(f"[intent_classifier] 识别出的主要意图: {primary_intent_type.value}")
            logger.info(f"[intent_classifier] 子意图: {[intent.type.value for intent in sub_intents]}")
            return Intent(
                type=primary_intent_type,
                confidence=result.get("confidence", 0.5),
                sub_intents=sub_intents,
                metadata={
                    "reasoning": result.get("reasoning", ""),
                    "raw_output": result,
                }
            )
            
        except Exception as e:
            # 出错时返回UNKNOWN意图
            # 尝试使用规则分类作为备选
            fallback_intent = self.quick_classify(query)
            logger.error(f"[intent_classifier] LLM调用失败: {str(e)}, 使用规则分类作为备选: {fallback_intent.value}")
            return Intent(
                type=fallback_intent,
                confidence=0.7,  # 规则分类的置信度
                metadata={"error": str(e), "fallback": True}
            )
    
    def _format_history(self, chat_history: Optional[List[Dict]]) -> str:
        """格式化对话历史"""
        if not chat_history:
            return "无"
        
        formatted = []
        for msg in chat_history[-3:]:  # 只保留最近3轮
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            formatted.append(f"{role}: {content[:100]}...")
        
        return "\n".join(formatted)
    
    def _parse_intent_type(self, intent_str: str) -> IntentType:
        """解析意图字符串为枚举值"""
        intent_str = intent_str.lower().strip()
        
        # 直接匹配
        for intent_type in IntentType:
            if intent_type.value == intent_str:
                return intent_type
        
        # 关键词匹配
        intent_keywords = {
            IntentType.RETRIEVAL: ["retrieval", "query", "search", "查找", "检索"],
            IntentType.SUMMARIZATION: ["summarization", "summary", "总结", "摘要"],
            IntentType.COMPARISON: ["comparison", "compare", "对比", "比较"],
            IntentType.ANALYSIS: ["analysis", "analyze", "分析"],
            IntentType.CLARIFICATION: ["clarification", "clarify", "澄清", "解释"],
            IntentType.GREETING: ["greeting", "hello", "你好", "问候"],
        }
        
        for intent_type, keywords in intent_keywords.items():
            if any(kw in intent_str for kw in keywords):
                return intent_type
        
        return IntentType.UNKNOWN
    
    def quick_classify(self, query: str) -> IntentType:
        """
        快速意图分类（基于规则，无需LLM）
        
        Args:
            query: 用户查询
            
        Returns:
            IntentType: 意图类型
        """
        query_lower = query.lower()
        
        # 检查每个意图的关键词
        scores = {}
        for intent_type, info in self.INTENT_DEFINITIONS.items():
            score = sum(1 for kw in info["keywords"] if kw in query_lower)
            if score > 0:
                scores[intent_type] = score
        
        logger.info(f"[intent_classifier] 规则分类结果: {scores}")
        
        # 返回得分最高的意图
        if scores:
            return max(scores.items(), key=lambda x: x[1])[0]
        
        return IntentType.UNKNOWN


# 测试
if __name__ == "__main__":
    async def test():
        classifier = IntentClassifier()
        
        test_queries = [
            "什么是机器学习？",
            "对比一下Python和Java的区别",
            "请总结一下这份文档",
            "你好",
            "我不太理解这个概念，能再解释一下吗？",
        ]
        
        for query in test_queries:
            intent = await classifier.classify(query)
            quick = classifier.quick_classify(query)
            print(f"\n查询: {query}")
            print(f"  LLM识别: {intent.type.value} (置信度: {intent.confidence:.2f})")
            print(f"  快速识别: {quick.value}")
            print(f"  推理: {intent.metadata.get('reasoning', 'N/A')[:50]}...")
    
    asyncio.run(test())
