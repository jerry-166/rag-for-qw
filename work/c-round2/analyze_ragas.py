"""分析 faithfulness/answer_relevancy 低的原因：answer 和 contexts 是否匹配"""
import json

with open('d:/workspace/rag-for-qw/backend/evaluation/testsets/c2_crud_ours_native_rerank_off.json', encoding='utf-8') as f:
    d = json.load(f)

samples = d['samples']

# 统计 answer 类型
refuse_count = 0  # 拒绝回答
short_count = 0   # 短回答
normal_count = 0  # 正常回答
empty_count = 0   # 空回答

for s in samples:
    ans = s.get('answer', '')
    if not ans:
        empty_count += 1
    elif '无法' in ans or '未提及' in ans or '没有' in ans or '不包含' in ans:
        refuse_count += 1
    elif len(ans) < 50:
        short_count += 1
    else:
        normal_count += 1

print(f'answer 类型分布（300 samples）:')
print(f'  正常回答: {normal_count}')
print(f'  拒绝回答（无法/未提及/没有）: {refuse_count}')
print(f'  短回答（<50字）: {short_count}')
print(f'  空回答: {empty_count}')

# 看几个拒绝回答的 sample，确认 contexts 是否有相关信息
print('\n=== 拒绝回答的 sample 分析 ===')
refuse_samples = [s for s in samples if s.get('answer','') and ('无法' in s.get('answer','') or '未提及' in s.get('answer',''))]
for s in refuse_samples[:3]:
    print(f'\nQ: {s["question"][:60]}')
    print(f'A: {s["answer"][:100]}')
    ctx = s.get('contexts', [])
    print(f'contexts: {len(ctx)} 条')
    if ctx:
        print(f'  ctx[0]: {str(ctx[0])[:100]}')
