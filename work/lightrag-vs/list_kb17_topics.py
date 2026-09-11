"""查 KB17 docs 主题列表，用于生成匹配的 query。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
from services.database import Database

db = Database()
rows = db.fetchall("SELECT id, filename, metadata FROM document WHERE knowledge_base_id=17 ORDER BY id LIMIT 200")
print(f'KB17 docs: {len(rows)}')
topics = set()
for r in rows:
    fname = r['filename']
    meta = r['metadata'] if isinstance(r['metadata'], dict) else {}
    topic = meta.get('topic') or meta.get('title') or fname
    topics.add(topic)
print(f'topics: {len(topics)}')
for t in sorted(topics):
    print(f'  {t}')
