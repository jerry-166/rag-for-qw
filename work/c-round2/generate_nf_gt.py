"""C 轮2 NFCorpus ground_truth 生成
NFCorpus 没有自带 answer，只有 qrels。为 RAGAS context_recall/context_precision 准备 gt：
- 用 qrel 中 score>=2 的 corpus docs 作为 contexts
- 调 LLM (智谱 GLM-4-Flash-250414) 从 contexts 生成 answer
- 把 answer 写回 testsets/nfcorpus_100.json 的 ground_truth 字段

CRUD-RAG 已有 answers 字段，不需生成。
"""
import os, sys, json, time, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 用智谱 GLM-4-Flash-250414
import openai
THIS = os.path.dirname(os.path.abspath(__file__))
TESTSET_DIR = os.path.normpath(os.path.join(THIS, '..', '..', 'backend', 'evaluation', 'testsets'))
QRELS_PATH = os.path.join(THIS, 'qrels', 'nfcorpus_qrels.json')
CORPUS_PATH = os.path.join(THIS, 'corpus', 'nfcorpus_corpus.json')
TS_PATH = os.path.join(TESTSET_DIR, 'nfcorpus_100.json')

ZHIPU_KEY = os.getenv('ZHIPU_API_KEY', '')
LLM_BASE = 'https://open.bigmodel.cn/api/paas/v4/'
LLM_MODEL = 'glm-4-flash-250414'
print(f'LLM: {LLM_MODEL} base={LLM_BASE} key={ZHIPU_KEY[:8]}...')

client = openai.OpenAI(api_key=ZHIPU_KEY, base_url=LLM_BASE)

# 加载
with open(CORPUS_PATH, encoding='utf-8') as f:
    corpus_list = json.load(f)
corpus_by_id = {d['id']: d for d in corpus_list}
print(f'corpus: {len(corpus_by_id)} docs')

with open(QRELS_PATH, encoding='utf-8') as f:
    qrels = json.load(f).get('qid_to_doc_id', {})
print(f'qrels: {len(qrels)} queries')

with open(TS_PATH, encoding='utf-8') as f:
    ts = json.load(f)
samples = ts.get('samples', [])
print(f'testset: {len(samples)} samples')

# 给每个 sample 生成 gt
def gen_answer(question, contexts):
    """调 LLM 从 contexts 生成 answer"""
    if not contexts:
        return ''
    ctx_str = '\n\n'.join(contexts[:3])  # 取前 3 个相关 doc 作 contexts
    prompt = (
        f'Based on the following reference documents, answer the question concisely '
        f'(2-4 sentences, English).\n\n'
        f'Reference documents:\n{ctx_str}\n\n'
        f'Question: {question}\n\n'
        f'Answer:'
    )
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0,
                max_tokens=300,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err_str = str(e).lower()
            print(f'  LLM err attempt {attempt+1}: {str(e)[:120]}')
            if '429' in err_str or 'rate' in err_str:
                print('  [429] sleeping 60s')
                time.sleep(60)
            elif 'timeout' in err_str:
                time.sleep(5)
            else:
                break
    return ''

t0 = time.time()
for i, s in enumerate(samples):
    qid = s.get('metadata', {}).get('qid', '')
    if not qid:
        print(f'  [{i+1}] no qid, skip')
        continue
    # 已生成则跳过
    if s.get('ground_truth'):
        continue
    rels = qrels.get(qid, {})
    # 取 score>=2 的 docs 作为 gt 生成 contexts
    high_rel_ids = [cid for cid, sc in rels.items() if sc >= 2]
    if not high_rel_ids:
        high_rel_ids = [cid for cid, sc in rels.items() if sc >= 1][:3]
    contexts = []
    for cid in high_rel_ids[:5]:  # 最多取 5 个
        doc = corpus_by_id.get(cid, {})
        text = doc.get('text', '')
        title = doc.get('title', '')
        if text:
            contexts.append(f'{title}\n{text}' if title else text)
    gt = gen_answer(s['question'], contexts)
    s['ground_truth'] = gt
    if (i + 1) % 10 == 0 or i == len(samples) - 1:
        ok = sum(1 for x in samples if x.get('ground_truth'))
        print(f'  [{i+1}/{len(samples)}] qid={qid} high_rel={len(high_rel_ids)} gt_len={len(gt)} ok_total={ok} elapsed={time.time()-t0:.0f}s')

# 写回 testset
ts['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
ts['samples'] = samples
with open(TS_PATH, 'w', encoding='utf-8') as f:
    json.dump(ts, f, ensure_ascii=False, indent=2)
ok = sum(1 for s in samples if s.get('ground_truth'))
print(f'\n[done] {ok}/{len(samples)} samples with gt, saved {TS_PATH}')
print(f'  elapsed: {time.time()-t0:.0f}s')
