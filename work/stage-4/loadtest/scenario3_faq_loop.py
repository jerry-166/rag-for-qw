"""Stage4 圈2 场景3：自进化 FAQ 闭环连续运行（50 轮 supplement/hit/promote 混合）+ 审计对账
轮次组成（私有 KB=17）：30 轮 supplement（去重阈值内命中会返回 hit/promote，均计成功）+ 10 轮重复 supplement（应命中去重/命中路径）+ 10 轮 demote/delete 轮换。
记录每轮 action/成功/耗时，最后与 audit_log 对账。
"""
import requests, json, time, random
B='http://localhost:8003'
def login():
    return requests.post(B+'/api/auth/login',data={'username':'loadtester','password':'Loadtest#123'})
tok=None
def H():
    global tok
    if tok is None: tok=login().json()['access_token']
    return {'Authorization':f'Bearer {tok}'}
def call(method,path,**kw):
    t0=time.perf_counter()
    try:
        r=getattr(requests,method)(B+path,headers=H(),timeout=120,**kw)
        dt=(time.perf_counter()-t0)*1000
        try: j=r.json()
        except: j={}
        if r.status_code==401:  # token 过期重登
            tok=login().json()['access_token']
            r=getattr(requests,method)(B+path,headers=H(),timeout=120,**kw); j=r.json()
        return {'code':r.status_code,'ok':r.status_code<400,'ms':round(dt),'resp':j}
    except Exception as e:
        return {'code':-1,'ok':False,'ms':round((time.perf_counter()-t0)*1000),'err':str(e)[:100]}

random.seed(7)
log=[]; faq_ids=[]
t_start=time.time()
for i in range(30):
    q=f"压测闭环问题：{random.choice(['向量检索','重排序','切片策略','嵌入模型','多路召回'])}的第{i}种优化手段是什么"
    a=f"压测闭环答案{i}：通过实测数据驱动调优，关注吞吐/延迟分位/错误率三类指标。"
    r=call('post','/api/faq/supplement',json={'question':q,'answer':a,'kb_id':17})
    act=r['resp'].get('action','?') if isinstance(r['resp'],dict) else '?'
    if isinstance(r['resp'],dict) and r['resp'].get('faq_id'): faq_ids.append(r['resp']['faq_id'])
    log.append({'round':i,'op':'supplement_new','action':act,**{k:v for k,v in r.items() if k!='resp'}})
    if (i+1)%10==0: print(f"supplement {i+1}/30 done, actions so far ok={sum(1 for x in log if x['ok'])}",flush=True)
# 重复 supplement（命中已有 FAQ 应复用/计数）
for i in range(10):
    q=f"压测闭环问题：向量检索的第{i}种优化手段是什么"
    r=call('post','/api/faq/supplement',json={'question':q,'answer':f"重复答案{i}",'kb_id':17})
    act=r['resp'].get('action','?') if isinstance(r['resp'],dict) else '?'
    if isinstance(r['resp'],dict) and r['resp'].get('faq_id'): faq_ids.append(r['resp']['faq_id'])
    log.append({'round':30+i,'op':'supplement_dup','action':act,**{k:v for k,v in r.items() if k!='resp'}})
# demote/delete 10 轮
for i in range(10):
    if faq_ids:
        fid=random.choice(faq_ids)
        op='demote' if i%2==0 else 'delete'
        r=call('post',f'/api/faq/{fid}/{op}')
        log.append({'round':40+i,'op':op,'faq_id':fid,**{k:v for k,v in r.items() if k!='resp'}})
    else:
        log.append({'round':40+i,'op':'noop_no_faq','ok':True,'code':0,'ms':0})
wall=time.time()-t_start
print(f"total {len(log)} ops wall={wall:.0f}s ok={sum(1 for x in log if x['ok'])}",flush=True)
json.dump(log,open('scenario3_result.json','w'),ensure_ascii=False,indent=1)

# ---- audit 对账 ----
from services.database import db
import datetime
since=datetime.datetime.fromtimestamp(t_start-5)
rows=db.fetchall("select action,count(*) c from audit_log where created_at>=%s and user_id=(select id from users where username='loadtester') group by action order by 2 desc",(t_start_ := since,))
t_end=datetime.datetime.now()
# 落库延迟：本时段事件的 created_at 与窗口尾差
maxlag=db.fetchone("select max(extract(epoch from %s-created_at)) lag from audit_log where created_at>=%s",(t_end,since))
print('audit by action (loadtester, window):',{r['action']:r['c'] for r in rows})
print('max flush lag s:',dict(maxlag) if maxlag else None)
json.dump({'audit_by_action':{r['action']:r['c'] for r in rows},'max_flush_lag_s':maxlag['lag'] if maxlag else None},
          open('scenario3_audit_recon.json','w'),ensure_ascii=False,indent=1)
