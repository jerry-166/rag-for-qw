"""C 轮1 补量 v3 续跑：跳过已有 question，补到 ≥30。"""
import sys, os, json, requests, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
from evaluation.gt_generator import generate_ground_truth

B = 'http://localhost:8003'
TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets', 'kb17_supplement.json'))
existing = json.load(open(OUT, encoding='utf-8'))
samples = existing.get('samples', [])
existing_qs = {s['question'] for s in samples}
print(f'existing: {len(samples)} samples, {len(existing_qs)} unique questions', flush=True)

QUERIES = [
    "向量数据库的内部机制是什么", "向量数据库的工程实践要点", "向量数据库的监控指标有哪些",
    "检索增强生成的内部机制", "RAG系统的工程实践", "检索增强生成的监控指标",
    "文档切片策略的内部机制", "文档切片的工程实践",
    "嵌入模型的内部机制", "嵌入模型的工程实践要点",
    "重排序的内部机制是什么", "重排序的工程实践",
    "知识图谱的内部机制", "知识图谱的工程实践要点",
    "语义缓存的内部机制", "语义缓存的工程实践",
    "多路召回的内部机制", "多路召回的工程实践",
    "查询改写的内部机制", "查询改写的工程实践",
    "评估基准的内部机制", "评估基准的工程实践",
    "分布式索引的内部机制", "分布式索引的工程实践",
    "倒排索引的内部机制", "倒排索引的工程实践",
    "分词算法的内部机制", "分词算法的工程实践",
    "文本压缩的内部机制", "文本压缩的工程实践",
    "联邦学习的内部机制", "联邦学习的工程实践",
    "熔断降级的内部机制", "熔断降级的工程实践",
    # 补充变体确保 ≥30
    "向量数据库的常见问题", "重排序的监控指标", "语义缓存的常见问题",
    "多路召回的监控指标", "分布式索引的监控指标",
]

new_count = 0
for i, q in enumerate(QUERIES):
    if q in existing_qs:
        continue
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
        print(f'[{q}] milvus err {str(e)[:50]}', flush=True)
        continue
    if not contexts:
        print(f'[{q}] no contexts', flush=True)
        continue

    gt = None
    for attempt in range(2):
        try:
            gt = generate_ground_truth(q, contexts)
            break
        except Exception as e:
            print(f'[{q}] gt err {str(e)[:50]}', flush=True)
            time.sleep(3)

    if not gt:
        continue

    samples.append({
        'question': q, 'contexts': contexts, 'ground_truth': gt,
        'answer': '', 'status': 'approved',
        'metadata': {'kb_id': 17, 'source': 'supplement', 'tags': ['技术']}
    })
    existing_qs.add(q)
    new_count += 1
    is_insuf = '不足以回答' in gt
    print(f'[+{new_count}] {"INSUF" if is_insuf else "OK"} {q}: gt={gt[:40]}', flush=True)
    time.sleep(0.5)
    # 够 30 条就停
    if len(samples) >= 32:
        break

dataset = {'name': 'kb17_supplement',
           'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'count': len(samples),
           'samples': samples}
json.dump(dataset, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
substantive = sum(1 for s in samples if '不足以回答' not in s['ground_truth'])
print(f'\n[done] total {len(samples)}（new {new_count}，实质 {substantive}，不足以回答 {len(samples)-substantive}）', flush=True)
