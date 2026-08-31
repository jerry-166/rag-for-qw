"""场景3 审计对账（修正版）：正确列名 occurred_at；窗口按结果文件 mtime 反推。"""
import sys, os, json, datetime
sys.path.insert(0, r'd:\workspace\rag-for-qw\backend')
from dotenv import load_dotenv
load_dotenv(r'd:\workspace\rag-for-qw\backend\.env')
from services.database import db

f = r'd:\workspace\rag-for-qw\work\stage-4\loadtest-reattack\scenario3_result.json'
end = datetime.datetime.fromtimestamp(os.path.getmtime(f))
start = end - datetime.timedelta(seconds=340)  # 50 ops wall=320s + 缓冲
rows = db.fetchall(
    "select action, count(*) c from audit_log where occurred_at>=%s and occurred_at<=%s+interval '30 s' "
    "and user_id=(select id from users where username='loadtester') group by action order by 2 desc",
    (start, end))
recon = {r['action']: r['c'] for r in rows}
print('audit by action (loadtester, window):', recon)
lag = db.fetchone(
    "select max(extract(epoch from %s-occurred_at)) lag from audit_log where occurred_at>=%s",
    (datetime.datetime.now(), start))
print('max flush lag s:', lag['lag'] if lag else None)
json.dump({'audit_by_action': recon, 'max_flush_lag_s': lag['lag'] if lag else None,
           'window': [str(start), str(end)]},
          open(r'd:\workspace\rag-for-qw\work\stage-4\loadtest-reattack\scenario3_audit_recon_fixed.json', 'w'),
          ensure_ascii=False, indent=1)
print('RECON SAVED')
