"""多模型分发可行性测试
- 4 个智谱免费模型 + qwen3.8-flash，各测 5 个并发 entity 抽取 calls
- 测量各模型的调用数/成功率/平均耗时
- 给结论：可不可以多模型分发加速 entity 抽取

测试用例：用 backend enhancers/entity.py 的 ENTITY_TEMPLATE 做 entity 抽取
"""
import os, sys, json, time, asyncio, aiohttp
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ZHIPU_KEY = os.getenv('ZHIPU_API_KEY', '')
DASHSCOPE_KEY = os.getenv('DASHSCOPE_API_KEY', '')
ZHIPU_BASE = 'https://open.bigmodel.cn/api/paas/v4/'
DASHSCOPE_BASE = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

# 测试模型列表（模型名, base_url, api_key, 并发限制）
MODELS = [
    ('glm-4-flashx-250414', ZHIPU_BASE, ZHIPU_KEY, 50),
    ('glm-4-flash',         ZHIPU_BASE, ZHIPU_KEY, 20),
    ('glm-4-air',           ZHIPU_BASE, ZHIPU_KEY, 100),
    ('glm-4-air-250414',    ZHIPU_BASE, ZHIPU_KEY, 30),
    ('qwen3.8-flash',       DASHSCOPE_BASE, DASHSCOPE_KEY, 10),  # qwen 并发未知，试 10
]

# entity 抽取 prompt（跟 backend enhancers/entity.py 的 ENTITY_TEMPLATE 一样）
ENTITY_TEMPLATE = (
    "你是知识图谱构建助手，负责从文档段落中抽取实体和实体间的关系。\n"
    "要求：\n"
    "1. 实体是段落中的关键概念、人物、组织、技术、产品、地点等，每个实体给出一句话描述；\n"
    "2. 关系必须表达实体间在原文中明确存在的联系，evidence 为原文依据（不超过100字）；\n"
    "3. 实体数量控制在 1~6 个，关系数量控制在 0~5 条，宁缺毋滥；\n"
    "4. 若段落不含可抽取的实体，返回空数组。\n"
    "文档段落：{document_text}\n"
    "请严格按照以下JSON格式返回结果：\n"
    "{{\"entities\":[{{\"name\":\"实体名\",\"type\":\"类型\",\"description\":\"一句话描述\"}}],"
    "\"relations\":[{{\"head\":\"头实体名\",\"relation\":\"关系\",\"tail\":\"尾实体名\",\"evidence\":\"原文依据\"}}]}}"
)

# 测试文档（取自 CRUD-RAG crud_000 的 news1 片段）
TEST_DOC = (
    "2023-07-31 10:13:18作者：于丹丹来源：扬子晚报，正文："
    "\"大暑\"节气时值\"三伏天\"的\"中伏\"前后，是\"上蒸下煮\"\"湿热交蒸\"到达极点的时节。"
    "江苏省中医院急诊科副主任、副主任中医师徐顺娟介绍，大暑养生关键在养\"心阴\"，护\"脾气\"。"
    "徐顺娟建议大家要保持心情平和，戒燥戒怒。大暑节气，饮食建议多样化，以清淡易消化为主。"
)

CALLS_PER_MODEL = 5  # 每个模型测 5 个并发 calls

async def call_model(session, model, base_url, api_key, doc_text, semaphore):
    """调单个模型做 entity 抽取"""
    async with semaphore:
        prompt = ENTITY_TEMPLATE.format(document_text=doc_text)
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0,
            'max_tokens': 1000,
        }
        t0 = time.time()
        try:
            async with session.post(f'{base_url}chat/completions',
                headers=headers, json=payload, timeout=60) as r:
                elapsed = time.time() - t0
                if r.status == 200:
                    j = await r.json()
                    content = j.get('choices', [{}])[0].get('message', {}).get('content', '')
                    # 尝试解析 JSON
                    entities = 0
                    try:
                        # 清理 markdown 代码块
                        content_clean = content.strip()
                        if content_clean.startswith('```'):
                            content_clean = content_clean.split('\n', 1)[1].rsplit('```', 1)[0].strip()
                        parsed = json.loads(content_clean)
                        entities = len(parsed.get('entities', []))
                    except Exception:
                        pass
                    return {'status': 'ok', 'elapsed': elapsed, 'entities': entities, 'content_len': len(content)}
                else:
                    body = await r.text()
                    return {'status': f'fail_{r.status}', 'elapsed': elapsed, 'error': body[:100]}
        except asyncio.TimeoutError:
            return {'status': 'timeout', 'elapsed': time.time() - t0, 'error': '60s timeout'}
        except Exception as e:
            return {'status': 'exc', 'elapsed': time.time() - t0, 'error': str(e)[:100]}

async def test_model(session, model_name, base_url, api_key, concurrency):
    """测试单个模型：并发 CALLS_PER_MODEL 个 calls"""
    sem = asyncio.Semaphore(concurrency)
    print(f'\n=== {model_name} (并发限制={concurrency}, 测试 {CALLS_PER_MODEL} calls) ===')
    tasks = [call_model(session, model_name, base_url, api_key, TEST_DOC, sem)
             for _ in range(CALLS_PER_MODEL)]
    t0 = time.time()
    results = await asyncio.gather(*tasks)
    total_elapsed = time.time() - t0
    
    ok = [r for r in results if r['status'] == 'ok']
    fail = [r for r in results if r['status'] != 'ok']
    avg_elapsed = sum(r['elapsed'] for r in ok) / len(ok) if ok else 0
    total_entities = sum(r.get('entities', 0) for r in ok)
    
    print(f'  ok={len(ok)}/{CALLS_PER_MODEL} fail={len(fail)}')
    print(f'  total_elapsed={total_elapsed:.2f}s (并发 {CALLS_PER_MODEL} calls)')
    print(f'  avg_per_call={avg_elapsed:.2f}s')
    print(f'  throughput={CALLS_PER_MODEL/total_elapsed:.2f} calls/s')
    print(f'  total_entities_extracted={total_entities}')
    if fail:
        print(f'  fail details:')
        for r in fail:
            print(f'    {r["status"]}: {r.get("error","")}')
    
    return {
        'model': model_name,
        'concurrency_limit': concurrency,
        'ok': len(ok),
        'fail': len(fail),
        'total_elapsed': round(total_elapsed, 2),
        'avg_per_call': round(avg_elapsed, 2),
        'throughput': round(CALLS_PER_MODEL / total_elapsed, 2) if total_elapsed > 0 else 0,
        'total_entities': total_entities,
    }

async def main():
    print('=== 多模型分发可行性测试 ===')
    print(f'ZHIPU_API_KEY: {ZHIPU_KEY[:8]}... len={len(ZHIPU_KEY)}')
    print(f'DASHSCOPE_API_KEY: {DASHSCOPE_KEY[:8]}... len={len(DASHSCOPE_KEY)}')
    print(f'测试文档长度: {len(TEST_DOC)} chars')
    print(f'每模型测试 calls 数: {CALLS_PER_MODEL}')
    
    timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        results = []
        for model_name, base_url, api_key, concurrency in MODELS:
            if not api_key:
                print(f'\n=== {model_name}: SKIP (no api key) ===')
                continue
            r = await test_model(session, model_name, base_url, api_key, concurrency)
            results.append(r)
    
    # 汇总
    print('\n' + '=' * 80)
    print('=== 汇总 ===')
    print('=' * 80)
    print(f'{"模型":<25} {"并发限制":>8} {"ok":>5} {"fail":>5} {"总耗时":>8} {"平均/call":>10} {"吞吐(calls/s)":>14} {"实体数":>8}')
    print('-' * 80)
    for r in results:
        print(f'{r["model"]:<25} {r["concurrency_limit"]:>8} {r["ok"]:>5} {r["fail"]:>5} {r["total_elapsed"]:>7.2f}s {r["avg_per_call"]:>9.2f}s {r["throughput"]:>14.2f} {r["total_entities"]:>8}')
    
    # 结论
    print('\n=== 结论 ===')
    total_throughput = sum(r['throughput'] for r in results if r['fail'] == 0)
    print(f'总吞吐（成功模型）: {total_throughput:.2f} calls/s')
    print(f'1000 docs entity 抽取预估: {1000/total_throughput:.0f}s = {1000/total_throughput/60:.1f} min' if total_throughput > 0 else 'NA')
    
    # 单模型最快
    best = max(results, key=lambda r: r['throughput']) if results else None
    if best:
        print(f'单模型最快: {best["model"]} = {best["throughput"]:.2f} calls/s')
        print(f'单模型 1000 docs 预估: {1000/best["throughput"]:.0f}s = {1000/best["throughput"]/60:.1f} min')

if __name__ == '__main__':
    asyncio.run(main())
