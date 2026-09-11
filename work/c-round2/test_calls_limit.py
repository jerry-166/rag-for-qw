"""测试 calls/hour 是账户级还是模型级限制
- 同时用 2 个模型各跑 50 calls（共 100 calls）
- 如果 2 个模型都成功 → 模型级独立限制（多模型分发可行）
- 如果 1 个成功 1 个 429 → 账户级共享限制
"""
import os, sys, json, time, asyncio, aiohttp
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ZHIPU_KEY = os.getenv('ZHIPU_API_KEY', '')
ZHIPU_BASE = 'https://open.bigmodel.cn/api/paas/v4/'

# 2 个不同模型，各跑 50 calls
MODELS = [
    ('glm-4-flashx-250414', 50),  # 50 并发限制
    ('glm-4-air', 100),           # 100 并发限制
]

CALLS_PER_MODEL = 200
TEST_DOC = "江苏省中医院急诊科副主任徐顺娟在大暑节气时期提出大暑养生的关键在于养心阴和护脾气。"

ENTITY_PROMPT = (
    "从以下文档段落中抽取实体（人物/组织/概念/技术/产品/地点），"
    "返回JSON格式：{{\"entities\":[{{\"name\":\"实体名\",\"type\":\"类型\",\"description\":\"描述\"}}]}}\n"
    "文档段落：{document_text}"
)

async def call_model(session, model, base_url, api_key, doc_text, sem):
    async with sem:
        prompt = ENTITY_PROMPT.format(document_text=doc_text)
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        payload = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                   'temperature': 0, 'max_tokens': 500}
        t0 = time.time()
        try:
            async with session.post(f'{base_url}chat/completions',
                headers=headers, json=payload, timeout=30) as r:
                elapsed = time.time() - t0
                if r.status == 200:
                    return {'status': 'ok', 'elapsed': elapsed, 'model': model}
                else:
                    body = await r.text()
                    return {'status': f'fail_{r.status}', 'elapsed': elapsed, 'model': model, 'error': body[:80]}
        except Exception as e:
            return {'status': 'exc', 'elapsed': time.time() - t0, 'model': model, 'error': str(e)[:80]}

async def test_model(session, model_name, concurrency, calls):
    sem = asyncio.Semaphore(concurrency)
    print(f'\n=== {model_name} ({calls} calls, concurrency={concurrency}) ===')
    tasks = [call_model(session, model_name, ZHIPU_BASE, ZHIPU_KEY, TEST_DOC, sem)
             for _ in range(calls)]
    t0 = time.time()
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - t0
    ok = [r for r in results if r['status'] == 'ok']
    fail = [r for r in results if r['status'] != 'ok']
    print(f'  ok={len(ok)}/{calls} fail={len(fail)} elapsed={elapsed:.1f}s')
    print(f'  throughput={calls/elapsed:.2f} calls/s')
    if fail:
        for r in fail[:3]:
            print(f'  fail: {r["status"]} {r.get("error","")}')
    return {'model': model_name, 'ok': len(ok), 'fail': len(fail), 'elapsed': elapsed}

async def main():
    print('=== calls/hour 限制测试：2 模型同时各跑 50 calls ===')
    print(f'ZHIPU_KEY: {ZHIPU_KEY[:8]}...')
    
    timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 同时跑 2 个模型
        tasks = []
        for model, concurrency in MODELS:
            tasks.append(test_model(session, model, concurrency, CALLS_PER_MODEL))
        results = await asyncio.gather(*tasks)
    
    print('\n=== 结论 ===')
    total_ok = sum(r['ok'] for r in results)
    total_fail = sum(r['fail'] for r in results)
    print(f'总 calls: {total_ok + total_fail} (ok={total_ok} fail={total_fail})')
    for r in results:
        print(f'  {r["model"]}: ok={r["ok"]} fail={r["fail"]} elapsed={r["elapsed"]:.1f}s')
    
    if total_fail == 0:
        print('\n✅ 两模型都成功 → calls/hour 是模型级独立限制')
        print('   多模型分发可行：3 模型 × 200/hour = 600/hour = 10 docs/min')
        print('   700 docs / 10 = 70 min（vs 单模型 3.5h）')
    else:
        print(f'\n❌ 有 {total_fail} 个 fail → calls/hour 可能是账户级共享限制')
        print('   多模型分发无法突破（合计 200/hour）')

if __name__ == '__main__':
    asyncio.run(main())
