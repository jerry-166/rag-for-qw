import os, psycopg2
from dotenv import load_dotenv
load_dotenv('backend/.env')
conn = psycopg2.connect(host=os.getenv('POSTGRES_HOST'), port=os.getenv('POSTGRES_PORT'), user=os.getenv('POSTGRES_USER'), password=os.getenv('POSTGRES_PASSWORD'), dbname=os.getenv('POSTGRES_DB'))
cur = conn.cursor()
cur.execute("select id, filename, status, split_time, generate_time, import_time, processing_time, created_at from document order by id")
for r in cur.fetchall(): print('doc:', r)
print('--- workflow_log ---')
cur.execute("select document_id, operation, status, processing_time, created_at from workflow_log order by created_at")
for r in cur.fetchall(): print(r)
print('--- counts ---')
for t in ('document_chunk','sub_question','chunk_summary'):
    cur.execute(f'select count(*) from {t}'); print(t, cur.fetchone()[0])
