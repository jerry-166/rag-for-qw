"""C 轮2 数据准备：构建 CRUD-RAG 300 + NFCorpus 100 的 testsets/corpus/qrels

输出：
  testsets/crud_rag_300.json     — EvaluationDataset 格式（question/gt）
  testsets/nfcorpus_100.json     — EvaluationDataset 格式（question, gt 待 LLM 生成）
  corpus/crud_corpus_300.json    — [{id, text, title}] 供两系统导入
  corpus/nfcorpus_corpus.json    — [{id, text, title}] 3633 docs
  qrels/crud_qrels.json          — {qid: {doc_id: 1}}  (CRUD: query i → doc i 单 relevant)
  qrels/nfcorpus_qrels.json      — {qid: {corpus_id: score}}  (BEIR 3-level)

控制变量：
  - 切块 1000+overlap 100 由 .env 配置（CHUNK_SIZE=1000, CHUNK_OVERLAP=100 已就位）
  - embedding dim 1536 由 .env 配置（EMBEDDING_DIM=1536 已就位）
  - 这里不切块，把完整 doc text 给两系统让其各自按 1000 切块
"""
import os, sys, json, random, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

THIS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(THIS, '..', '..'))
TESTSET_DIR = os.path.join(ROOT, 'backend', 'evaluation', 'testsets')
CORPUS_DIR = os.path.join(THIS, 'corpus')
QRELS_DIR = os.path.join(THIS, 'qrels')
for d in (TESTSET_DIR, CORPUS_DIR, QRELS_DIR):
    os.makedirs(d, exist_ok=True)

SEED = 20260907
random.seed(SEED)

# ============ 1. CRUD-RAG 300 ============
print('=== 1. CRUD-RAG 300 ===')
crud_path = r'd:\workspace\CRUD_RAG\data\crud_split\split_merged.json'
with open(crud_path, encoding='utf-8') as f:
    crud = json.load(f)

qa1 = crud.get('questanswer_1doc', [])
print(f'questanswer_1doc total: {len(qa1)}')

# 抽 300 条，固定 seed 保证可复现
indices = list(range(len(qa1)))
random.shuffle(indices)
sel_idx = sorted(indices[:300])
sel = [qa1[i] for i in sel_idx]

crud_corpus = []      # [{id, text, title}]
crud_samples = []     # EvaluationDataset samples
crud_qrels = {}       # {qid: {doc_id: 1}}

for i, s in enumerate(sel):
    doc_id = f'crud_{i:03d}'      # 稳定 doc_id
    qid = f'crud_q{i:03d}'
    text = s.get('news1', '').strip()
    title = s.get('event', '')[:60] or f'CRUD doc {i}'
    if not text:
        continue
    crud_corpus.append({
        'id': doc_id,
        'text': text,
        'title': title,
        'metadata': {'source': 'crud-rag', 'orig_id': s.get('ID', ''), 'kb_id': 18}
    })
    crud_samples.append({
        'question': s.get('questions', '').strip(),
        'answer': '',         # 待 fill 阶段填充
        'contexts': [],       # 待 fill 阶段填充
        'ground_truth': s.get('answers', '').strip(),
        'status': 'approved',
        'metadata': {
            'kb_id': 18,
            'source': 'crud-rag',
            'doc_id': doc_id,    # 反查 qrel 用
            'qid': qid,
            'tags': ['中文', 'CRUD', 'questanswer_1doc'],
        }
    })
    # qrel: 1 relevant doc per query（CRUD 的 query 就是基于该 news1 生成的）
    crud_qrels[qid] = {doc_id: 1}

# 写 testset
crud_testset = {
    'name': 'crud_rag_300',
    'created_at': __import__('time').strftime('%Y-%m-%dT%H:%M:%S'),
    'count': len(crud_samples),
    'samples': crud_samples,
}
crud_testset_path = os.path.join(TESTSET_DIR, 'crud_rag_300.json')
with open(crud_testset_path, 'w', encoding='utf-8') as f:
    json.dump(crud_testset, f, ensure_ascii=False, indent=2)
print(f'  testset: {crud_testset_path} ({len(crud_samples)} samples)')

# 写 corpus
crud_corpus_path = os.path.join(CORPUS_DIR, 'crud_corpus_300.json')
with open(crud_corpus_path, 'w', encoding='utf-8') as f:
    json.dump(crud_corpus, f, ensure_ascii=False, indent=2)
print(f'  corpus: {crud_corpus_path} ({len(crud_corpus)} docs)')

# 写 qrels
crud_qrels_path = os.path.join(QRELS_DIR, 'crud_qrels.json')
with open(crud_qrels_path, 'w', encoding='utf-8') as f:
    json.dump({'qid_to_doc_id': crud_qrels, 'note': 'CRUD-RAG: 1 relevant doc per query'}, f, ensure_ascii=False, indent=2)
print(f'  qrels: {crud_qrels_path} ({len(crud_qrels)} queries)')

# ============ 2. NFCorpus 100 ============
print('\n=== 2. NFCorpus 100 ===')
import pandas as pd

NF_DIR = os.path.join(THIS, 'nfcorpus')
corpus_df = pd.read_parquet(os.path.join(NF_DIR, 'corpus.parquet'))
queries_df = pd.read_parquet(os.path.join(NF_DIR, 'queries.parquet'))

# 全量 corpus（3633 docs）
nf_corpus = []
for _, r in corpus_df.iterrows():
    nf_corpus.append({
        'id': str(r['_id']),
        'text': str(r['text']) if r['text'] is not None else '',
        'title': str(r['title']) if r['title'] is not None else '',
        'metadata': {'source': 'nfcorpus', 'kb_id': 19}
    })
nf_corpus_path = os.path.join(CORPUS_DIR, 'nfcorpus_corpus.json')
with open(nf_corpus_path, 'w', encoding='utf-8') as f:
    json.dump(nf_corpus, f, ensure_ascii=False, indent=2)
print(f'  corpus: {nf_corpus_path} ({len(nf_corpus)} docs)')

# 加载 qrels test（3-level relevance）
qrels_raw = collections.defaultdict(dict)
with open(os.path.join(NF_DIR, 'qrels.test.tsv'), encoding='utf-8') as f:
    next(f)  # header
    for line in f:
        parts = line.rstrip().split('\t')
        if len(parts) >= 3:
            qid, cid, score = parts[0], parts[1], int(parts[2])
            qrels_raw[qid][cid] = score
print(f'  qrels.test queries: {len(qrels_raw)}')

# 过滤：只取至少 2 个 relevant docs（score>=1）的 query，确保非平凡
cand_qids = [q for q, rels in qrels_raw.items() if len(rels) >= 2]
print(f'  candidate queries (>=2 rel): {len(cand_qids)}')

# 抽 100
random.shuffle(cand_qids)
sel_qids = sorted(cand_qids[:100])

# 构建 query id → text 映射
qtext_by_id = {str(r['_id']): str(r['text']) for _, r in queries_df.iterrows()}

nf_samples = []
nf_qrels = {}
for i, qid in enumerate(sel_qids):
    text = qtext_by_id.get(qid, '')
    if not text:
        continue
    nf_samples.append({
        'question': text,
        'answer': '',
        'contexts': [],
        'ground_truth': '',     # 待 LLM 从 top relevant docs 生成
        'status': 'approved',
        'metadata': {
            'kb_id': 19,
            'source': 'nfcorpus',
            'qid': qid,
            'tags': ['英文', 'BEIR', 'nfcorpus'],
        }
    })
    nf_qrels[qid] = dict(qrels_raw[qid])

nf_testset = {
    'name': 'nfcorpus_100',
    'created_at': __import__('time').strftime('%Y-%m-%dT%H:%M:%S'),
    'count': len(nf_samples),
    'samples': nf_samples,
}
nf_testset_path = os.path.join(TESTSET_DIR, 'nfcorpus_100.json')
with open(nf_testset_path, 'w', encoding='utf-8') as f:
    json.dump(nf_testset, f, ensure_ascii=False, indent=2)
print(f'  testset: {nf_testset_path} ({len(nf_samples)} samples)')

nf_qrels_path = os.path.join(QRELS_DIR, 'nfcorpus_qrels.json')
with open(nf_qrels_path, 'w', encoding='utf-8') as f:
    json.dump({'qid_to_doc_id': nf_qrels, 'note': 'NFCorpus BEIR test qrels (3-level score)'}, f, ensure_ascii=False, indent=2)
print(f'  qrels: {nf_qrels_path} ({len(nf_qrels)} queries)')

# 统计 NFCorpus qrels 的 relevant 分布
total_rel = sum(len(v) for v in nf_qrels.values())
high_rel = sum(1 for v in nf_qrels.values() for s in v.values() if s >= 2)
print(f'  avg rel/query: {total_rel/len(nf_qrels):.2f}')
print(f'  high-rel (score>=2) pairs: {high_rel}')

# ============ 3. 汇总 ============
print('\n=== 汇总 ===')
print(f'CRUD-RAG: 300 queries × 1 relevant doc, gt 已自带')
print(f'NFCorpus: 100 queries × ~{total_rel//100} relevant docs, gt 待 LLM 生成')
print(f'KB 18: CRUD-RAG 中文 (300 docs)')
print(f'KB 19: NFCorpus 英文 (3633 docs)')
