"""C 轮2 Fill 测试集（简化版）：native + graph 2 模式 × CRUD-RAG 300 query
策略同 C1：1 共享 answer（/api/agent/chat 默认 advanced 检索生成），每模式只换 contexts
- native：/api/milvus/query use_rerank=False retrieval_mode=native
- graph：/api/milvus/query use_rerank=True retrieval_mode=graph

输出：
  backend/evaluation/testsets/c2_crud_ours_native.json
  backend/evaluation/testsets/c2_crud_ours_graph.json
"""
import os, sys, json, time, requests, threading
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
TESTSET_DIR = os.path.normpath(os.path.join(THIS, '..', '..', 'backend', 'evaluation', 'testsets'))

# token 管理
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}
def get_token(force=False):
    with _token_lock:
        now = time.time()
        if force or _token_state['token'] is None or now - _token_state['login_at'] > 50*60:
            r = requests.post(f'{B}/api/auth/login',
                data={'username': 'loadtester', 'password': 'Loadtest#123'}, timeout=10)
            r.raise_for_status()
            _token_state['token'] = r.json()['access_token']
            _token_state['login_at'] = now
        return _token_state['token']
def H():
    return {'Authorization': f'Bearer {get_token()}'}
print(f'login ok, token={get_token()[:20]}...')

KB_ID = 65
SRC_NAME = 'crud_rag_300'

# 2 模式定义
MODES = [
    ('native', 'milvus/query', {'retrieval_mode': 'native', 'use_rerank': False}),
    ('graph', 'milvus/query', {'retrieval_mode': 'graph', 'use_rerank': True}),
]

def get_shared_answer(question, kb_id):
    """调 /api/agent/chat 生成共享 answer"""
    try:
        r = requests.post(f'{B}/api/agent/chat',
            json={'query': question, 'knowledge_base_id': kb_id, 'agent_type': 'claw'},
            headers=H(), timeout=180)
        if r.status_code == 401:
            get_token(force=True)
            r = requests.post(f'{B}/api/agent/chat',
                json={'query': question, 'knowledge_base_id': kb_id, 'agent_type': 'claw'},
                headers=H(), timeout=180)
        if r.status_code != 200:
            return '', f'{r.status_code} {r.text[:120]}'
        j = r.json()
        answer = j.get('response', '') or j.get('content', '') or ''
        return answer, ''
    except Exception as e:
        return '', str(e)[:120]

def get_contexts(question, mode_name, endpoint, extra, kb_id):
    """调本项目检索端点拿 contexts"""
    try:
        r = requests.post(f'{B}/api/{endpoint}',
            json={'query': question, 'limit': 10, 'knowledge_base_id': kb_id, **extra},
            headers=H(), timeout=30)
        if r.status_code == 401:
            get_token(force=True)
            r = requests.post(f'{B}/api/{endpoint}',
                json={'query': question, 'limit': 10, 'knowledge_base_id': kb_id, **extra},
                headers=H(), timeout=30)
        if r.status_code != 200:
            return [], f'{r.status_code} {r.text[:120]}'
        results = r.json().get('results', [])
        contexts = [c.get('content') or c.get('chunk_text', '')
                    for c in results
                    if c.get('content') or c.get('chunk_text', '')]
        return contexts, ''
    except Exception as e:
        return [], str(e)[:120]

def save_testset(name, samples):
    out_path = os.path.join(TESTSET_DIR, f'c2_crud_ours_{name}.json')
    dataset = {
        'name': f'c2_crud_ours_{name}',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'count': len(samples),
        'samples': samples,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    complete = sum(1 for s in samples if s['answer'] and s['contexts'])
    print(f'  saved: {out_path} ({len(samples)} samples, complete={complete})')

# 加载源 testset
src_path = os.path.join(TESTSET_DIR, f'{SRC_NAME}.json')
with open(src_path, encoding='utf-8') as f:
    src = json.load(f)
samples = src.get('samples', [])
print(f'source samples: {len(samples)}')

# Step 1: 生成共享 answer
print(f'\n[Step 1] 生成共享 answer（/api/agent/chat）')
shared_answers = []
t0 = time.time()
for i, s in enumerate(samples):
    q = s['question']
    ans, msg = get_shared_answer(q, KB_ID)
    shared_answers.append({'answer': ans, 'msg': msg})
    if (i + 1) % 20 == 0 or i == len(samples) - 1:
        ok = sum(1 for x in shared_answers if x['answer'])
        print(f'  [{i+1}/{len(samples)}] ok={ok} elapsed={time.time()-t0:.0f}s', flush=True)

# Step 2: 2 模式独立检索 contexts
print(f'\n[Step 2] 2 模式独立检索 contexts')
mode_contexts = {m[0]: [] for m in MODES}
for mode_name, endpoint, extra in MODES:
    print(f'\n  [mode] {mode_name}')
    t1 = time.time()
    for i, s in enumerate(samples):
        q = s['question']
        ctx, msg = get_contexts(q, mode_name, endpoint, extra, KB_ID)
        mode_contexts[mode_name].append({'contexts': ctx, 'msg': msg})
        time.sleep(0.1)
        if (i + 1) % 50 == 0:
            ok = sum(1 for x in mode_contexts[mode_name] if x['contexts'])
            print(f'    [{i+1}/{len(samples)}] ok={ok} elapsed={time.time()-t1:.0f}s', flush=True)

# Step 3: 组装 2 个 testset
print(f'\n[Step 3] 组装 testsets')
for mode_name, _, _ in MODES:
    out_samples = []
    for i, s in enumerate(samples):
        sa = shared_answers[i]
        mc = mode_contexts[mode_name][i]
        out_samples.append({
            'question': s['question'],
            'answer': sa['answer'],
            'contexts': mc['contexts'],
            'ground_truth': s.get('ground_truth', ''),
            'status': 'approved',
            'metadata': {
                'kb_id': KB_ID,
                'source': 'ours',
                'mode': mode_name,
                'dataset': 'crud',
                'qid': s.get('metadata', {}).get('qid', str(i)),
                'tags': s.get('metadata', {}).get('tags', []),
            }
        })
    save_testset(mode_name, out_samples)

print(f'\n=== fill done ===')
