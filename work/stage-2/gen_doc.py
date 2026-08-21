import random
random.seed(42)

topics = [
    ("Milvus 向量数据库", "Milvus 是开源向量数据库，支持十亿级向量的近似最近邻搜索，广泛用于推荐、图像检索与 RAG。它有集合、分区、段三级数据组织结构，支持标量过滤与多向量混合查询。"),
    ("BM25 关键词检索", "BM25 是基于词频与逆文档频率的经典排序函数，对查询词在文档中的频率与文档长度联合打分。它无需训练、可解释、能精确匹配术语，与向量检索互补。"),
    ("RRF 融合排序", "Reciprocal Rank Fusion 将多路召回结果按排名倒数求和融合，常数 k 常取 60。RRF 无需分数归一化，对不同打分体系稳健。"),
    ("重排序模型", "Reranker 在召回后对候选精排。cross-encoder 把查询与文档拼接编码，捕捉细粒度交互，精度高但成本大，只用于 top-k 候选。"),
    ("知识库权限模型", "系统采用用户-知识库-权限三元组。KB 可私有或共享，通过 user_kb_permission 授权。私有 KB 的 FAQ 蒸馏阈值为 2，共享 KB 为 3。"),
    ("FAQ 记忆闭环", "FAQ 系统把高频问答沉淀为可复用知识。命中已有 FAQ 直接返回缓存答案；相似问题达到阈值后 LLM 蒸馏规范化答案并升格为 active。"),
    ("实体图谱增强", "实体增强器从 chunk 抽取命名实体与关系，写入 entity 与 entity_relation 表，并同步实体向量到 Milvus 的 entity_vectors 集合。"),
    ("文档切块策略", "支持 auto 自动探测、markdown 按标题切割、recursive 递归切割三种策略，优先级为请求级 > KB 级 > 全局级。"),
    ("审计中心", "审计中心记录关键操作事件：文档处理各阶段、FAQ 生命周期、KB 分享克隆、PR 审核，写入 audit_log 表。"),
    ("LangGraph 工作流", "claw agent 基于 LangGraph 构建对话工作流，节点含意图识别、检索、生成、反馈，SSE 逐步透出中间事件。"),
    ("子问题增强", "sub_question 增强器为每个 chunk 生成三到五个变体问题并写入向量库，检索时同时命中问题向量与原文向量。"),
    ("摘要增强", "summary 增强器为 chunk 生成一句话摘要，摘要向量参与检索，在查询语义与原文差异大时提供额外召回通道。"),
]

lines = ["# RAG 系统综合测试文档 v3\n", "覆盖 RAG 核心组件的端到端流水线验证文档，共 48 个知识条目。\n"]
n = 0
for rep in range(4):
    for t, body in topics:
        n += 1
        lines.append(f"\n## 条目{n}：{t}（第{rep+1}部分）\n")
        lines.append(
            f"{body}在第{rep+1}部分中，我们关注{t}的工程落地细节。"
            f"典型做法是先以默认配置建立基线，再用固定评测集对比迭代。"
            f"监控指标包括 P95 延迟、吞吐量、错误率与质量评分，任何变更都应通过回归测试。"
            f"与相邻组件的组合调优往往能带来叠加收益，例如召回阶段扩宽候选、精排阶段收紧阈值。"
            f"运维上建议保留灰度开关，出现回退可快速切回；文档记录与告警配置同样重要。\n"
        )
doc = "\n".join(lines)
open("work/stage-2/e2e_doc.md", "w", encoding="utf-8").write(doc)
print("chars:", len(doc), "sections:", n)
