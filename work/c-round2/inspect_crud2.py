"""快速看 CRUD-RAG questanswer_3docs 是否存在 + 各子任务字段
+ 探 NFCorpus HF dataset 结构（不下载，只列）"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

P = r'd:\workspace\CRUD_RAG\data\crud_split\split_merged.json'
with open(P, encoding='utf-8') as f:
    d = json.load(f)

print('=== CRUD-RAG 子任务统计 ===')
for k, v in d.items():
    if isinstance(v, list):
        print(f'{k}: {len(v)} items')
        if v and isinstance(v[0], dict):
            print(f'  keys: {list(v[0].keys())}')

# questanswer_1doc 取 5 条问题字段抽样
print('\n=== questanswer_1doc 样本（5 条 questions 字段）===')
qa1 = d.get('questanswer_1doc', [])
for i, s in enumerate(qa1[:5]):
    q = s.get('questions', '')[:120]
    a = s.get('answers', '')[:120]
    n1_len = len(s.get('news1', ''))
    print(f'[{i}] q={q}')
    print(f'    a={a}')
    print(f'    news1_len={n1_len}')
