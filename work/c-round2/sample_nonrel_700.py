"""从 CRUD_RAG/data/80000_docs/ 抽 700 篇 non-rel，拼成 1000 corpus
- 读全部 45 个 part 文件，每行 = 1 篇 doc
- 排除已用作 300 源 doc 的（按 text[:200] 前缀 hash 去重，避免完全重复）
- 随机抽 700 篇 non-rel（seed=20260907）
- 输出 corpus/crud_corpus_1000.json = 300 源 + 700 non-rel
"""
import os, sys, json, random, hashlib
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

THIS = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = r'd:\workspace\CRUD_RAG\data\80000_docs'
SRC_CORPUS_PATH = os.path.join(THIS, 'corpus', 'crud_corpus_300.json')
OUT_PATH = os.path.join(THIS, 'corpus', 'crud_corpus_1000.json')
SEED = 20260907

# 1. 加载 300 源 doc 的 hash（前 200 字符）
print('=== 1. 加载 300 源 doc ===')
with open(SRC_CORPUS_PATH, encoding='utf-8') as f:
    src_docs = json.load(f)
src_hashes = set()
for d in src_docs:
    h = hashlib.md5(d['text'][:200].encode('utf-8')).hexdigest()
    src_hashes.add(h)
print(f'  源 doc 数: {len(src_docs)}, hash 数: {len(src_hashes)}')

# 2. 读全部 80000_docs，每行 = 1 篇 doc，排除源 doc
print('\n=== 2. 读 80000_docs 全部 part 文件 ===')
all_non_rel = []
total_lines = 0
dup_with_src = 0
empty_lines = 0
for fname in sorted(os.listdir(DOCS_DIR)):
    fpath = os.path.join(DOCS_DIR, fname)
    if not os.path.isfile(fpath):
        continue
    try:
        with open(fpath, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line or len(line) < 50:
                    empty_lines += 1
                    continue
                total_lines += 1
                h = hashlib.md5(line[:200].encode('utf-8')).hexdigest()
                if h in src_hashes:
                    dup_with_src += 1
                    continue
                all_non_rel.append({'text': line, 'title': line[:60], 'hash': h})
    except Exception as e:
        print(f'  ERR {fname}: {e}')
print(f'  total lines: {total_lines}')
print(f'  dup with 300 src: {dup_with_src}')
print(f'  empty/too-short: {empty_lines}')
print(f'  non-rel candidates: {len(all_non_rel)}')

# 3. 随机抽 700 篇
print('\n=== 3. 随机抽 700 篇 non-rel ===')
random.seed(SEED)
if len(all_non_rel) < 700:
    print(f'  WARN: only {len(all_non_rel)} non-rel, use all')
    sampled = all_non_rel
else:
    sampled = random.sample(all_non_rel, 700)
print(f'  sampled: {len(sampled)}')

# 4. 拼 1000 corpus
print('\n=== 4. 拼 1000 corpus ===')
corpus_1000 = []
# 300 源 doc
for i, d in enumerate(src_docs):
    corpus_1000.append({
        'id': f'crud_{i:03d}',
        'text': d['text'],
        'title': d.get('title', ''),
        'metadata': {'source': 'crud-rag-src', 'kb_id': 65, 'is_relevant': True}
    })
# 700 non-rel
for i, d in enumerate(sampled):
    corpus_1000.append({
        'id': f'nonrel_{i:03d}',
        'text': d['text'],
        'title': d.get('title', ''),
        'metadata': {'source': 'crud-rag-80000-nonrel', 'kb_id': 65, 'is_relevant': False}
    })
print(f'  total corpus: {len(corpus_1000)} (300 src + 700 non-rel)')

# 5. 写
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(corpus_1000, f, ensure_ascii=False, indent=2)
print(f'\n[done] saved: {OUT_PATH}')
print(f'  size: {os.path.getsize(OUT_PATH)/1024/1024:.1f} MB')
