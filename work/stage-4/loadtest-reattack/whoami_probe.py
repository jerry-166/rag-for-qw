import sys
sys.path.insert(0, r'd:\workspace\rag-for-qw\backend')
from dotenv import load_dotenv
load_dotenv(r'd:\workspace\rag-for-qw\backend\.env')
from services.database import db

u = db.fetchall("select id, username, role from users order by id")
print('users:')
for r in u: print(' ', r['id'], r['username'], r['role'])

kb = db.fetchall("select id, kb_name, user_id from knowledge_base where id in (17,18) order by id")
print('KB17/18:')
for r in kb: print(' ', r['id'], repr(r['kb_name']), 'owner_user_id=', r['user_id'])

# 可见性：loadtester 的 KB 是否私有（无 user_kb_permission 记录）
p = db.fetchall("select kb_id, user_id from user_kb_permission order by kb_id")
print('shares:', p)
