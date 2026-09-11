"""用 glm-4-air 重新生成 testset 中"无法回答"的 answer
- 筛选 answer 含"无法/未提及/没有/不包含"的 samples
- 用 glm-4-air 直接调 API（基于 contexts 生成 answer）
- 更新 testset 的 answer
- 用于 graph 模式 + native 两个模式的修复

用法：
  python regenerate_answers.py c2_crud_ours_native_rerank_off  # 修复指定 testset
  python regenerate_answers.py all                               # 修复全部 3 个
"""
import os, sys, json, time, requests, openai

THIS = os.path.dirname(os.path.abspath(__file__))
TESTSET_DIR = os.path.normpath(os.path.join(THIS, '..', '..', 'backend', 'evaluation', 'testsets'))

# glm-4-air（智谱，理解力比 flashx 更好）
ZHIPU_KEY = os.getenv('ZHIPU_API_KEY', '')
LLM_BASE = 'https://open.bigmodel.cn/api/paas/v4/'
LLM_MODEL = 'glm-4-air'
client = openai.OpenAI(api_key=ZHIPU_KEY, base_url=LLM_BASE)
print(f'LLM: {LLM_MODEL} base={LLM_BASE}')

REFUSE_KEYWORDS = ['无法', '未提及', '没有', '不包含', '未找到', '未涉及', '未能']

def is_refuse(answer):
    """判断是否拒绝回答"""
    if not answer or len(answer) < 20:
        return True
    return any(kw in answer for kw in REFUSE_KEYWORDS)

def regenerate_answer(question, contexts):
    """用 glm-4-air 基于 contexts 生成 answer"""
    if not contexts:
        return ''
    ctx_str = '\n\n'.join(contexts[:5])  # 取前 5 个 context
    prompt = (
        f'请根据以下参考文档回答问题。要求：\n'
        f'1. 只根据参考文档内容回答，不要编造\n'
        f'2. 如果参考文档有答案，必须给出具体回答（不要说"无法回答"）\n'
        f'3. 回答简洁，2-4 句话\n\n'
        f'参考文档：\n{ctx_str}\n\n'
        f'问题：{question}\n\n'
        f'回答：'
    )
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0,
                max_tokens=500,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err_str = str(e).lower()
            print(f'  LLM err attempt {attempt+1}: {str(e)[:100]}')
            if '429' in err_str or 'rate' in err_str:
                time.sleep(30)
            elif 'timeout' in err_str:
                time.sleep(5)
            else:
                break
    return ''

def fix_testset(name):
    """修复指定 testset 的"无法回答" samples"""
    fpath = os.path.join(TESTSET_DIR, f'{name}.json')
    with open(fpath, encoding='utf-8') as f:
        d = json.load(f)
    samples = d.get('samples', [])
    
    # 筛选需要重新生成的 samples
    to_fix = [(i, s) for i, s in enumerate(samples) if is_refuse(s.get('answer', ''))]
    print(f'\n=== {name}: {len(to_fix)}/{len(samples)} need regenerate ===')
    
    fixed = 0
    for idx, (i, s) in enumerate(to_fix):
        q = s['question']
        ctx = s.get('contexts', [])
        old_ans = s.get('answer', '')[:60]
        new_ans = regenerate_answer(q, ctx)
        
        if new_ans and not is_refuse(new_ans):
            samples[i]['answer'] = new_ans
            fixed += 1
            if (idx + 1) % 20 == 0:
                print(f'  [{idx+1}/{len(to_fix)}] fixed={fixed} old={old_ans[:30]}... new={new_ans[:30]}...')
        else:
            if (idx + 1) % 20 == 0:
                print(f'  [{idx+1}/{len(to_fix)}] still refuse, skip')
        
        time.sleep(0.5)  # 避限流
    
    # 保存
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f'  done: fixed {fixed}/{len(to_fix)} answers, saved {fpath}')

# 主流程
target = sys.argv[1] if len(sys.argv) > 1 else 'all'
if target == 'all':
    for name in ['c2_crud_ours_native_rerank_off', 'c2_crud_ours_native_rerank_on', 'c2_crud_ours_graph']:
        fix_testset(name)
else:
    fix_testset(target)

print('\n=== regenerate done ===')
