"""C 轮1 补量：50 query 覆盖 KB17 主题，milvus 检索 contexts + LLM 生成 gt + 写测试集 JSON。
跳过"不足以回答"的，留实质 gt（spec 三.轮1.3 LLM 补量）。"""
import sys, os, json, requests, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
from evaluation.gt_generator import generate_ground_truth

B = 'http://localhost:8003'
TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

QUERIES = [
    # bench 20
    "向量数据库的核心原理", "如何优化检索延迟", "文档切片策略对比", "嵌入模型的维度选择", "重排序的作用",
    "多路召回如何融合", "查询改写的常见方法", "评估RAG系统的指标", "倒排索引构建过程", "语义缓存命中率",
    "一致性哈希的应用", "熔断降级的实现", "消息队列的可靠性", "分布式索引的分片", "知识图谱多跳查询",
    "分词算法的对比", "流式计算窗口", "数据脱敏技术", "文本压缩算法", "联邦学习隐私",
    # 变体 30（基于 KB17 docs 主题，确保 contexts 覆盖）
    "什么是向量数据库", "向量数据库的索引算法", "向量数据库的应用场景",
    "BM25的打分公式", "BM25与向量检索的区别",
    "嵌入模型有哪些", "嵌入模型的训练方法",
    "重排序模型有哪些", "为什么需要重排序",
    "多路召回的RRF融合", "查询扩展的策略",
    "RAG的faithfulness指标含义", "context_recall指标含义",
    "倒排索引与向量索引的区别", "语义缓存的实现方法",
    "一致性哈希的原理", "熔断降级的策略",
    "消息队列的语义保证", "分布式索引的副本同步",
    "知识图谱的实体抽取", "分词算法的优缺点",
    "流式计算的状态管理", "数据脱敏的方法",
    "文本压缩的算法对比", "联邦学习的差分隐私",
    "RAG的架构", "检索增强生成的流程",
    "向量检索的近似算法", "文档切片的递归方法", "嵌入模型的蒸馏",
]

samples = []
skipped = 0
for i, q in enumerate(QUERIES):
    # milvus 检索 contexts
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

    # generate gt（带重试，gpt-4o 偶发 rate limit）
    gt = None
    for attempt in range(2):
        try:
            gt = generate_ground_truth(q, contexts)
            break
        except Exception as e:
            print(f'[{i+1}] gt err {str(e)[:50]}', flush=True)
            time.sleep(3)

    if not gt or '不足以回答' in gt:
        skipped += 1
        print(f'[{i+1}/{len(QUERIES)}] SKIP {q}: gt 不足以回答', flush=True)
        continue

    samples.append({
        'question': q, 'contexts': contexts, 'ground_truth': gt,
        'answer': '', 'status': 'approved',
        'metadata': {'kb_id': 17, 'source': 'supplement', 'tags': ['技术']}
    })
    print(f'[{i+1}/{len(QUERIES)}] OK {q}: gt={gt[:50]}', flush=True)
    time.sleep(1)

# 写测试集 JSON
out = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets', 'kb17_supplement.json'))
dataset = {'name': 'kb17_supplement', 'samples': samples,
           'created_at': time.strftime('%Y-%m-%dT%H:%M:%S')}
json.dump(dataset, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'\n[done] {len(samples)} 实质 gt（跳过 {skipped}），saved {out}', flush=True)
json.dump({'ok': len(samples), 'skipped': skipped, 'total': len(QUERIES)},
    open(os.path.join(os.path.dirname(__file__), 'result_c_supplement.json'), 'w'),
    ensure_ascii=False)
print('saved result_c_supplement.json', flush=True)
