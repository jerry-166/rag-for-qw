"""C 轮1 补量 v3：query 匹配 KB17 docs 实际内容（工程实践描述）。
KB17 docs 是模板化工程文档，每个主题内容是"X 的内部机制/工程实践/监控指标"。
query 问这些方面，contexts 才能生成实质 gt。
"""
import sys, os, json, requests, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
from evaluation.gt_generator import generate_ground_truth

B = 'http://localhost:8003'
TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

# 35 query 匹配 KB17 docs 内容（每个主题的内部机制/工程实践/监控指标/常见问题）
QUERIES = [
    # 向量数据库
    "向量数据库的内部机制是什么", "向量数据库的工程实践要点", "向量数据库的监控指标有哪些",
    # 检索增强生成
    "检索增强生成的内部机制", "RAG系统的工程实践", "检索增强生成的监控指标",
    # 文档切片
    "文档切片策略的内部机制", "文档切片的工程实践",
    # 嵌入模型
    "嵌入模型的内部机制", "嵌入模型的工程实践要点",
    # 重排序
    "重排序的内部机制是什么", "重排序的工程实践",
    # 知识图谱
    "知识图谱的内部机制", "知识图谱的工程实践要点",
    # 语义缓存
    "语义缓存的内部机制", "语义缓存的工程实践",
    # 多路召回
    "多路召回的内部机制", "多路召回的工程实践",
    # 查询改写
    "查询改写的内部机制", "查询改写的工程实践",
    # 评估基准
    "评估基准的内部机制", "评估基准的工程实践",
    # 分布式索引
    "分布式索引的内部机制", "分布式索引的工程实践",
    # 倒排索引
    "倒排索引的内部机制", "倒排索引的工程实践",
    # 分词算法
    "分词算法的内部机制", "分词算法的工程实践",
    # 文本压缩
    "文本压缩的内部机制", "文本压缩的工程实践",
    # 联邦学习
    "联邦学习的内部机制", "联邦学习的工程实践",
    # 熔断降级
    "熔断降级的内部机制", "熔断降级的工程实践",
]

samples = []
skipped = 0
for i, q in enumerate(QUERIES):
    try:
        r = requests.post(B + '/api/milvus/query',
            json={'retrieval_mode': 'native', 'use_rerank': False,
                  'limit': 10, 'knowledge_base_id': 17, 'query': q},
            headers=H, timeout=30)
        results = r.json().get('results', [])
        contexts = [c.get('content', c.get('chunk_text', ''))
                    for c in results
                    if c.get('content', c.get('chunk_text', ''))]
    except Exception as e:
        print(f'[{i+1}] {q}: milvus err {str(e)[:50]}', flush=True)
        continue
    if not contexts:
        print(f'[{i+1}] {q}: no contexts', flush=True)
        continue

    gt = None
    for attempt in range(2):
        try:
            gt = generate_ground_truth(q, contexts)
            break
        except Exception as e:
            print(f'[{i+1}] gt err {str(e)[:50]}', flush=True)
            time.sleep(3)

    if not gt:
        skipped += 1
        continue

    samples.append({
        'question': q, 'contexts': contexts, 'ground_truth': gt,
        'answer': '', 'status': 'approved',
        'metadata': {'kb_id': 17, 'source': 'supplement', 'tags': ['技术']}
    })
    is_insuf = '不足以回答' in gt
    print(f'[{i+1}/{len(QUERIES)}] {"INSUF" if is_insuf else "OK"} {q}: gt={gt[:50]}', flush=True)
    time.sleep(0.5)

out = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets', 'kb17_supplement.json'))
dataset = {'name': 'kb17_supplement',
           'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'count': len(samples),
           'samples': samples}
json.dump(dataset, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
substantive = sum(1 for s in samples if '不足以回答' not in s['ground_truth'])
print(f'\n[done] {len(samples)} gt（实质 {substantive}，不足以回答 {len(samples)-substantive}，跳过 {skipped}），saved {out}', flush=True)
