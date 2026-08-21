"""场景2b：hybrid_endpoint 重跑（新 token）+ native 慢查询分解对照（use_rerank on/off）"""
import asyncio, json, time, subprocess
import aiohttp, requests
B='http://localhost:8003'; KB=17
def login():
    return requests.post(B+'/api/auth/login',data={'username':'loadtester','password':'Loadtest#123'}).json()['access_token']
QUERIES=["向量数据库的核心原理","如何优化检索延迟","文档切片策略对比","嵌入模型","重排序","多路召回融合","查询改写","RAG评估指标","倒排索引","语义缓存"]
def pctl(xs,p):
    xs=sorted(xs); k=(len(xs)-1)*p/100; f=int(k)
    return round(xs[f] if f+1>=len(xs) else xs[f]+(xs[f+1]-xs[f])*(k-f))
def rss_mb():
    pid=subprocess.run(['powershell','-NoProfile','-Command',
        "(Get-NetTCPConnection -LocalPort 8003 -State Listen).OwningProcess"],capture_output=True,text=True).stdout.strip()
    if not pid: return None
    o=subprocess.run(['powershell','-NoProfile','-Command',
        f"[math]::Round((Get-Process -Id {pid}).WorkingSet64/1MB,1)"],capture_output=True,text=True).stdout.strip()
    return float(o)
async def bench(s,tok,ep,body,n,conc,tag):
    H={'Authorization':f'Bearer {tok}'}; out=[]; sem=asyncio.Semaphore(conc)
    r0=rss_mb()
    async def w(i):
        async with sem:
            t0=time.perf_counter()
            try:
                async with s.post(B+ep,json={**body,'query':QUERIES[i%len(QUERIES)]},headers=H) as r:
                    await r.read(); out.append({'ok':r.status==200,'ms':(time.perf_counter()-t0)*1000,'code':r.status})
            except Exception as e:
                out.append({'ok':False,'ms':(time.perf_counter()-t0)*1000,'code':-1,'err':str(e)[:60]})
    t0=time.perf_counter(); await asyncio.gather(*[w(i) for i in range(n)]); wall=time.perf_counter()-t0
    ok=[o['ms'] for o in out if o['ok']]; bad=[o for o in out if not o['ok']]
    summ={'tag':tag,'n':n,'conc':conc,'wall_s':round(wall,1),'qps':round(n/wall,2),'ok':len(ok),'err':len(bad),
          'p50_ms':pctl(ok,50) if ok else None,'p95_ms':pctl(ok,95) if ok else None,'p99_ms':pctl(ok,99) if ok else None,
          'max_ms':round(max(ok)) if ok else None,'err_codes':{str(b['code']):1 for b in bad},
          'rss_start_mb':r0,'rss_end_mb':rss_mb()}
    print(json.dumps(summ,ensure_ascii=False),flush=True); return {'summary':summ,'detail':out}
async def main():
    res={}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600),connector=aiohttp.TCPConnector(limit=40)) as s:
        tok=login()
        # warmup
        async with s.post(B+'/api/hybrid/search',json={'query':QUERIES[0],'use_rerank':True,'knowledge_base_id':KB,'limit':10},headers={'Authorization':f'Bearer {tok}'}) as r:
            print('warmup hybrid_endpoint',r.status,flush=True)
        res['hybrid_endpoint']=await bench(s,tok,'/api/hybrid/search',{'use_rerank':True,'knowledge_base_id':KB,'limit':10},120,20,'hybrid_endpoint')
        # native 慢查询分解：无 rerank vs 有 rerank（各 8 次串行，避免相互干扰）
        tok2=login()
        res['native_norerank']=await bench(s,tok2,'/api/milvus/query',{'use_rerank':False,'knowledge_base_id':KB,'limit':10,'retrieval_mode':'native'},8,8,'native_norerank')
        tok3=login()
        res['native_rerank']=await bench(s,tok3,'/api/milvus/query',{'use_rerank':True,'knowledge_base_id':KB,'limit':10,'retrieval_mode':'native'},8,8,'native_rerank')
    json.dump({'summaries':{k:v['summary'] for k,v in res.items()},'detail':{k:v['detail'] for k,v in res.items()}},
              open('scenario2b_result.json','w'),ensure_ascii=False,indent=1)
asyncio.run(main())
