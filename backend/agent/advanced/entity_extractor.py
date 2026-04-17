"""
实体提取模块

从用户查询中提取关键实体信息，支持：
- 命名实体识别（NER）
- 领域特定实体提取
- 实体关系抽取
- 多语言支持
"""
import json
import re
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

import sys
import os
# 添加backend/agent目录到搜索路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import settings, init_logger
# 直接导入base模块
from base import Entity

logger = init_logger(__name__)



class EntityExtractionOutput(BaseModel):
    """实体提取输出结构"""
    entities: List[Dict[str, Any]] = Field(
        ..., 
        description="提取的实体列表，每个实体包含name, type, value, confidence"
    )
    relations: List[Dict[str, Any]] = Field(
        default=[],
        description="实体间的关系列表"
    )


class EntityExtractor:
    """
    实体提取器
    
    结合规则匹配和LLM提取，支持多种实体类型
    """
    
    # 实体类型定义
    ENTITY_TYPES = {
        "DOCUMENT": {
            "description": "文档、文件、资料",
            "patterns": [
                r"《([^》]+)》",  # 《书名》
                r'"([^"]+)"',     # "文件名"
                r"'([^']+)'",     # '文件名'
                r"文档[：:]\s*(\S+)",
                r"文件[：:]\s*(\S+)",
            ],
        },
        "TECHNOLOGY": {
            "description": "技术、框架、工具",
            "keywords": [
                "Python", "JavaScript", "Java", "Go", "Rust", "C++",
                "RAG", "LLM", "GPT", "BERT", "Transformer",
                "Docker", "Kubernetes", "AWS", "Azure",
                "React", "Vue", "Angular", "Django", "Flask",
                "MySQL", "PostgreSQL", "MongoDB", "Redis",
                "LangChain", "LangGraph", "OpenAI", "Claude",
            ],
        },
        "CONCEPT": {
            "description": "概念、术语、理论",
            "keywords": [
                "向量数据库", "知识图谱", "机器学习", "深度学习",
                "神经网络", "自然语言处理", "NLP",
                "检索增强生成", "微调", "Fine-tuning",
                "注意力机制", "Transformer", "Embedding",
            ],
        },
        "PERSON": {
            "description": "人名",
            "patterns": [
                r"[\u4e00-\u9fa5]{2,4}(?=先生|女士|博士|教授|老师)",
            ],
        },
        "TIME": {
            "description": "时间、日期",
            "patterns": [
                r"\d{4}年\d{1,2}月\d{1,2}日",
                r"\d{4}-\d{2}-\d{2}",
                r"\d{1,2}月\d{1,2}日",
                r"(昨天|今天|明天|上周|下周|上个月|下个月)",
            ],
        },
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.use_llm = self.config.get("use_llm", True)
        
        if self.use_llm:
            self.llm = ChatOpenAI(
                model=self.config.get("model", settings.DEFAULT_MODEL),
                base_url=settings.LITELLM_BASE_URL,
                api_key=settings.LITELLM_API_KEY,
                temperature=0.1,
            )
            self._build_chain()
        logger.info("[EntityExtractor] 实体提取器初始化完成")
    
    def _build_chain(self):
        """构建LLM提取的静态提示部分（不含变量）"""
        
        # 构建实体类型描述
        entity_types_desc = "\n".join([
            f"- {k}: {v['description']}"
            for k, v in self.ENTITY_TYPES.items()
        ])
        
        # 存储静态的系统提示部分（不包含任何大括号变量）
        self._static_prompt_parts = {
            "entity_types_desc": entity_types_desc,
            "json_example": '''{
                "entities": [
                    {
                        "name": "实体名称",
                        "type": "实体类型",
                        "value": "实体值（与name可能不同，如标准化后的值）",
                        "confidence": 0.95
                    }
                ],
                "relations": [
                    {
                        "source": "实体1名称",
                        "target": "实体2名称", 
                        "relation": "关系类型"
                    }
                ]
            }''',
        }
    
    async def extract(self, query: str, context: Optional[Dict] = None) -> List[Entity]:
        """
        提取实体
        
        Args:
            query: 用户查询
            context: 上下文信息
            
        Returns:
            List[Entity]: 提取的实体列表
        """
        entities = []
        
        # 1. 规则提取
        logger.info(f"[EntityExtractor] 开始规则提取实体...")
        rule_entities = self._extract_by_rules(query)
        entities.extend(rule_entities)
        logger.info(f"[EntityExtractor] 规则提取实体: {[e.name for e in rule_entities]}")
        
        # 2. LLM提取（如果启用）
        if self.use_llm:
            try:
                logger.info(f"[EntityExtractor] 开始LLM提取实体...")
                llm_entities = await self._extract_by_llm(query)
                logger.info(f"[EntityExtractor] LLM提取实体: {[e.name for e in llm_entities]}")
                # 合并去重
                entities = self._merge_entities(entities, llm_entities)
                logger.info(f"[EntityExtractor] 合并后实体: {[e.name for e in entities]}")
            except Exception as e:
                # LLM提取失败时，只使用规则提取结果
                logger.error(f"[EntityExtractor] LLM实体提取失败: {e}")
                import traceback
                traceback.print_exc()
        
        return entities
    
    def _extract_by_rules(self, query: str) -> List[Entity]:
        """基于规则提取实体"""
        entities = []
        
        for entity_type, config in self.ENTITY_TYPES.items():
            # 模式匹配
            if "patterns" in config:
                for pattern in config["patterns"]:
                    matches = re.finditer(pattern, query)
                    for match in matches:
                        value = match.group(1) if match.groups() else match.group(0)
                        entities.append(Entity(
                            name=value,
                            type=entity_type,
                            value=value,
                            confidence=0.8,
                            start_pos=match.start(),
                            end_pos=match.end(),
                        ))
            
            # 关键词匹配
            if "keywords" in config:
                for keyword in config["keywords"]:
                    # 不区分大小写的匹配
                    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                    for match in pattern.finditer(query):
                        entities.append(Entity(
                            name=match.group(0),
                            type=entity_type,
                            value=keyword,  # 使用标准关键词作为值
                            confidence=0.9,
                            start_pos=match.start(),
                            end_pos=match.end(),
                        ))
        
        return entities
    
    async def _extract_by_llm(self, query: str) -> List[Entity]:
        """使用LLM提取实体"""
        # 手动构建完整提示（不使用任何模板系统，避免大括号解析问题）
        full_prompt = f"""你是一个实体提取专家。请从用户查询中提取所有相关实体。

支持的实体类型：
{self._static_prompt_parts['entity_types_desc']}

请按以下JSON格式输出：
{self._static_prompt_parts['json_example']}

注意：
- 只提取明确的实体，不要推测
- confidence表示提取的确定程度(0-1)
- 如果查询中没有明显实体，返回空列表

请提取以下查询中的实体：

{query}
"""
        
        # 直接调用LLM，绕过模板系统
        from langchain_core.messages import HumanMessage
        response = await self.llm.ainvoke([HumanMessage(content=full_prompt)])
        
        # 解析JSON
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        result = json.loads(content.strip())
        
        entities = []
        for entity_data in result.get("entities", []):
            entities.append(Entity(
                name=entity_data.get("name", ""),
                type=entity_data.get("type", "UNKNOWN"),
                value=entity_data.get("value", entity_data.get("name", "")),
                confidence=entity_data.get("confidence", 0.5),
            ))
        
        return entities
    
    def _merge_entities(self, rule_entities: List[Entity], llm_entities: List[Entity]) -> List[Entity]:
        """合并规则提取和LLM提取的实体，去重"""
        merged = list(rule_entities)
        
        for llm_entity in llm_entities:
            # 检查是否已存在相似实体
            is_duplicate = False
            for existing in merged:
                # 名称相似度检查
                if self._similarity(llm_entity.name, existing.name) > 0.8:
                    is_duplicate = True
                    # 保留置信度更高的
                    if llm_entity.confidence > existing.confidence:
                        existing.confidence = llm_entity.confidence
                        existing.value = llm_entity.value
                    break
            
            if not is_duplicate:
                merged.append(llm_entity)
        
        return merged
    
    def _similarity(self, s1: str, s2: str) -> float:
        """计算字符串相似度（简单的包含关系检查）"""
        s1, s2 = s1.lower(), s2.lower()
        if s1 == s2:
            return 1.0
        if s1 in s2 or s2 in s1:
            return 0.9
        # 可以扩展为使用编辑距离等算法
        return 0.0


# 测试
if __name__ == "__main__":
    async def test():
        # 启用LLM，测试使用模型进行实体提取
        extractor = EntityExtractor(config={"use_llm": True})
        
        test_queries = [
            "在《技术文档》知识库中查找关于Python的RAG实现",
            "对比一下LangChain和LlamaIndex的区别",
            "什么是Transformer架构？",
            "请总结昨天的会议纪要",
        ]
        
        for query in test_queries:
            print(f"\n查询: {query}")
            entities = await extractor.extract(query)
            for entity in entities:
                print(f"  [{entity.type}] {entity.name} = {entity.value} (置信度: {entity.confidence:.2f})")
    
    import asyncio
    asyncio.run(test())
