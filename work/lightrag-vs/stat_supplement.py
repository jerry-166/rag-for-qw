"""统计 kb17_supplement 测试集"""
import json, os
p = os.path.normpath(os.path.join(os.path.dirname(__file__),'..','..','backend','evaluation','testsets','kb17_supplement.json'))
d = json.load(open(p, encoding='utf-8'))
samples = d.get('samples',[])
print(f"total: {len(samples)}")
with_gt = sum(1 for s in samples if s.get('ground_truth'))
with_answer = sum(1 for s in samples if s.get('answer'))
with_ctx = sum(1 for s in samples if s.get('contexts'))
approved = sum(1 for s in samples if s.get('status')=='approved')
evaluable = sum(1 for s in samples if s.get('answer') and s.get('contexts') and s.get('ground_truth') and s.get('status')=='approved')
print(f"with_gt={with_gt} with_answer={with_answer} with_ctx={with_ctx} approved={approved} evaluable={evaluable}")
print(f"first q: {samples[0]['question'][:40] if samples else 'none'}")
print(f"first gt: {samples[0]['ground_truth'][:40] if samples else 'none'}")
