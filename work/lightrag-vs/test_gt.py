"""直接调 generate_ground_truth 看错误（gt_generator 配置 DashScope）。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
from evaluation.gt_generator import generate_ground_truth

try:
    gt = generate_ground_truth(
        'BM25打分原理是什么',
        ['BM25是基于词频与逆文档频率的经典排序函数，对查询词在文档中的频率与文档长度联合打分。它无需训练、可解释、能精确匹配关键词。'])
    print('gt:', gt[:200] if gt else 'EMPTY')
except Exception as e:
    print('ERR:', type(e).__name__, str(e)[:400])
