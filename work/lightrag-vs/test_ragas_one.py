"""先单测 kb17_ours_native_rerank_off 确认 RAGAS 评估流程能跑通"""
import os, sys, asyncio, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
# cd 到 backend 让 TESTSET_DIR 相对路径生效
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from evaluation.evaluator import RagasEvaluator
from evaluation.dataset import EvaluationDataset

async def main():
    # 只取前 2 条快速测
    ds = EvaluationDataset.load('kb17_ours_native_rerank_off.json')
    ds.samples = ds.samples[:2]
    ds._count = 2
    print(f'测试集: {ds.name}, samples: {len(ds)}')
    for s in ds.samples:
        print(f'  q={s.question[:30]} ans_len={len(s.answer or "")} ctx={len(s.contexts)} gt_len={len(s.ground_truth or "")}')

    evaluator = RagasEvaluator()
    print(f'LLM model: {evaluator.llm_model}')
    print(f'LLM base_url: {evaluator.llm_base_url}')

    t0 = time.time()
    report = await evaluator.evaluate(ds)
    elapsed = time.time() - t0
    print(f'\nelapsed: {elapsed:.1f}s')
    print(f'scores: {report.scores}')
    if report.error:
        print(f'ERROR: {report.error[:300]}')
    for ss in report.sample_scores:
        print(f'  {ss["question"][:30]}: {ss["scores"]}')

asyncio.run(main())
