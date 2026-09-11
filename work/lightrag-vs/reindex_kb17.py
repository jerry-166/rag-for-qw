"""重建 KB17 milvus chunk_vectors 索引（text-embedding-v4 dim=1536）。

背景：旧索引由 github_copilot/text-embedding-ada-002（1536 dim）建立，
切换到 DashScope text-embedding-v4 后向量空间不匹配，cosine 低被 RETRIEVAL_MIN_SCORE=0.3 过滤。
现切到 text-embedding-v4(1536 dim) 重 embed + 重 insert，使查询向量与索引向量同模型。

步骤：
1. 删 milvus chunk_vectors 中 KB17 的 chunks（expr='knowledge_base_id == 17'）
2. 从 PG 查 KB17 chunks（document_chunk 表 knowledge_base_id=17）
3. text-embedding-v4 重 embedding（batch 32）
4. milvus insert（chunks_collection.insert，字段顺序对齐 schema）
5. flush

注意：KB17 chunks 数量可能上千，embedding 走 DashScope 远程 HTTP，分批 + 进度打印。
"""
import os, sys, time, asyncio, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from services.milvus_client import MilvusClient
from services.database import Database
from services.document_processor import DocumentProcessor

KB_ID = 17
BATCH = 8  # DashScope text-embedding-v4 batch 上限 10，留余量用 8


def main():
    # 初始化
    mc = MilvusClient()
    mc.create_collections()
    db = Database()
    dp = DocumentProcessor()

    chunks_coll = mc.chunks_collection
    if not chunks_coll:
        print('[fatal] chunks_collection 未初始化', flush=True)
        return

    # 1. 删 KB17 旧向量
    print(f'[1/4] 删除 milvus chunk_vectors 中 KB17 的旧向量 ...', flush=True)
    chunks_coll.delete(expr=f'knowledge_base_id == {KB_ID}')
    chunks_coll.flush()
    print(f'      delete done', flush=True)

    # 2. 查 PG KB17 chunks
    print(f'[2/4] 从 PG 查 KB17 chunks ...', flush=True)
    rows = db.fetchall(
        "SELECT id, document_id, knowledge_base_id, chunk_index, content, metadata "
        "FROM document_chunk WHERE knowledge_base_id = %s ORDER BY id",
        (KB_ID,))
    print(f'      PG chunks: {len(rows)}', flush=True)
    if not rows:
        print('[fatal] KB17 无 chunks', flush=True)
        return

    # 3. 分批 embedding + insert
    print(f'[3/4] text-embedding-v4 重 embedding + insert (batch={BATCH}) ...', flush=True)
    total_start = time.time()
    inserted = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        texts = [r['content'] for r in batch]
        # embed（同步调用 aembed_documents）
        try:
            embeddings = asyncio.run(dp.EmbeddingModel.aembed_documents(texts, chunk_size=8))
        except Exception as e:
            print(f'  [{i+1}-{i+len(batch)}] embed err: {str(e)[:80]}', flush=True)
            continue
        if len(embeddings) != len(batch):
            print(f'  [{i+1}] embed count mismatch: {len(embeddings)} vs {len(batch)}', flush=True)
            continue

        # 组装 insert 数据（字段顺序对齐 schema: pg_chunk_id, document_id, knowledge_base_id, chunk_index, chunk_text, chunk_vector, created_at, metadata）
        ts = int(time.time())
        pg_ids = [int(r['id']) for r in batch]
        doc_ids = [int(r['document_id']) for r in batch]
        kb_ids = [KB_ID] * len(batch)
        indices = [int(r['chunk_index']) for r in batch]
        chunks_texts = [t[:65535] for t in texts]
        chunks_vectors = list(embeddings)
        chunks_ts = [ts] * len(batch)
        chunks_meta = [r['metadata'] if isinstance(r['metadata'], dict) else json.loads(r['metadata'] or '{}') for r in batch]

        try:
            chunks_coll.insert([
                pg_ids, doc_ids, kb_ids,
                indices, chunks_texts, chunks_vectors,
                chunks_ts, chunks_meta,
            ])
            inserted += len(batch)
            if (i // BATCH) % 5 == 0 or i + BATCH >= len(rows):
                print(f'  [{i+1}-{i+len(batch)}/{len(rows)}] inserted={inserted} elapsed={time.time()-total_start:.1f}s', flush=True)
        except Exception as e:
            print(f'  [{i+1}-{i+len(batch)}] insert err: {str(e)[:80]}', flush=True)

    # 4. flush
    print(f'[4/4] flush ...', flush=True)
    chunks_coll.flush()
    print(f'\n[done] inserted={inserted}/{len(rows)}, total {time.time()-total_start:.1f}s', flush=True)
    print(f'      num_entities now: {chunks_coll.num_entities}', flush=True)


if __name__ == '__main__':
    main()
