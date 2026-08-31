import sys, os
sys.path.insert(0, r'd:\workspace\rag-for-qw\backend')
from dotenv import load_dotenv
load_dotenv(r'd:\workspace\rag-for-qw\backend\.env')
from services.database import db
# 最近 3 小时全部用户的审计事件分布
rows = db.fetchall("select user_id, action, count(*) c, min(created_at) mn, max(created_at) mx from audit_log where created_at > now() - interval '3 hours' group by user_id, action order by 3 desc limit 20")
for r in rows: print(r)
print('---')
# 时区探针：DB now() vs python now
row = db.fetchone("select now() as db_now")
import datetime
print('db now:', row['db_now'], '| py now:', datetime.datetime.now(), '| py utc:', datetime.datetime.utcnow())
