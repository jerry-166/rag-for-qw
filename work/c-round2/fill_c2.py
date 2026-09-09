"""C 轮2 fill 测试集：8 模式 × 2 数据集 = 16 个测试集

策略（同 C 轮1）：
  ours 6 模式：共享一份 answer（/api/agent/chat 默认检索生成），每模式只换 contexts
    （/api/milvus/query / hybrid/search / elasticsearch/search 拿 contexts）
  LightRAG 2 模式：/query 拿 answer + /query/data 拿 contexts（answer 来自 LightRAG）

ground_truth：
  CRUD-RAG：testset 自带（answers 字段，自然 gt）
  NFCorpus：需 LLM 生成（从 top relevant docs 抽 answer）—— 在 generate_nf_gt.py 单独做

输出：
  backend/evaluation/testsets/c2_crud_ours_native_rerank_off.json  （baseline，shared answer）
  backend/evaluation/testsets/c2_crud_ours_native_rerank_on.json
  backend/evaluation/testsets/c2_crud_ours_advanced.json
  backend/evaluation/testsets/c2_crud_ours_hybrid_vec.json
  backend/evaluation/testsets/c2_crud_ours_keyword.json
  backend/evaluation/testsets/c2_crud_ours_graph.json
  backend/evaluation/testsets/c2_crud_lightrag_naive.json
  backend/evaluation/testsets/c2_crud_lightrag_hybrid.json
  （NFCorpus 同样 8 个）
"""
import os, sys, json, time, requests, threading
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

B = 'http://localhost:8003'
LR = 'http://localhost:9621'
THIS = os.path.dirname(os.path.abspath(__file__))
TESTSET_DIR = os.path.normpath(os.path.join(THIS, '..', '..', 'backend', 'evaluation', 'testsets'))

# ── token 管理 ──
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}
_TTL = 50 * 60

def _login():
    r = requests.post(f'{B}/api/auth/login',
        data={'username': 'loadtester', 'password': 'Loadtest#123'},
        timeout=10)
    r.raise_for_status()
    return r.json()['access_token']

def get_token(force=False):
    with _token_lock:
        now = time.time()
        if force or _token_state['token'] is None or now - _token_state['login_at'] > _TTL:
            _token_state['token'] = _login()
            _token_state['login_at'] = now
        return _token_state['token']

def H():
    return {'Authorization': f'Bearer {get_token()}'}

print(f'login ok, token={get_token()[:20]}...')

# ── ours 模式定义（仅 contexts 检索；answer 共享） ──
OURS_MODES = [
    ('native_rerank_off', 'milvus/query', {'retrieval_mode': 'native', 'use_rerank': False}),
    ('native_rerank_on',  'milvus/query', {'retrieval_mode': 'native', 'use_rerank': True}),
    ('advanced',         'milvus/query', {'retrieval_mode': 'advanced', 'use_rerank': True}),
    ('hybrid_vec',       'hybrid/search', {'retrieval_mode': 'hybrid', 'use_rerank': True}),
    ('keyword',          'elasticsearch/search', {'retrieval_mode': 'native', 'use_rerank': True}),
    ('graph',            'milvus/query', {'retrieval_mode': 'graph', 'use_rerank': True}),
]

def get_shared_answer(question, kb_id):
    """调 /api/agent/chat 生成共享 answer（默认 advanced 检索）
    返回 (answer, contexts_from_agent, sources)
    """
    try:
        r = requests.post(f'{B}/api/agent/chat',
            json={'query': question, 'knowledge_base_id': kb_id,
                  'agent_type': 'claw'},
            headers=H(), timeout=120)
        if r.status_code == 401:
            get_token(force=True)
            r = requests.post(f'{B}/api/agent/chat',
                json={'query': question, 'knowledge_base_id': kb_id,
                      'agent_type': 'claw'},
                headers=H(), timeout=120)
        if r.status_code != 200:
            return '', [], f'{r.status_code} {r.text[:120]}'
        j = r.json()
        answer = j.get('response', '') or j.get('content', '') or ''
        sources = j.get('sources', []) or j.get('metadata', {}).get('sources', [])
        contexts = [s.get('chunk_text') or s.get('content', '') for s in sources
                    if s.get('chunk_text') or s.get('content')]
        return answer, contexts, ''
    except Exception as e:
        return '', [], str(e)[:120]

def get_ours_contexts(question, mode_name, endpoint, extra, kb_id):
    """调本项目检索端点拿 contexts（不生成 answer）"""
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

def get_lightrag_answer_contexts(question, mode):
    """调 LightRAG /query 拿 answer + /query/data 拿 chunks"""
    answer = ''
    try:
        r = requests.post(f'{LR}/query',
            json={'query': question, 'mode': mode, 'top_k': 10},
            timeout=120)
        answer = r.json().get('response', '')
    except Exception as e:
        print(f'  /query err: {str(e)[:80]}')

    contexts = []
    try:
        r2 = requests.post(f'{LR}/query/data',
            json={'query': question, 'mode': mode, 'chunk_top_k': 10},
            timeout=120)
        data = r2.json().get('data', {})
        chunks = data.get('chunks', [])
        contexts = [c.get('content', '') for c in chunks if c.get('content')]
    except Exception as e:
        print(f'  /query/data err: {str(e)[:80]}')
    return answer, contexts

def save_testset(name, samples):
    out_path = os.path.join(TESTSET_DIR, f'c2_{name}.json')
    dataset = {
        'name': f'c2_{name}',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'count': len(samples),
        'samples': samples,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    complete = sum(1 for s in samples if s['answer'] and s['contexts'])
    print(f'  saved: {out_path} ({len(samples)} samples, complete={complete})')

def fill_dataset(dataset_short, testset_name, kb_id):
    """跑单个数据集的 8 模式 fill"""
    print(f'\n{"="*60}\n=== fill: {dataset_short} (kb_id={kb_id}) ===\n{"="*60}')
    src_path = os.path.join(TESTSET_DIR, f'{testset_name}.json')
    with open(src_path, encoding='utf-8') as f:
        src = json.load(f)
    samples = src.get('samples', [])
    print(f'source samples: {len(samples)}')

    # ── Step 1: 生成共享 answer（ours 6 模式共享） + LightRAG 2 模式独立 ──
    print('\n[Step 1] 生成 ours 共享 answer + LightRAG 独立 answer')
    shared_answers = []   # [{answer, contexts, msg}]
    lr_naive_data = []    # [{answer, contexts}]
    lr_hybrid_data = []
    t0 = time.time()
    for i, s in enumerate(samples):
        q = s['question']
        # ours 共享 answer
        ans, ctx, msg = get_shared_answer(q, kb_id)
        shared_answers.append({'answer': ans, 'contexts': ctx, 'msg': msg})
        # LightRAG naive
        lr_naive_ans, lr_naive_ctx = get_lightrag_answer_contexts(q, 'naive')
        lr_naive_data.append({'answer': lr_naive_ans, 'contexts': lr_naive_ctx})
        # LightRAG hybrid
        lr_hybrid_ans, lr_hybrid_ctx = get_lightrag_answer_contexts(q, 'hybrid')
        lr_hybrid_data.append({'answer': lr_hybrid_ans, 'contexts': lr_hybrid_ctx})
        if (i + 1) % 20 == 0 or i == len(samples) - 1:
            ok_ours = sum(1 for x in shared_answers if x['answer'])
            ok_naive = sum(1 for x in lr_naive_data if x['answer'])
            ok_hybrid = sum(1 for x in lr_hybrid_data if x['answer'])
            print(f'  [{i+1}/{len(samples)}] elapsed={time.time()-t0:.0f}s ours_ans={ok_ours} lr_naive={ok_naive} lr_hybrid={ok_hybrid}')

    # ── Step 2: ours 6 模式每模式独立检索 contexts ──
    print('\n[Step 2] ours 6 模式独立检索 contexts')
    ours_contexts = {m[0]: [] for m in OURS_MODES}
    for mode_name, endpoint, extra in OURS_MODES:
        print(f'  [mode] {mode_name}')
        t1 = time.time()
        for i, s in enumerate(samples):
            q = s['question']
            ctx, msg = get_ours_contexts(q, mode_name, endpoint, extra, kb_id)
            ours_contexts[mode_name].append({'contexts': ctx, 'msg': msg})
            time.sleep(0.1)
            if (i + 1) % 50 == 0:
                ok = sum(1 for x in ours_contexts[mode_name] if x['contexts'])
                print(f'    [{i+1}/{len(samples)}] ok={ok} elapsed={time.time()-t1:.0f}s')
        ok = sum(1 for x in ours_contexts[mode_name] if x['contexts'])
        print(f'  {mode_name} done: ok={ok}/{len(samples)} elapsed={time.time()-t1:.0f}s')

    # ── Step 3: 组装 8 个 testset ──
    print('\n[Step 3] 组装 testsets')
    # ours 6 模式
    for mode_name, _, _ in OURS_MODES:
        out_samples = []
        for i, s in enumerate(samples):
            sa = shared_answers[i]
            oc = ours_contexts[mode_name][i]
            out_samples.append({
                'question': s['question'],
                'answer': sa['answer'],
                'contexts': oc['contexts'],
                'ground_truth': s.get('ground_truth', ''),
                'status': 'approved',
                'metadata': {
                    'kb_id': kb_id,
                    'source': 'ours',
                    'mode': mode_name,
                    'dataset': dataset_short,
                    'qid': s.get('metadata', {}).get('qid', str(i)),
                    'tags': s.get('metadata', {}).get('tags', []),
                }
            })
        save_testset(f'{dataset_short}_ours_{mode_name}', out_samples)

    # LightRAG naive / hybrid
    for mode_name, lr_data in [('lightrag_naive', lr_naive_data), ('lightrag_hybrid', lr_hybrid_data)]:
        out_samples = []
        for i, s in enumerate(samples):
            ld = lr_data[i]
            out_samples.append({
                'question': s['question'],
                'answer': ld['answer'],
                'contexts': ld['contexts'],
                'ground_truth': s.get('ground_truth', ''),
                'status': 'approved',
                'metadata': {
                    'kb_id': kb_id,
                    'source': 'lightrag',
                    'mode': mode_name,
                    'dataset': dataset_short,
                    'qid': s.get('metadata', {}).get('qid', str(i)),
                    'tags': s.get('metadata', {}).get('tags', []),
                }
            })
        save_testset(f'{dataset_short}_{mode_name}', out_samples)

# ── 主流程：接受 dataset 参数 ──
# 用法：python fill_c2.py crud       # 只跑 CRUD-RAG（KB 65）
#       python fill_c2.py nfcorpus   # 只跑 NFCorpus（KB 66/67）
#       python fill_c2.py            # 两个都跑
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

if mode in ('crud', 'all'):
    # 查 KB id
    crud_kb_id = 65
    crud_map_path = os.path.join(THIS, 'kb_map_crud.json')
    if os.path.exists(crud_map_path):
        with open(crud_map_path, encoding='utf-8') as f:
            crud_kb_id = json.load(f).get('kb_id', 65)
    fill_dataset('crud', 'crud_rag_300', crud_kb_id)

if mode in ('nfcorpus', 'all'):
    nf_kb_id = 66
    nf_map_path = os.path.join(THIS, 'kb_map_nfcorpus.json')
    if os.path.exists(nf_map_path):
        with open(nf_map_path, encoding='utf-8') as f:
            nf_kb_id = json.load(f).get('kb_id', 66)
    fill_dataset('nfcorpus', 'nfcorpus_100', nf_kb_id)

print('\n=== fill done ===')
