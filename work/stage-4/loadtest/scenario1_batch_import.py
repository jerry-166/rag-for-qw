"""Stage4 圈2 场景1：批量文档导入压测（百级 markdown）
120 篇：110 篇入 loadtest-noop KB（增强全关，generate no-op），10 篇入 loadtest-real KB（真实 LLM 增强，质量路径采样）。
分批：upload 并发 8 -> split 并发 4 -> generate 并发 2(noop)/2(real) -> import 并发 3。
记录每 doc 每阶段耗时/成功失败，落盘 JSON+CSV。
"""
import asyncio, json, random, time, statistics, csv, sys
import requests, aiohttp

B = 'http://localhost:8003'
random.seed(42)

TOPICS = ["向量数据库", "检索增强生成", "文档切片策略", "嵌入模型", "重排序", "知识图谱", "语义缓存", "多路召回", "查询改写", "评估基准",
          "分布式索引", "倒排索引", "分词算法", "文本压缩", "联邦学习", "数据脱敏", "流式计算", "消息队列", "一致性哈希", "熔断降级"]

def gen_doc(i):
    """混合大小：30% 小(~4KB) 50% 中(~15KB) 20% 大(~45KB)，中文技术文本带标题结构"""
    size_cls = random.choices(['s','m','l'], weights=[3,5,2])[0]
    target = {'s':4000,'m':15000,'l':45000}[size_cls]
    topic = TOPICS[i % len(TOPICS)]
    parts = [f"# {topic} 技术详解（测试文档 {i:03d}）\n\n本文介绍{topic}的核心概念、架构与工程实践。压测生成文档，用于 Stage 4 批量导入性能测试。\n"]
    sec = 0
    while sum(len(p) for p in parts) < target:
        sec += 1
        parts.append(f"\n## {topic} 第{sec}节：原理与实现\n\n{topic}在现代系统中承担关键角色。第{sec}节讨论其内部机制："
                     f"数据经过预处理后进入主流程，系统按批次处理并维护状态一致性。"
                     f"当负载上升时，通过并发控制与队列缓冲平滑流量；当依赖服务异常时，通过重试与降级保证可用性。"
                     f"监控方面需要关注吞吐量、延迟分位数与错误率三类核心指标，并对慢查询进行归因分析。"
                     f"实践中常见的问题包括缓存失效风暴、连接池耗尽、以及远程服务网络往返延迟过高，"
                     f"这些都需要通过压测在上线前暴露。参数调优应基于实测数据而非直觉，任何改动需保留前后对比证据链。\n")
        if sec % 3 == 0:
            parts.append(f"\n### {topic} 小节 {sec}.1：示例与清单\n\n- 配置项应支持热生效，避免重启代价\n"
                         f"- 批处理大小与并发度需联合调优\n- 审计与观测埋点随编码同步落地\n"
                         f"- 失败清单与成功率必须如实记录\n\n```python\n"
                         f"def process(batch):\n    results = [handle(x) for x in batch]\n    return [r for r in results if r.ok]\n```\n")
    return ("".join(parts), f"loadtest-doc-{i:03d}-{topic}.md")

def login(u,p):
    return requests.post(B+'/api/auth/login', data={'username':u,'password':p}).json()['access_token']

async def upload(session, token, kb_id, content, fname):
    data = aiohttp.FormData(); data.add_field('file', content.encode('utf-8'), filename=fname, content_type='text/markdown')
    data.add_field('kb_id', str(kb_id))
    t0=time.perf_counter()
    async with session.post(B+'/api/upload/markdown', data=data, headers={'Authorization':f'Bearer {token}'}) as r:
        j = await r.json(); dt=time.perf_counter()-t0
        ok = r.status==200 and j.get('status')=='success'
        return {'file_id':j.get('file_id'),'ok':ok,'ms':dt*1000,'code':r.status,'msg':str(j.get('message',''))[:100]}

async def stage(session, token, path, fid):
    t0=time.perf_counter()
    async with session.post(f'{B}{path}/{fid}', headers={'Authorization':f'Bearer {token}'}) as r:
        try: j=await r.json()
        except: j={}
        return {'ok':r.status==200,'ms':(time.perf_counter()-t0)*1000,'code':r.status,'msg':str(j.get('detail',j.get('message','')))[:150]}

def pctl(xs,p):
    if not xs: return None
    xs=sorted(xs); k=(len(xs)-1)*p/100; f=int(k)
    return xs[f] if f+1>=len(xs) else xs[f]+(xs[f+1]-xs[f])*(k-f)

async def run_group(session, token, kb_id, docs, conc, tag, real_generate):
    recs=[]
    sem=asyncio.Semaphore(conc)
    async def up(d):
        async with sem:
            return await upload(session, token, kb_id, d[0], d[1])
    ups = await asyncio.gather(*[up(d) for d in docs])
    for d,u in zip(docs,ups): recs.append({'doc':d[1],'kb':tag,**u})
    return recs

async def run_stage_for_all(session, token, recs, path, conc):
    sem=asyncio.Semaphore(conc)
    async def one(r):
        if not r['ok'] or not r.get('file_id'): return {'ok':False,'ms':0,'code':-1,'msg':'skip(no file_id)'}
        async with sem:
            return await stage(session, token, path, r['file_id'])
    outs = await asyncio.gather(*[one(r) for r in recs])
    for r,o in zip(recs,outs):
        r[path.strip('/')]=o
        # propagate failure
        if not o['ok']: r['ok']=False; r['failed_at']=path
    return outs

async def main():
    tok_all = json.load(open('tokens.json'))
    token = requests.post(B+'/api/auth/login',data={'username':'loadtester','password':'Loadtest#123'}).json()['access_token']
    N_NOOP, N_REAL = 110, 10
    noop_docs=[gen_doc(i) for i in range(N_NOOP)]
    real_docs=[gen_doc(1000+i) for i in range(N_REAL)]
    report={'config':{'noop':N_NOOP,'real':N_REAL,'started':time.strftime('%F %T')},'noop':[],'real':[]}
    conn=aiohttp.TCPConnector(limit=32)
    async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=1800)) as s:
        # uploads
        for tag,docs,kb in [('noop',noop_docs,17),('real',real_docs,18)]:
            t0=time.perf_counter()
            recs=await run_group(s, token, kb, docs, conc=8, tag=tag, real_generate=None)
            wall=time.perf_counter()-t0
            report[tag]=recs
            ok=[r for r in recs if r['ok']]
            print(f"[upload {tag}] {len(ok)}/{len(recs)} ok, wall={wall:.1f}s, chunks≈", flush=True)
            report[f'upload_summary_{tag}']={'ok':len(ok),'total':len(recs),'wall_s':wall}
        # stages per KB: noop first (fast), real generate is the slow one
        for tag, gen_conc in [('noop',4),('real',2)]:
            recs=[r for r in report[tag]]
            for path, conc in [('/api/process/split',4),('/api/process/generate',gen_conc),('/api/process/import',3)]:
                t0=time.perf_counter()
                outs=await run_stage_for_all(s, token, recs, path, conc)
                wall=time.perf_counter()-t0
                ms=[o['ms'] for o in outs if o['ok']]
                summ={'ok':sum(1 for o in outs if o['ok']),'total':len(outs),'wall_s':round(wall,1),
                      'p50_ms':round(pctl(ms,50)) if ms else None,'p95_ms':round(pctl(ms,95)) if ms else None,
                      'max_ms':round(max(ms)) if ms else None}
                report[f'{path.strip("/").replace("/","_")}_summary_{tag}']=summ
                print(f"[{path} {tag}] {summ}", flush=True)
    report['config']['finished']=time.strftime('%F %T')
    json.dump(report, open('scenario1_result.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
    # CSV
    keys=set()
    for r in report['noop']+report['real']: keys|=set(r)
    with open('scenario1_detail.csv','w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=['doc','kb','file_id','ok']+[k for k in sorted(keys) if k not in('doc','kb','file_id','ok')]+['failed_at'])
        w.writeheader(); [w.writerow(r) for r in report['noop']+report['real']]
    # final status via DB-less check: query result endpoint
    print("DONE")

asyncio.run(main())
