"""Stage4 圈2 场景2：并发检索压测
4 模式 x 固定请求数（native/hybrid_vec: 40 each；advanced: 80；keyword: 200；hybrid_endpoint: 200），
并发 10-20；记录 QPS/延迟分位/错误码；周期采样服务进程 RSS（psutil 按 8003 端口找 PID）。
简化记录：native/hybrid_vec 为与 Stage0 口径一致（use_rerank=true），其余同。KB=17（压测 KB）。
"""
import asyncio, json, time, threading, statistics
import aiohttp, requests

B='http://localhost:8003'
KB=17
TOKEN=requests.post(B+'/api/auth/login',data={'username':'loadtester','password':'Loadtest#123'}).json()['access_token']
H={'Authorization':f'Bearer {TOKEN}'}

QUERIES=["向量数据库的核心原理","如何优化检索延迟","文档切片策略对比","嵌入模型的维度选择","重排序的作用",
         "多路召回如何融合","查询改写的常见方法","评估RAG系统的指标","倒排索引构建过程","语义缓存命中率",
         "一致性哈希的应用","熔断降级的实现","消息队列的可靠性","分布式索引的分片","知识图谱多跳查询",
         "分词算法的对比","流式计算窗口","数据脱敏技术","文本压缩算法","联邦学习隐私"]

def pctl(xs,p):
    xs=sorted(xs); k=(len(xs)-1)*p/100; f=int(k)
    return round(xs[f] if f+1>=len(xs) else xs[f]+(xs[f+1]-xs[f])*(k-f))

rss_samples=[]
stop_flag=False
def rss_sampler():
    import psutil
    try:
        pid=None
        for c in psutil.net_connections(kind='tcp'):
            if c.laddr and c.laddr.port==8003 and c.status=='LISTEN': pid=c.pid; break
        p=psutil.Process(pid)
        while not stop_flag:
            rss_samples.append({'t':time.time(),'rss_mb':round(p.memory_info().rss/1048576,1)})
            time.sleep(2)
    except Exception as e:
        rss_samples.append({'error':str(e)})

async def worker(session, ep, body, q, out, sem):
    async with sem:
        t0=time.perf_counter()
        try:
            async with session.post(B+ep, json=body, headers=H) as r:
                await r.read(); dt=(time.perf_counter()-t0)*1000
                out.append({'ok':r.status==200,'ms':dt,'code':r.status})
        except Exception as e:
            out.append({'ok':False,'ms':(time.perf_counter()-t0)*1000,'code':-1,'err':str(e)[:80]})

async def bench(s, ep, body, n, conc, tag):
    out=[]; sem=asyncio.Semaphore(conc)
    t0=time.perf_counter()
    await asyncio.gather(*[worker(s,ep,{**body,'query':QUERIES[i%len(QUERIES)]},None,out,sem) for i in range(n)])
    wall=time.perf_counter()-t0
    ok=[o['ms'] for o in out if o['ok']]; bad=[o for o in out if not o['ok']]
    summ={'tag':tag,'ep':ep,'body':body,'n':n,'conc':conc,'wall_s':round(wall,1),
          'qps':round(n/wall,2),'ok':len(ok),'err':len(bad),'err_rate':round(len(bad)/n*100,2),
          'p50_ms':pctl(ok,50),'p95_ms':pctl(ok,95),'p99_ms':pctl(ok,99),'max_ms':round(max(ok)) if ok else None,
          'err_codes':{}}
    for b in bad: summ['err_codes'][str(b['code'])]=summ['err_codes'].get(str(b['code']),0)+1
    summ['rss_start']=rss_samples[-1]['rss_mb'] if rss_samples else None
    print(json.dumps(summ,ensure_ascii=False),flush=True)
    return {'summary':summ,'detail':out}

async def main():
    global stop_flag
    th=threading.Thread(target=rss_sampler,daemon=True); th.start()
    timeout=aiohttp.ClientTimeout(total=300)
    res={}
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=40)) as s:
        # 预热 1 次各端点（不计数）
        for ep,body in [('/api/milvus/query',{'retrieval_mode':'native','use_rerank':True,'knowledge_base_id':KB,'limit':10}),
                        ('/api/milvus/query',{'retrieval_mode':'hybrid','use_rerank':True,'knowledge_base_id':KB,'limit':10}),
                        ('/api/milvus/query',{'retrieval_mode':'advanced','use_rerank':True,'knowledge_base_id':KB,'limit':10}),
                        ('/api/elasticsearch/search',{'use_rerank':True,'knowledge_base_id':KB,'limit':10}),
                        ('/api/hybrid/search',{'use_rerank':True,'knowledge_base_id':KB,'limit':10})]:
            async with s.post(B+ep,json={**body,'query':QUERIES[0]},headers=H) as r:
                print('warmup',ep,r.status,flush=True)
        cases=[('/api/milvus/query',{'retrieval_mode':'native'},40,10,'native'),
               ('/api/milvus/query',{'retrieval_mode':'advanced'},80,10,'advanced'),
               ('/api/milvus/query',{'retrieval_mode':'hybrid'},40,10,'hybrid_vec'),
               ('/api/elasticsearch/search',{},200,20,'keyword'),
               ('/api/hybrid/search',{},200,20,'hybrid_endpoint')]
        for ep,extra,n,conc,tag in cases:
            body={'use_rerank':True,'knowledge_base_id':KB,'limit':10,**extra}
            res[tag]=await bench(s,ep,body,n,conc,tag)
            await asyncio.sleep(3)
    stop_flag=True; time.sleep(0.5)
    json.dump({'summaries':{k:v['summary'] for k,v in res.items()},'rss_samples':rss_samples,
               'detail':{k:v['detail'] for k,v in res.items()}},
              open('scenario2_result.json','w'),ensure_ascii=False,indent=1)
    r0,r1=rss_samples[0],rss_samples[-1]
    print(f"RSS: start={r0['rss_mb']}MB end={r1['rss_mb']}MB samples={len(rss_samples)}")

asyncio.run(main())
