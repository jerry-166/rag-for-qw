import json

with open('d:/workspace/rag-for-qw/backend/evaluation/testsets/c2_crud_ours_native_rerank_off.json', encoding='utf-8') as f:
    d = json.load(f)

samples = d['samples']
print(f'total: {len(samples)}')

# 找包含 '852' 的 sample
for i, s in enumerate(samples):
    answer = str(s.get('answer', ''))
    gt = str(s.get('ground_truth', ''))
    contexts = s.get('contexts', [])
    
    # 检查是否有 '852'
    if '852' in answer or '852' in gt or any('852' in str(c) for c in contexts):
        print(f'\n[{i}] qid={s.get("metadata",{}).get("qid","")}')
        print(f'  answer type={type(s.get("answer")).__name__} len={len(answer)} preview={answer[:80]}')
        print(f'  gt type={type(s.get("ground_truth")).__name__} len={len(gt)} preview={gt[:80]}')
        print(f'  contexts type={type(contexts).__name__} count={len(contexts)}')
        if contexts:
            print(f'  ctx[0] type={type(contexts[0]).__name__} preview={str(contexts[0])[:80]}')
        break

# 查 answer/ground_truth 的类型分布
types_a = set(type(s.get('answer')).__name__ for s in samples)
types_g = set(type(s.get('ground_truth')).__name__ for s in samples)
types_c = set(type(s.get('contexts')).__name__ for s in samples)
print(f'\ntype distribution: answer={types_a} gt={types_g} contexts={types_c}')

# 查第一个 sample 的 answer
s0 = samples[0]
print(f'\nsample[0] answer type={type(s0.get("answer")).__name__}')
print(f'sample[0] answer={repr(s0.get("answer"))[:100]}')
print(f'sample[0] contexts={repr(s0.get("contexts"))[:100]}')
