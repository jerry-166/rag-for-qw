"""测 qwen3.7-flash vs GLM-4-Flash 速度对比（3 次各）。"""
import os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from openai import OpenAI

# qwen3.7-flash DashScope
print('=== qwen3.7-flash (DashScope) ===')
c = OpenAI(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', api_key=os.environ['DASHSCOPE_API_KEY'])
times = []
for i in range(3):
    t0 = time.time()
    try:
        r = c.chat.completions.create(model='qwen3.7-flash',
            messages=[{'role':'user','content':'一句话说明什么是RAG'}], max_tokens=50)
        dt = time.time() - t0
        times.append(dt)
        print(f'  [{i+1}] {dt:.2f}s reply={r.choices[0].message.content[:30]}')
    except Exception as e:
        print(f'  [{i+1}] ERR {str(e)[:100]}')
if times:
    print(f'  >>> avg={sum(times)/len(times):.2f}s')

# GLM-4-Flash
print('\n=== GLM-4-Flash (智谱) ===')
c = OpenAI(base_url='https://open.bigmodel.cn/api/paas/v4/', api_key=os.environ['ZHIPU_API_KEY'])
times = []
for i in range(3):
    t0 = time.time()
    try:
        r = c.chat.completions.create(model='glm-4-flash',
            messages=[{'role':'user','content':'一句话说明什么是RAG'}], max_tokens=50)
        dt = time.time() - t0
        times.append(dt)
        print(f'  [{i+1}] {dt:.2f}s reply={r.choices[0].message.content[:30]}')
    except Exception as e:
        print(f'  [{i+1}] ERR {str(e)[:100]}')
if times:
    print(f'  >>> avg={sum(times)/len(times):.2f}s')

# Cohere command-a-plus（对比之前测的 2.03s）
print('\n=== Cohere command-a-plus（对比）===')
import cohere
co = cohere.ClientV2()
times = []
for i in range(3):
    t0 = time.time()
    try:
        r = co.chat(model='command-a-plus-05-2026',
            messages=[{'role':'user','content':'一句话说明什么是RAG'}])
        dt = time.time() - t0
        times.append(dt)
        msg = r.message
        content = "".join(c.text or "" for c in msg.content if c.type == "text")
        print(f'  [{i+1}] {dt:.2f}s reply={content[:30]}')
    except Exception as e:
        print(f'  [{i+1}] ERR {str(e)[:100]}')
if times:
    print(f'  >>> avg={sum(times)/len(times):.2f}s')
