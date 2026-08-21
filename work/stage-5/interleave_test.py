"""交错验证：8 个 rerank 请求进行中，穿插发送无 rerank 请求。
修复前：predict 阻塞事件循环，无 rerank 请求会被卡到 rerank 完成（>>30s）。
修复后：无 rerank 请求应接近空载水平（~9s）。"""
import asyncio, json, time
import aiohttp, requests

B = 'http://localhost:8003'
KB = 17
TOKEN = requests.post(B + '/api/auth/login', data={'username': 'loadtester', 'password': 'Loadtest#123'}).json()['access_token']
H = {'Authorization': f'Bearer {TOKEN}'}
Q = {'retrieval_mode': 'native', 'knowledge_base_id': KB, 'limit': 10}
QS = ["如何优化检索延迟", "语义缓存命中率", "熔断降级的实现", "消息队列的可靠性"]

async def req(s, use_rerank, q):
    t0 = time.perf_counter()
    async with s.post(B + '/api/milvus/query', json={**Q, 'query': q, 'use_rerank': use_rerank}, headers=H) as r:
        await r.read()
        return r.status, round(time.perf_counter() - t0, 1)

async def main():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as s:
        rerank_jobs = [asyncio.create_task(req(s, True, QS[i % 4])) for i in range(8)]
        await asyncio.sleep(5)  # 等 rerank 推理开始
        t0 = time.perf_counter()
        nr = []
        for i in range(4):
            nr.append(await req(s, False, QS[i % 4]))
        print('no-rerank during rerank load:', json.dumps(nr), flush=True)
        rr = await asyncio.gather(*rerank_jobs)
        print('rerank jobs:', json.dumps(rr), flush=True)

asyncio.run(main())
