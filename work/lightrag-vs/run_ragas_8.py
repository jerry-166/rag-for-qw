"""C 轮1 RAGAS 8 对象评估
8 对象 = 本项目 5 模式 + LightRAG 2 模式
judge 智谱 GLM-4-Flash
四指标: faithfulness / answer_relevancy / context_precision / context_recall
直接调 RagasEvaluator（绕 30 条门控），每个测试集 32 条
"""
import os, sys, asyncio, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from evaluation.evaluator import RagasEvaluator
from evaluation.dataset import EvaluationDataset

TESTSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets'))
REPORT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'reports'))

TARGETS = [
    'kb17_ours_native_rerank_off',
    'kb17_ours_native_rerank_on',
    'kb17_ours_advanced',
    'kb17_ours_hybrid_vec',
    'kb17_ours_keyword',
    'kb17_lightrag_naive',
    'kb17_lightrag_hybrid',
]

# 第一个 kb17_supplement 也是评估对象（作为 baseline，本项目 native rerank关 的 agent answer）
TARGETS_ALL = ['kb17_supplement'] + TARGETS

async def run_one(name):
    """跑单个测试集的 RAGAS 评估"""
    dataset = EvaluationDataset.load(f'{name}.json')
    print(f'\n=== {name}: {len(dataset)} samples ===')
    evaluator = RagasEvaluator()
    t0 = time.time()
    report = await evaluator.evaluate(dataset)
    elapsed = time.time() - t0
    print(f'  elapsed: {elapsed:.1f}s')
    print(f'  scores: {report.scores}')
    if report.error:
        print(f'  ERROR: {report.error[:200]}')
    # 保存报告
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = report.save(REPORT_DIR)
    print(f'  saved: {report_path}')
    return {
        'name': name,
        'scores': report.scores,
        'total_samples': report.total_samples,
        'skipped': report.skipped_samples,
        'error': report.error,
        'elapsed': elapsed,
        'report_path': report_path,
    }

async def main():
    print(f'RAGAS 8 对象评估，judge=智谱 GLM-4-Flash')
    print(f'测试集目录: {TESTSET_DIR}')
    print(f'报告目录: {REPORT_DIR}')
    print(f'目标: {TARGETS_ALL}')

    results = []
    for name in TARGETS_ALL:
        try:
            r = await run_one(name)
            if r:
                results.append(r)
        except Exception as e:
            print(f'  [{name}] EXCEPTION: {str(e)[:200]}')
            results.append({'name': name, 'error': str(e)[:200]})

    # 汇总
    print('\n' + '=' * 80)
    print('RAGAS 8 对象汇总')
    print('=' * 80)
    print(f'{"对象":<32} {"faith":>8} {"ans_rel":>8} {"ctx_pre":>8} {"ctx_rec":>8} {"samples":>8}')
    print('-' * 80)
    for r in results:
        name = r['name'][:30]
        s = r.get('scores', {})
        err = r.get('error')
        if err:
            print(f'{name:<32} {"ERR":>8} {"":>8} {"":>8} {"":>8} {r.get("total_samples",""):>8}  {err[:40]}')
        else:
            print(f'{name:<32} {s.get("faithfulness",0):>8.3f} {s.get("answer_relevancy",0):>8.3f} {s.get("context_precision",0):>8.3f} {s.get("context_recall",0):>8.3f} {r.get("total_samples",0):>8}')

    # 保存汇总
    summary_path = os.path.join(REPORT_DIR, 'c_round1_ragas_summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'\n汇总已保存: {summary_path}')

if __name__ == '__main__':
    asyncio.run(main())
