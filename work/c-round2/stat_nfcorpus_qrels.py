"""统计 NFCorpus 100 queries 的 qrels 涉及的 unique docs"""
import os, sys, json, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

THIS = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(THIS, 'qrels', 'nfcorpus_qrels.json'), encoding='utf-8') as f:
    qd = json.load(f)
qrels = qd.get('qid_to_doc_id', {})

# 统计 unique docs
all_docs = set()
high_rel_docs = set()  # score>=2
for qid, rels in qrels.items():
    for cid, sc in rels.items():
        all_docs.add(cid)
        if sc >= 2:
            high_rel_docs.add(cid)

print(f'100 queries qrels:')
print(f'  total pairs: {sum(len(v) for v in qrels.values())}')
print(f'  unique docs (all scores): {len(all_docs)}')
print(f'  unique docs (score>=2): {len(high_rel_docs)}')

# score 分布
score_dist = collections.Counter()
for v in qrels.values():
    for s in v.values():
        score_dist[s] += 1
print(f'  score distribution: {dict(score_dist)}')

# 估算子采样策略
# 全 relevant + 200 随机 non-relevant = ?
import random
with open(os.path.join(THIS, 'corpus', 'nfcorpus_corpus.json'), encoding='utf-8') as f:
    corpus = json.load(f)
all_corpus_ids = {d['id'] for d in corpus}
print(f'\ncorpus total: {len(corpus)}')
non_rel = list(all_corpus_ids - all_docs)
print(f'  non-relevant (not in qrels): {len(non_rel)}')

# 子采样策略 A：relevant + 200 non-relevant = ?
random.seed(20260907)
sample_non_rel_200 = random.sample(non_rel, 200) if len(non_rel) >= 200 else non_rel
print(f'  Strategy A: all rel ({len(all_docs)}) + 200 non-rel = {len(all_docs) + len(sample_non_rel_200)} docs')

# 子采样策略 B：relevant (score>=2) + 100 non-relevant = ?
sample_non_rel_100 = random.sample(non_rel, 100) if len(non_rel) >= 100 else non_rel
print(f'  Strategy B: high-rel ({len(high_rel_docs)}) + 100 non-rel = {len(high_rel_docs) + len(sample_non_rel_100)} docs')

# 子采样策略 C：relevant + 500 non-relevant = ?
sample_non_rel_500 = random.sample(non_rel, 500) if len(non_rel) >= 500 else non_rel
print(f'  Strategy C: all rel ({len(all_docs)}) + 500 non-rel = {len(all_docs) + len(sample_non_rel_500)} docs')

# 全 relevant 都不在 corpus？
missing = all_docs - all_corpus_ids
print(f'\n  relevant docs not in corpus: {len(missing)}')
