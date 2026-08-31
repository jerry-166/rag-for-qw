import sys, datetime
sys.path.insert(0, r'd:\workspace\rag-for-qw\backend')
from dotenv import load_dotenv
load_dotenv(r'd:\workspace\rag-for-qw\backend\.env')
from services.database import db
rows = db.fetchall("select action, user_id, count(*) c from audit_log where occurred_at > now() - interval '2 hours' and action like 'faq.%' group by action, user_id order by 3 desc")
for r in rows: print(r['action'], 'user_id=', r['user_id'], 'count=', r['c'])
