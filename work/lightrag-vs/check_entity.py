"""查 KB17 entity 数据（PG，正确列名 kb_id）。"""
import sys, os
sys.path.insert(0, os.path.abspath('backend'))
os.chdir('backend')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from services.database import db

kb = db.fetchone("SELECT id, enhancers, chunk_strategy FROM knowledge_base WHERE id = %s", (17,))
print(f"KB17: enhancers={kb.get('enhancers') if kb else '?'} chunk_strategy={kb.get('chunk_strategy') if kb else '?'}")

cnt = db.fetchone("SELECT count(*) as c FROM entity WHERE kb_id = %s", (17,))
print(f"KB17 PG entities: {cnt['c'] if cnt else 0}")
entities = db.fetchall("SELECT id, name, type FROM entity WHERE kb_id = %s LIMIT 5", (17,))
for e in entities:
    print(f"  entity {e['id']}: {e['name'][:50]} (type={e.get('type')})")

rels = db.fetchone("SELECT count(*) as c FROM entity_relation WHERE kb_id = %s", (17,))
print(f"KB17 entity_relations: {rels['c'] if rels else 0}")

# 看其他 KB 有没有 entity 数据（对比）
others = db.fetchall("SELECT kb_id, count(*) as c FROM entity GROUP BY kb_id ORDER BY c DESC LIMIT 5")
print(f"其他 KB entity 分布: {[(o['kb_id'], o['c']) for o in others]}")
