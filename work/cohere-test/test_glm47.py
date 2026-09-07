"""测 GLM-4.7-Flash 速度 + 可用性（vs glm-4-flash 1.38s）。"""
import os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from openai import OpenAI
c = OpenAI(base_url='https://open.bigmodel.cn/api/paas/v4/', api_key=os.environ['ZHIPU_API_KEY'])

for model in ['glm-4.7-flash', 'glm-4.7-flash-2025.04.09', 'glm-4-flash']:
    print(f'\n=== {model} ===')
    times = []
    for i in range(3):
        t0 = time.time()
        try:
            r = c.chat.completions.create(model=model,
                messages=[{'role':'user','content':'一句话说明什么是RAG'}], max_tokens=50)
            dt = time.time() - t0
            times.append(dt)
            print(f'  [{i+1}] {dt:.2f}s reply={r.choices[0].message.content[:40]}')
        except Exception as e:
            print(f'  [{i+1}] ERR {str(e)[:150]}')
            break
    if times:
        print(f'  >>> avg={sum(times)/len(times):.2f}s')
