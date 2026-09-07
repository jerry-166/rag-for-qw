"""测免费 LLM（智谱 GLM-4-Flash + 火山 doubao + 小米 mimo + NVIDIA）速度 + 限额。
国内可直连，免代理，免费额度。"""
import os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from openai import OpenAI

# 1. 智谱 GLM-4-Flash（免费 tier，国内快）
print('=== 智谱 GLM-4-Flash ===')
try:
    c = OpenAI(base_url='https://open.bigmodel.cn/api/paas/v4/', api_key=os.environ['ZHIPU_API_KEY'])
    for i in range(3):
        t0 = time.time()
        r = c.chat.completions.create(model='glm-4-flash',
            messages=[{'role':'user','content':'一句话说明什么是RAG'}], max_tokens=50)
        dt = time.time() - t0
        print(f'  [{i+1}] {dt:.2f}s reply={r.choices[0].message.content[:40]}')
except Exception as e:
    print(f'  ERR {str(e)[:180]}')

# 2. 火山引擎 doubao（ARK，字节，免费额度）
print('\n=== 火山 doubao（ARK）===')
try:
    c = OpenAI(base_url='https://ark.cn-beijing.volces.com/api/v3/', api_key=os.environ['ARK_API_KEY'])
    for m in ['doubao-1.5-pro-32k-250115', 'doubao-pro-32k', 'doubao-1.5-lite-32k']:
        try:
            t0 = time.time()
            r = c.chat.completions.create(model=m, messages=[{'role':'user','content':'hi'}], max_tokens=10)
            print(f'  {m}: OK {time.time()-t0:.2f}s')
            break
        except Exception as e:
            print(f'  {m}: {str(e)[:100]}')
except Exception as e:
    print(f'  ERR {str(e)[:180]}')

# 3. 小米 mimo
print('\n=== 小米 mimo ===')
try:
    c = OpenAI(base_url='https://token-plan-cn.xiaomimimo.com/v1', api_key=os.environ['MIMO_API_KEY'])
    for m in ['mimo-v2-flash', 'mimo-v2-pro', 'mimo-v2.5-pro']:
        try:
            t0 = time.time()
            r = c.chat.completions.create(model=m, messages=[{'role':'user','content':'hi'}], max_tokens=10)
            print(f'  {m}: OK {time.time()-t0:.2f}s')
            break
        except Exception as e:
            print(f'  {m}: {str(e)[:100]}')
except Exception as e:
    print(f'  ERR {str(e)[:180]}')

# 4. NVIDIA（llama，需代理可能）
print('\n=== NVIDIA llama ===')
try:
    c = OpenAI(base_url='https://integrate.api.nvidia.com/v1', api_key=os.environ['NVIDIA_API_KEY'])
    t0 = time.time()
    r = c.chat.completions.create(model='meta/llama-3.1-8b-instruct',
        messages=[{'role':'user','content':'hi'}], max_tokens=10)
    print(f'  OK {time.time()-t0:.2f}s')
except Exception as e:
    print(f'  ERR {str(e)[:180]}')

# 5. HuggingFace Inference（免费 tier）
print('\n=== HuggingFace ===')
try:
    c = OpenAI(base_url='https://api-inference.huggingface.co/v1/', api_key=os.environ['HUGGINGFACE_API_KEY'])
    # HF 不完全 OpenAI 兼容，跳过
    print('  (HF Inference API 非完全 OpenAI 兼容，跳过)')
except Exception as e:
    print(f'  ERR {str(e)[:150]}')
