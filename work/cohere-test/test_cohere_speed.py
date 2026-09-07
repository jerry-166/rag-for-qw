"""测 Cohere chat 速度 + 限额（C 轮决策：qwen 太慢，Cohere 够不够 ~1000 调用）。"""
import os, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
env_path = Path(r"d:/workspace/rag-for-qw/backend/.env")
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line.startswith("COHERE_API_KEY="):
        os.environ["COHERE_API_KEY"] = line.split("=", 1)[1].strip()
import cohere
co = cohere.ClientV2()
print(f'cohere SDK: {cohere.__version__}')

# 1. chat command-a-plus 速度（5 次）
print('\n=== chat command-a-plus-05-2026 速度（5 次）===')
times = []
for i in range(5):
    t0 = time.time()
    try:
        r = co.chat(model='command-a-plus-05-2026',
            messages=[{'role':'user','content':f'一句话说明什么是向量数据库？回复{i+1}'}])
        dt = time.time() - t0
        times.append(dt)
        msg = r.message
        content = "".join(c.text or "" for c in msg.content if c.type == "text")
        print(f'  [{i+1}] {dt:.2f}s reply={content[:40]}')
    except Exception as e:
        print(f'  [{i+1}] ERR {str(e)[:140]}')
    time.sleep(0.3)
if times:
    print(f'  >>> avg={sum(times)/len(times):.2f}s min={min(times):.2f}s max={max(times):.2f}s')

# 2. 查限额
print('\n=== 限额（check_api_key）===')
try:
    r = co.check_api_key()
    print(f'organization: {getattr(r, "organization_id", "?")}')
    print(f'valid: {getattr(r, "valid", "?")}')
    print(f'raw: {str(r)[:300]}')
except Exception as e:
    print(f'check err: {str(e)[:200]}')

# 3. command-r 备选（2 次）
print('\n=== command-r 速度（2 次）===')
for i in range(2):
    t0 = time.time()
    try:
        r = co.chat(model='command-r',
            messages=[{'role':'user','content':'一句话说明什么是BM25？'}])
        dt = time.time() - t0
        print(f'  [{i+1}] {dt:.2f}s')
    except Exception as e:
        print(f'  [{i+1}] ERR {str(e)[:140]}')

# 4. embed-v4.0 速度（2 次，dim=1536 与 Milvus 一致）
print('\n=== embed-v4.0 速度（2 次）===')
for i in range(2):
    t0 = time.time()
    try:
        r = co.embed(inputs=[{'content':[{'type':'text','text':'测试向量数据库'}]}],
            model='embed-v4.0', input_type='classification', embedding_types=['float'])
        dt = time.time() - t0
        emb = r.embeddings.float_
        print(f'  [{i+1}] {dt:.2f}s dim={len(emb[0])}')
    except Exception as e:
        print(f'  [{i+1}] ERR {str(e)[:140]}')
