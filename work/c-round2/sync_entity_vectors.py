"""同步 KB 65 的 entity 向量到 Milvus entities_collection
- build 的 46 fail docs（import timeout）有 entity 但没 Milvus 向量
- qwen 的 18 docs 有 entity（PG）但没调 import
- 这个脚本补同步所有 entity 的 description embedding 到 Milvus

复用 backend 的 milvus_client.upsert_entity_vector
"""
import os, sys, asyncio, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from services.database import Database
from services.milvus_client import MilvusClient
from services.document_processor import DocumentProcessor

db = Database()
mc = MilvusClient()
dp = DocumentProcessor()
print(f'Database + MilvusClient + DocumentProcessor initialized')

KB_ID = 65

# 查所有 entity
entities = db.get_kb_entities(KB_ID, limit=5000)
print(f'KB{KB_ID} entities: {len(entities)}')

# 生成 description embedding + upsert 到 Milvus
texts = [f"{e['name']}：{e.get('description') or ''}" for e in entities]
# 生成 description embedding（DashScope batch size 限制 10，分批处理）
import openai
DASHSCOPE_KEY = os.getenv('DASHSCOPE_API_KEY', '')
DASHSCOPE_BASE = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
embed_client = openai.OpenAI(api_key=DASHSCOPE_KEY, base_url=DASHSCOPE_BASE)

def embed_batch(texts, batch_size=10):
    """分批生成 embedding（DashScope 限制 batch<=10）"""
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        try:
            resp = embed_client.embeddings.create(
                model='text-embedding-v4',
                input=batch,
                dimensions=1536,
            )
            all_vecs.extend([d.embedding for d in resp.data])
        except Exception as e:
            print(f'  batch {i//batch_size} err: {str(e)[:120]}')
            all_vecs.extend([None] * len(batch))
        if (i // batch_size) % 20 == 0 and i > 0:
            print(f'  embedded {i}/{len(texts)}')
    return all_vecs

print(f'generating embeddings for {len(texts)} entities (batch=10)...')
t0 = time.time()
vectors = embed_batch(texts)
print(f'embeddings done: {len(vectors)} in {time.time()-t0:.1f}s')

# 批量同步到 Milvus（delete 全部 + 批量 insert + 一次 flush）
# 逐个 upsert 会被 Zilliz RateLimiter 卡死（每次 delete+insert+flush 限流）
# 批量模式：1 次 delete + N 批 insert + 1 次 flush
print(f'\nbatch upsert to Milvus (delete all + batch insert + single flush)...')
t1 = time.time()

col = mc.entities_collection
if col is None:
    if not mc.create_collections():
        raise RuntimeError('Milvus collections create failed')
    col = mc.entities_collection

try:
    col.load()
except Exception:
    pass

# 1. delete KB 65 全部 entity 向量（幂等，重跑安全）
try:
    col.delete(expr=f'kb_id == {KB_ID}')
    print(f'  deleted all KB{KB_ID} entity vectors')
except Exception as e:
    print(f'  delete err (may be empty): {str(e)[:100]}')

# 2. 批量 insert（过滤 embedding 失败的 None）
import time as _time
rows = [(e, v) for e, v in zip(entities, vectors) if v is not None]
print(f'  inserting {len(rows)}/{len(entities)} entities (skip None vectors)...')

BATCH = 200
inserted = 0
for i in range(0, len(rows), BATCH):
    batch = rows[i:i+BATCH]
    try:
        col.insert([
            [e['id'] for e, _ in batch],                    # pg_entity_id
            [KB_ID] * len(batch),                           # kb_id
            [e['name'][:500] for e, _ in batch],            # name
            [(e.get('description') or '')[:2000] for e, _ in batch],  # description
            [v for _, v in batch],                          # description_vector
            [int(_time.time() * 1000)] * len(batch),        # created_at
        ])
        inserted += len(batch)
        print(f'  inserted {inserted}/{len(rows)}')
    except Exception as e:
        print(f'  batch {i//BATCH} insert err: {str(e)[:120]}')

# 3. 一次 flush
try:
    col.flush()
    print(f'  flushed')
except Exception as e:
    print(f'  flush err: {str(e)[:120]}')

print(f'\n=== done: inserted {inserted}/{len(entities)} entity vectors in {time.time()-t1:.1f}s ===')
