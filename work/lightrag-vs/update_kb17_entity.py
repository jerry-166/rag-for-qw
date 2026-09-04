"""改 KB17 enhancers 加 entity + 拿 file_id 列表（psycopg2 直连，避免 db 模块方法不确定）。"""
import sys, os
sys.path.insert(0, os.path.abspath('backend'))
os.chdir('backend')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from config import settings
import psycopg2, json

conn = psycopg2.connect(host=settings.POSTGRES_HOST, port=settings.POSTGRES_PORT,
                        user=settings.POSTGRES_USER, password=settings.POSTGRES_PASSWORD, dbname=settings.POSTGRES_DB)
cur = conn.cursor()
cur.execute("UPDATE knowledge_base SET enhancers = %s WHERE id = %s", ('["entity"]', 17))
conn.commit()
cur.execute("SELECT id, enhancers, chunk_strategy FROM knowledge_base WHERE id = %s", (17,))
print(f"KB17 updated: {cur.fetchone()}")

cur.execute("SELECT file_id, filename FROM document WHERE knowledge_base_id = %s ORDER BY file_id", (17,))
rows = cur.fetchall()
file_ids = [r[0] for r in rows]
print(f"KB17 docs: {len(file_ids)}, file_ids[:5]: {file_ids[:5]}, ... last: {file_ids[-3:]}")
json.dump(file_ids, open('work/lightrag-vs/kb17_file_ids.json', 'w'))
print(f"saved work/lightrag-vs/kb17_file_ids.json")
conn.close()
