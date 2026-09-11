"""测 GLM-4-Flash-250414 速度 + 可用性（避免限流，c-worker4 用）。"""
import os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from openai import OpenAI
c = OpenAI(base_url='https://open.bigmodel.cn/api/paas/v4/', api_key=os.environ['ZHIPU_API_KEY'])
times = []
for i in range(5):
    t0 = time.time()
    try:
        r = c.chat.completions.create(model='glm-4-flash-250414',
            messages=[{'role':'user','content':'一句话说明什么是RAG'}], max_tokens=50)
        dt = time.time() - t0
        times.append(dt)
        print(f'[{i+1}] {dt:.2f}s reply={r.choices[0].message.content[:40]}')
    except Exception as e:
        print(f'[{i+1}] ERR {str(e)[:150]}')
    time.sleep(0.3)
if times:
    print(f'>>> avg={sum(times)/len(times):.2f}s')
