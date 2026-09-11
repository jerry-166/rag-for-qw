"""修复 kb17_ours_hybrid_vec 测试集（complete=0，需重填 contexts）
单独跑 hybrid_vec 模式，复用 supplement 的 question+answer+ground_truth
"""
import requests, json, os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
TESTSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets'))

TOKEN = requests.post(B + '/api/auth/login',
    data={'username': 'loadtester', 'password': 'Loadtest#123'},
    timeout=10).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}

src = json.load(open(os.path.join(TESTSET_DIR, 'kb17_supplement.json'), encoding='utf-8'))
src_samples = src.get('samples', [])
print(f"source samples: {len(src_samples)}")

samples = []
for i, s in enumerate(src_samples):
    q = s['question']
    try:
        r = requests.post(f"{B}/api/hybrid/search",
            json={'query': q, 'limit': 10, 'knowledge_base_id': 17,
                  'retrieval_mode': 'hybrid', 'use_rerank': True},
            headers=H, timeout=30)
        results = r.json().get('results', [])
        contexts = [c.get('content', c.get('chunk_text', ''))
                    for c in results
                    if c.get('content', c.get('chunk_text', ''))]
    except Exception as e:
        print(f"  [{i+1}] err: {str(e)[:60]}")
        contexts = []

    samples.append({
        'question': q,
        'answer': s.get('answer', ''),
        'contexts': contexts,
        'ground_truth': s['ground_truth'],
        'status': 'approved',
        'metadata': {'kb_id': 17, 'source': 'ours', 'mode': 'hybrid_vec', 'tags': ['技术']}
    })
    print(f"[hybrid_vec {i+1}/{len(src_samples)}] {q[:30]}: ctx={len(contexts)}")
    time.sleep(0.3)

out_path = os.path.join(TESTSET_DIR, 'kb17_ours_hybrid_vec.json')
dataset = {
    'name': 'kb17_ours_hybrid_vec',
    'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    'count': len(samples),
    'samples': samples,
}
json.dump(dataset, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
complete = sum(1 for s in samples if s['answer'] and s['contexts'])
print(f"\n[done] hybrid_vec: {len(samples)} samples, complete={complete}")
