"""C 轮2 两端开工：qwen3.8-flash 从 doc 699 往前抽 entity
- GLM-4-FlashX 继续从 [640] 往后（backend build_nonrel_async.py 在跑）
- qwen3.8-flash 从 699 往前，两端相遇

流程（绕过 backend generate，直接调 DashScope API）：
  1. backend /api/upload/markdown + /api/process/split（拿 file_id + chunk_ids）
  2. 对每个 chunk 调 qwen3.8-flash 用 ENTITY_TEMPLATE 抽 entity + relation
  3. 直接写 PG entity + entity_relation（复用 backend Database 模块）
  4. backend /api/process/import（自动调 _sync_entity_vectors 同步 entity 向量 + chunk 向量）

控制变量：与 backend 一致（切块 1000 + dim 1536 + 同一 ENTITY_TEMPLATE）
"""
import os, sys, json, time, asyncio, aiohttp, threading, requests, openai
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from services.database import Database
from services.enhancers.entity import ENTITY_TEMPLATE, _parse_extraction

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))
CORPUS_PATH = os.path.join(THIS, 'corpus', 'crud_corpus_1000.json')
KB_ID = 65
PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'

# DashScope qwen3.8-flash
DASHSCOPE_KEY = os.getenv('DASHSCOPE_API_KEY', '')
DASHSCOPE_BASE = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
LLM_MODEL = 'qwen3.8-flash'
llm_client = openai.OpenAI(api_key=DASHSCOPE_KEY, base_url=DASHSCOPE_BASE)
print(f'LLM: {LLM_MODEL} base={DASHSCOPE_BASE} key={DASHSCOPE_KEY[:8]}...')

# backend token 管理
_token_lock = threading.Lock()
_token_state = {'token': None, 'login_at': 0}

def _do_login_sync():
    r = requests.post(f'{B}/api/auth/login',
        data={'username': 'loadtester', 'password': 'Loadtest#123'},
        timeout=30)
    r.raise_for_status()
    return r.json()['access_token']

def get_token_sync(force=False):
    with _token_lock:
        now = time.time()
        if force or _token_state['token'] is None or now - _token_state['login_at'] > 50*60:
            _token_state['token'] = _do_login_sync()
            _token_state['login_at'] = now
            print(f'[token] refreshed at {time.strftime("%H:%M:%S")}')
        return _token_state['token']

print(f'login ok, token={get_token_sync()[:20]}...')

# PG + Database 模块（Database() 无参数，从 config 读 PG 配置）
db = Database()

# 加载 corpus + 取 non-rel docs
with open(CORPUS_PATH, encoding='utf-8') as f:
    corpus = json.load(f)
nonrel_docs = [d for d in corpus if not d.get('metadata', {}).get('is_relevant')]
print(f'corpus non-rel docs: {len(nonrel_docs)}')

# 查已抽取 entity 的 chunk_ids（PG entity.source_chunk_ids）
# build 的 upload+split 已把所有 700 docs 的 chunk 写入 PG
# 但 entity 抽取（generate）可能 fail——这些 docs 有 chunk 但没 entity
# qwen 脚本只处理"没 entity"的 docs
existing_chunk_ids_with_entity = set()
try:
    conn = __import__('psycopg2').connect(PG_DSN)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT jsonb_array_elements_text(source_chunk_ids::jsonb) "
        "FROM entity WHERE kb_id=%s", (KB_ID,))
    for r in cur.fetchall():
        if r[0]:
            existing_chunk_ids_with_entity.add(int(r[0]))
    cur.close()
    conn.close()
    print(f'chunks with entity: {len(existing_chunk_ids_with_entity)}')
except Exception as e:
    print(f'PG err: {e}')

# 过滤 todo docs：doc 的 chunk_ids 是否都已有 entity
# 如果 doc 的所有 chunk 都有 entity，跳过；否则处理
import psycopg2 as _psycopg2
def doc_has_entity(doc_id):
    """查 doc 的 chunk_ids 是否都已有 entity。返回 True=已抽取，跳过"""
    try:
        conn = _psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        # doc 的 filename = doc_id + '.md'，查 document_chunk
        cur.execute(
            "SELECT id FROM document_chunk WHERE knowledge_base_id=%s "
            "AND metadata->>'source'=%s", (KB_ID, f"{doc_id}.md"))
        chunk_ids = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
        if not chunk_ids:
            return False  # 没 chunk，需要处理（upload+split）
        # 检查是否所有 chunk 都有 entity
        has_entity = all(cid in existing_chunk_ids_with_entity for cid in chunk_ids)
        return has_entity
    except Exception:
        return False

# 从 699 往前过滤 todo docs（没有 entity 的）
todo_docs = [d for d in reversed(nonrel_docs) if not doc_has_entity(d['id'])]
# 支持 --limit 参数做 smoke test
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 0
if LIMIT > 0:
    todo_docs = todo_docs[:LIMIT]
print(f'todo docs (no entity, reverse from 699): {len(todo_docs)}')

# ── LLM 抽 entity（同步，qwen3.8-flash）──
def extract_entities_qwen(chunk_text):
    """调 qwen3.8-flash 抽 entity + relation，返回 {entities, relations}"""
    prompt = ENTITY_TEMPLATE.format(document_text=chunk_text[:3000])
    for attempt in range(3):
        try:
            resp = llm_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0,
                max_tokens=1000,
            )
            raw = resp.choices[0].message.content
            return _parse_extraction(raw)
        except Exception as e:
            err_str = str(e).lower()
            print(f'  LLM err attempt {attempt+1}: {str(e)[:120]}')
            if '429' in err_str or 'rate' in err_str:
                print('  [429] sleeping 30s')
                time.sleep(30)
            elif 'timeout' in err_str:
                time.sleep(5)
            else:
                break
    return {'entities': [], 'relations': []}

# ── 单 doc 处理 ──
def process_doc(doc):
    """处理单 doc：如果已有 chunk 直接抽 entity，否则 upload+split+抽 entity+import"""
    doc_id = doc['id']
    text = doc.get('text', '')
    title = doc.get('title', '')
    content = f'# {title}\n\n{text}'
    fname = f'{doc_id}.md'

    try:
        token = get_token_sync()
        headers = {'Authorization': f'Bearer {token}'}

        # 先查 PG 是否已有 chunk（build 已 upload+split）
        conn = _psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, content FROM document_chunk WHERE knowledge_base_id=%s "
            "AND metadata->>'source'=%s ORDER BY chunk_index", (KB_ID, fname))
        chunks = cur.fetchall()
        cur.close()
        conn.close()

        if chunks:
            # 已有 chunk（build upload+split 了），直接抽 entity
            file_id = None  # 不需要 file_id，因为不调 import
        else:
            # 没 chunk，走 upload+split
            files = {'file': (fname, content.encode('utf-8'), 'text/markdown')}
            data = {'kb_id': str(KB_ID)}
            r = requests.post(f'{B}/api/upload/markdown',
                files=files, data=data, headers=headers, timeout=60)
            if r.status_code == 401:
                token = get_token_sync(force=True)
                headers = {'Authorization': f'Bearer {token}'}
                r = requests.post(f'{B}/api/upload/markdown',
                    files=files, data=data, headers=headers, timeout=60)
            if r.status_code != 200:
                return (doc_id, None, 'upload_fail', f'{r.status_code} {r.text[:120]}')
            file_id = r.json().get('file_id')

            r1 = requests.post(f'{B}/api/process/split/{file_id}',
                headers=headers, timeout=120)
            if r1.status_code != 200:
                return (doc_id, file_id, 'split_fail', f'{r1.status_code} {r1.text[:200]}')

            # 查 split 后的 chunks
            conn = _psycopg2.connect(PG_DSN)
            cur = conn.cursor()
            cur.execute(
                "SELECT id, content FROM document_chunk WHERE document_id=%s ORDER BY chunk_index",
                (file_id,))
            chunks = cur.fetchall()
            cur.close()
            conn.close()

            if not chunks:
                return (doc_id, file_id, 'no_chunks', 'split produced 0 chunks')

        # 对每个 chunk 调 qwen3.8-flash 抽 entity + 写 PG
        entity_name_to_id = {}
        ent_count = 0
        rel_count = 0
        for chunk_id, chunk_text in chunks:
            result = extract_entities_qwen(chunk_text)
            entities = result.get('entities', [])
            relations = result.get('relations', [])

            for ent in entities:
                name = ent.get('name', '').strip()
                if not name:
                    continue
                eid = db.upsert_entity(KB_ID, name,
                    entity_type=ent.get('type', '概念'),
                    description=ent.get('description', ''),
                    chunk_id=chunk_id)
                if eid:
                    entity_name_to_id[name] = eid
                    ent_count += 1

            for rel in relations:
                head = rel.get('head', '').strip()
                tail = rel.get('tail', '').strip()
                rt = rel.get('relation', '').strip()
                if not head or not tail or not rt:
                    continue
                head_id = entity_name_to_id.get(head) or db.upsert_entity(KB_ID, head, chunk_id=chunk_id)
                tail_id = entity_name_to_id.get(tail) or db.upsert_entity(KB_ID, tail, chunk_id=chunk_id)
                if head_id and tail_id:
                    db.add_entity_relation(KB_ID, head_id, rt, tail_id,
                        evidence=rel.get('evidence', ''), source_chunk_id=chunk_id)
                    rel_count += 1

        # 如果是新 upload 的 doc，调 import 同步 entity 向量 + chunk 向量
        # 如果是已有 chunk 的 doc，只同步 entity 向量（调 import 会重复写 chunk 向量）
        # 这里统一调 import（backend 有幂等：已 completed 的 doc 直接返回）
        if file_id:
            r3 = requests.post(f'{B}/api/process/import/{file_id}',
                headers=headers, timeout=300)
            if r3.status_code != 200:
                return (doc_id, file_id, 'import_fail', f'{r3.status_code} {r3.text[:200]}')

        return (doc_id, file_id, 'ok', f'ent={ent_count} rel={rel_count} chunks={len(chunks)}')

    except Exception as e:
        return (doc_id, None, 'exc', str(e)[:200])

# ── 主流程（顺序跑，qwen3.8-flash 无 QPM 限制）──
if __name__ == '__main__':
    t0 = time.time()
    ok, fail = 0, 0
    for i, doc in enumerate(todo_docs):
        result = process_doc(doc)
        doc_id, file_id, status, msg = result
        if status == 'ok':
            ok += 1
        else:
            fail += 1
        elapsed = time.time() - t0
        done = ok + fail
        rate = done / elapsed if elapsed > 0 else 0
        eta = (len(todo_docs) - done) / rate if rate > 0 else 0
        print(f'  [{done}/{len(todo_docs)}] {doc_id} {status} {msg} | ok={ok} fail={fail} elapsed={elapsed:.0f}s rate={rate:.2f}/s eta={eta:.0f}s', flush=True)

    print(f'\n=== qwen3.8-flash done: ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s ===')
