"""查 KB17 Milvus 索引状态（chunks 数 + 是否有数据）。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
from config import settings
from pymilvus import connections, Collection, utility

uri = settings.MILVUS_URI
db = getattr(settings, 'MILVUS_DB_NAME', None) or 'rag_system'
print(f'MILVUS_URI: {uri[:50]}..., db: {db}')
connections.connect(uri=uri, db_name=db)

for name in ['chunk_vectors', 'chunk_summaries', 'chunk_subquestions', 'entities_collection', 'faq_collection']:
    if utility.has_collection(name):
        c = Collection(name)
        try:
            c.load()
            print(f'{name}: {c.num_entities} entities')
        except Exception as e:
            print(f'{name}: err {str(e)[:80]}')
    else:
        print(f'{name}: NOT EXIST')

# 查 KB17 chunks（如果 chunk_vectors 有 kb_id 字段）
try:
    c = Collection('chunk_vectors')
    c.load()
    # 查 KB17 几条
    res = c.query(expr='knowledge_base_id == 17', output_fields=['chunk_id', 'knowledge_base_id'], limit=3)
    print(f'KB17 chunks sample: {len(res)}')
    for r in res[:3]:
        print(' ', r)
except Exception as e:
    print(f'KB17 query err: {str(e)[:120]}')
