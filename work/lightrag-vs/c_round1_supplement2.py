"""C 轮1 补量 v2：40 query 覆盖 KB17 20 主题，milvus 检索 contexts + qwen3.7-flash 生成 gt + 写测试集 JSON。
reindex 后重跑（text-embedding-v4 索引，contexts 更相关）。
不跳过"不足以回答"——保留所有 gt，让 RAGAS 自己评。
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

# 40 query 覆盖 KB17 20 主题 × 2 变体（基础+应用）
QUERIES = [
    # 基础概念 20
    "什么是向量数据库", "向量数据库的索引算法有哪些",
    "检索增强生成的流程是什么", "RAG系统如何工作",
    "文档切片的策略有哪些", "如何选择文档切片大小",
    "嵌入模型的作用是什么", "嵌入向量的维度怎么选",
    "重排序的目的是什么", "重排序模型有哪些",
    "知识图谱的构建流程", "知识图谱在RAG中的作用",
    "语义缓存如何实现", "语义缓存的命中率如何提升",
    "多路召回的融合方法", "RRF融合的原理是什么",
    "查询改写的常见策略", "查询扩展怎么做",
    "RAG评估的核心指标", "如何评估RAG系统质量",
    # 应用/细节 20
    "向量数据库的应用场景", "向量检索的近似算法",
    "RAG如何减少幻觉", "检索增强生成的优缺点",
    "文档切片递归方法", "chunk_size对检索的影响",
    "嵌入模型训练方法", "嵌入向量的相似度计算",
    "为什么需要重排序", "rerank对检索质量的影响",
    "知识图谱实体抽取", "知识图谱多跳查询",
    "语义缓存的key设计", "语义缓存vs关键词缓存",
    "多路召回的top_k选择", "多路召回的权重分配",
    "查询改写的类型", "查询改写vs查询扩展",
]

samples = []
skipped = 0
for i, q in enumerate(QUERIES):
    # milvus 检索 contexts（reindex 后 text-embedding-v4）
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

    # generate gt（qwen3.7-flash，带重试）
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
        print(f'[{i+1}/{len(QUERIES)}] SKIP {q}: gt empty', flush=True)
        continue

    samples.append({
        'question': q, 'contexts': contexts, 'ground_truth': gt,
        'answer': '', 'status': 'approved',
        'metadata': {'kb_id': 17, 'source': 'supplement', 'tags': ['技术']}
    })
    print(f'[{i+1}/{len(QUERIES)}] OK {q}: gt={gt[:50]}', flush=True)
    time.sleep(0.5)

# 写测试集 JSON
out = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets', 'kb17_supplement.json'))
dataset = {'name': 'kb17_supplement',
           'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'count': len(samples),
           'samples': samples}
json.dump(dataset, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'\n[done] {len(samples)} 实质 gt（跳过 {skipped}），saved {out}', flush=True)
json.dump({'ok': len(samples), 'skipped': skipped, 'total': len(QUERIES)},
    open(os.path.join(os.path.dirname(__file__), 'result_c_supplement.json'), 'w'),
    ensure_ascii=False)
print('saved result_c_supplement.json', flush=True)
