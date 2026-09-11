"""C 轮2 RAGAS 9 对象四指标评估
16 测试集 × 4 指标 = 64 数据点 × 2 数据集 = 128 数据点
（实际是 8 模式 × 2 数据集 = 16 测试集；baseline = native_rerank_off 同对象）

8 模式 × 2 数据集：
  CRUD-RAG：ours_native_rerank_off/on, ours_advanced, ours_hybrid_vec, ours_keyword, ours_graph
            + lightrag_naive, lightrag_hybrid
  NFCorpus：同上 8 模式

四指标：faithfulness / answer_relevancy / context_precision / context_recall
judge：智谱 GLM-4-Flash-250414（默认），多模型轮换避 429
"""
import os, sys, asyncio, json, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from evaluation.evaluator import RagasEvaluator
from evaluation.dataset import EvaluationDataset

TESTSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets'))
REPORT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'reports'))
os.makedirs(REPORT_DIR, exist_ok=True)

# 16 个测试集（C2 fill_c2.py 产出）
# C 轮2 只测 graph vs native（3 测试集：native_rerank_off/on + graph）
TARGETS = []
for mode in ['native_rerank_off', 'native_rerank_on', 'graph']:
    TARGETS.append(f'c2_crud_ours_{mode}')

# 用于支持多模型轮换的 RagasEvaluator 子类
class MultiModelRagasEvaluator(RagasEvaluator):
    """支持多模型轮换的 RAGAS evaluator
    遇到 429/超时时切换到备用 LLM（DashScope qwen3-flash）
    """
    FALLBACK_CHAIN = [
        # (model, base_url, api_key_env)
        ('glm-4-flash-250414', 'https://open.bigmodel.cn/api/paas/v4/', 'ZHIPU_API_KEY'),
        ('qwen3-flash', 'https://dashscope.aliyuncs.com/compatible-mode/v1/', 'DASHSCOPE_API_KEY'),
        ('glm-4-flash', 'https://open.bigmodel.cn/api/paas/v4/', 'ZHIPU_API_KEY'),
    ]
    _cur_idx = 0

    def __init__(self):
        # 用第一个模型初始化
        m, bu, ke = self.FALLBACK_CHAIN[0]
        api_key = os.getenv(ke, '')
        super().__init__(llm_base_url=bu, llm_api_key=api_key, llm_model=m)
        self._cur_idx = 0
        print(f'[judge] using model={m} base={bu}')

    def _rotate(self):
        """切到下一个备用 LLM"""
        self._cur_idx = (self._cur_idx + 1) % len(self.FALLBACK_CHAIN)
        m, bu, ke = self.FALLBACK_CHAIN[self._cur_idx]
        api_key = os.getenv(ke, '')
        self.llm_model = m
        self.llm_base_url = bu
        self.llm_api_key = api_key
        self._ragas_llm = None  # 重置缓存
        print(f'[judge] rotated to model={m} base={bu}')

async def run_one(name, evaluator):
    """跑单个测试集的 RAGAS 评估"""
    dataset = EvaluationDataset.load(f'{name}.json')
    print(f'\n=== {name}: {len(dataset)} samples ===')
    t0 = time.time()
    # 多模型轮换：遇异常时切换
    for attempt in range(3):
        try:
            report = await evaluator.evaluate(dataset)
            elapsed = time.time() - t0
            print(f'  elapsed: {elapsed:.1f}s')
            print(f'  scores: {report.scores}')
            if report.error:
                # 检查是否是 429/限流类错误
                err_str = str(report.error).lower()
                if '429' in err_str or 'rate' in err_str or 'timeout' in err_str:
                    print(f'  [attempt {attempt+1}] 限流/超时，切换 LLM 重试')
                    evaluator._rotate()
                    continue
                else:
                    print(f'  ERROR: {report.error[:200]}')
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
        except Exception as e:
            err_str = str(e).lower()
            print(f'  [attempt {attempt+1}] EXCEPTION: {str(e)[:200]}')
            if '429' in err_str or 'rate' in err_str or 'timeout' in err_str:
                evaluator._rotate()
                continue
            return {'name': name, 'error': str(e)[:200]}
    return {'name': name, 'error': 'all retries failed'}

async def main():
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else 'all'
    targets = TARGETS
    if mode_arg in ('crud', 'nfcorpus'):
        targets = [t for t in TARGETS if t.startswith(f'c2_{mode_arg}_')]
    elif mode_arg in ('native_rerank_off', 'native_rerank_on', 'graph'):
        targets = [t for t in TARGETS if t.endswith(f'_{mode_arg}')]
    elif mode_arg == 'native':
        targets = [t for t in TARGETS if 'native' in t]
    print(f'RAGAS C2 评估，judge=智谱 GLM-4-Flash-250414（多模型轮换）')
    print(f'测试集目录: {TESTSET_DIR}')
    print(f'报告目录: {REPORT_DIR}')
    print(f'目标 ({len(targets)}): CRUD-RAG ours 6 模式')
    print(f'  {targets}')

    evaluator = MultiModelRagasEvaluator()
    results = []
    for name in targets:
        try:
            r = await run_one(name, evaluator)
            if r:
                results.append(r)
        except Exception as e:
            print(f'  [{name}] OUTER EXCEPTION: {str(e)[:200]}')
            results.append({'name': name, 'error': str(e)[:200]})

    # 汇总
    print('\n' + '=' * 100)
    print('RAGAS C2 汇总')
    print('=' * 100)
    print(f'{"对象":<40} {"faith":>8} {"ans_rel":>8} {"ctx_pre":>8} {"ctx_rec":>8} {"samples":>8}')
    print('-' * 100)
    for r in results:
        name = r['name'][:38]
        s = r.get('scores', {})
        err = r.get('error')
        if err and not s:
            print(f'{name:<40} {"ERR":>8} {"":>8} {"":>8} {"":>8} {r.get("total_samples",""):>8}  {err[:40]}')
        else:
            print(f'{name:<40} {s.get("faithfulness",0):>8.3f} {s.get("answer_relevancy",0):>8.3f} {s.get("context_precision",0):>8.3f} {s.get("context_recall",0):>8.3f} {r.get("total_samples",0):>8}')

    summary_path = os.path.join(REPORT_DIR, 'c_round2_ragas_summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'\n汇总已保存: {summary_path}')

if __name__ == '__main__':
    asyncio.run(main())
