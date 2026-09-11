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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
# C 轮2 只测 graph vs native（去掉 advanced/hybrid_vec/keyword）
_ALL_MODES = [
    ('native_rerank_off', 'milvus/query', {'retrieval_mode': 'native', 'use_rerank': False}),
    ('native_rerank_on',  'milvus/query', {'retrieval_mode': 'native', 'use_rerank': True}),
    ('graph',            'milvus/query', {'retrieval_mode': 'graph', 'use_rerank': True}),
]
# 支持模式选择：python fill_c2.py crud native（只跑 native）| graph（只跑 graph）| all（全 3 个）
_mode_filter = sys.argv[2] if len(sys.argv) > 2 else 'all'
if _mode_filter == 'native':
    OURS_MODES = [m for m in _ALL_MODES if m[0].startswith('native')]
elif _mode_filter == 'graph':
    OURS_MODES = [m for m in _ALL_MODES if m[0] == 'graph']
else:
    OURS_MODES = _ALL_MODES
print(f'modes: {[m[0] for m in OURS_MODES]}')

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
        # agent/chat 返回的 response 可能是 dict（{'content': '...'}），统一转成 str
        if isinstance(answer, dict):
            answer = answer.get('content', '') or answer.get('response', '') or str(answer)
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
            headers=H(), timeout=120)
        if r.status_code == 401:
            get_token(force=True)
            r = requests.post(f'{B}/api/{endpoint}',
                json={'query': question, 'limit': 10, 'knowledge_base_id': kb_id, **extra},
                headers=H(), timeout=120)
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

    # ── Step 1: 生成共享 answer（ours 模式共享，8 并发）──
    print('\n[Step 1] 生成 ours 共享 answer (3 并发)')
    shared_answers = [None] * len(samples)
    t0 = time.time()

    def _fetch_answer(args):
        i, s, _kb_id = args
        q = s['question']
        ans, ctx, msg = get_shared_answer(q, _kb_id)
        return i, {'answer': ans, 'contexts': ctx, 'msg': msg}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_fetch_answer, (i, s, kb_id)) for i, s in enumerate(samples)]
        done = 0
        for future in as_completed(futures):
            i, result = future.result()
            shared_answers[i] = result
            done += 1
            if done % 20 == 0 or done == len(samples):
                ok_ours = sum(1 for x in shared_answers if x and x['answer'])
                print(f'  [{done}/{len(samples)}] elapsed={time.time()-t0:.0f}s ours_ans={ok_ours}')

    # ── Step 2: ours 模式每模式独立检索 contexts（8 并发）──
    print('\n[Step 2] ours 模式独立检索 contexts (3 并发)')
    ours_contexts = {m[0]: [None] * len(samples) for m in OURS_MODES}

    def _fetch_contexts(args):
        i, s, mode_name, endpoint, extra, _kb_id = args
        q = s['question']
        ctx, msg = get_ours_contexts(q, mode_name, endpoint, extra, _kb_id)
        return mode_name, i, {'contexts': ctx, 'msg': msg}

    for mode_name, endpoint, extra in OURS_MODES:
        print(f'  [mode] {mode_name}')
        t1 = time.time()
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(_fetch_contexts, (i, s, mode_name, endpoint, extra, kb_id))
                       for i, s in enumerate(samples)]
            done = 0
            for future in as_completed(futures):
                _mode, i, result = future.result()
                ours_contexts[_mode][i] = result
                done += 1
                if done % 50 == 0 or done == len(samples):
                    ok = sum(1 for x in ours_contexts[_mode] if x and x['contexts'])
                    print(f'    [{done}/{len(samples)}] ok={ok} elapsed={time.time()-t1:.0f}s')
        ok = sum(1 for x in ours_contexts[mode_name] if x and x['contexts'])
        print(f'  {mode_name} done: ok={ok}/{len(samples)} elapsed={time.time()-t1:.0f}s')

    # ── Step 3: 组装 6 个 testset（ours 6 模式，不包含 LightRAG） ──
    print('\n[Step 3] 组装 testsets')
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

# ── 主流程：C 轮2 只做 CRUD-RAG（不做 NFCorpus + LightRAG） ──
mode = sys.argv[1] if len(sys.argv) > 1 else 'crud'

if mode in ('crud', 'all'):
    crud_kb_id = 65
    crud_map_path = os.path.join(THIS, 'kb_map_crud.json')
    if os.path.exists(crud_map_path):
        with open(crud_map_path, encoding='utf-8') as f:
            crud_kb_id = json.load(f).get('kb_id', 65)
    fill_dataset('crud', 'crud_rag_300', crud_kb_id)

print('\n=== fill done ===')
