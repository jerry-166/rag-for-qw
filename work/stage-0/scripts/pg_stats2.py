import os, psycopg2
from dotenv import load_dotenv
load_dotenv('backend/.env')
conn = psycopg2.connect(host=os.getenv('POSTGRES_HOST'), port=os.getenv('POSTGRES_PORT'), user=os.getenv('POSTGRES_USER'), password=os.getenv('POSTGRES_PASSWORD'), dbname=os.getenv('POSTGRES_DB'))
cur = conn.cursor()
cur.execute("select column_name from information_schema.columns where table_name='document'")
print('document cols:', [r[0] for r in cur.fetchall()])
cur.execute("select column_name from information_schema.columns where table_name='workflow_log'")
print('workflow_log cols:', [r[0] for r in cur.fetchall()])
cur.execute("select document_id, count(*) from document_chunk group by 1 order by 2 desc")
for r in cur.fetchall(): print('chunks:', r)
cur.execute("select column_name from information_schema.columns where table_name='sub_question'")
print('sub_question cols:', [r[0] for r in cur.fetchall()])
