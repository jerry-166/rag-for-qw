"""探 NFCorpus parquet 与 qrels tsv 结构"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

D = r'd:\workspace\rag-for-qw\work\c-round2\nfcorpus'

# 用 pandas 读 parquet
try:
    import pandas as pd
    print('=== corpus.parquet ===')
    df = pd.read_parquet(os.path.join(D, 'corpus.parquet'))
    print(f'rows: {len(df)}')
    print(f'cols: {list(df.columns)}')
    print(f'dtypes:\n{df.dtypes}')
    print(f'\nsample[0]:')
    for c in df.columns:
        v = df.iloc[0][c]
        s = str(v)[:200]
        print(f'  {c}: {s}')

    print('\n=== queries.parquet ===')
    qf = pd.read_parquet(os.path.join(D, 'queries.parquet'))
    print(f'rows: {len(qf)}')
    print(f'cols: {list(qf.columns)}')
    print(f'\nsample[0]:')
    for c in qf.columns:
        v = qf.iloc[0][c]
        s = str(v)[:200]
        print(f'  {c}: {s}')

    # 若有 split 字段统计
    if 'split' in qf.columns:
        print(f'\nqueries split counts:')
        print(qf['split'].value_counts())

except Exception as e:
    print(f'ERR: {e}')

print('\n=== qrels.test.tsv (head 5) ===')
with open(os.path.join(D, 'qrels.test.tsv'), encoding='utf-8') as f:
    for i, line in enumerate(f):
        if i < 5:
            print(repr(line.rstrip()))
        else:
            break

# 统计 qrels test 中 query 数
import collections
q_count = collections.Counter()
total_lines = 0
with open(os.path.join(D, 'qrels.test.tsv'), encoding='utf-8') as f:
    next(f)  # header
    for line in f:
        total_lines += 1
        parts = line.rstrip().split('\t')
        if len(parts) >= 2:
            q_count[parts[0]] += 1
print(f'\nqrels.test total relevance pairs: {total_lines}')
print(f'unique queries in test: {len(q_count)}')
print(f'avg docs per query: {total_lines/len(q_count):.2f}' if q_count else 'NA')
