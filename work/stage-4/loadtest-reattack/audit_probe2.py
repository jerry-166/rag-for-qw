import sys
sys.path.insert(0, r'd:\workspace\rag-for-qw\backend')
from dotenv import load_dotenv
load_dotenv(r'd:\workspace\rag-for-qw\backend\.env')
from services.database import db
cols = db.fetchall("select column_name, data_type from information_schema.columns where table_name='audit_log' order by ordinal_position")
for c in cols: print(c['column_name'], c['data_type'])
print('---')
rows = db.fetchall("select count(*) c from audit_log")
print('audit_log total rows:', rows[0]['c'])
rows = db.fetchall("select action, count(*) c from audit_log group by action order by 2 desc limit 15")
print('by action:', {r['action']: r['c'] for r in rows})
