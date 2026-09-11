"""测试 Cohere embed-v4.0 与 command-a-plus-05-2026 两个模型调用。

用法: backend/.venv/Scripts/python.exe work/cohere-test/test_models.py
"""
import os
import time
from pathlib import Path

# 从 backend/.env 加载 COHERE_API_KEY（不回显）
env_path = Path(r"d:/workspace/rag-for-qw/backend/.env")
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line.startswith("COHERE_API_KEY="):
        os.environ["COHERE_API_KEY"] = line.split("=", 1)[1].strip()

import cohere

co = cohere.ClientV2()
print(f"cohere SDK: {cohere.__version__}\n")

# ---------- 1) embed-v4.0 ----------
print("=" * 60)
print("[1] embed  model=embed-v4.0 input_type=classification")
print("=" * 60)
t0 = time.time()
try:
    response = co.embed(
        inputs=[
            {
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "goodbye"},
                ]
            },
            {
                "content": [
                    {"type": "text", "text": "RAG 是什么？"},
                ]
            },
        ],
        model="embed-v4.0",
        input_type="classification",
        embedding_types=["float"],
    )
    dt = time.time() - t0
    emb = response.embeddings.float_
    print(f"OK  elapsed={dt:.2f}s  num_inputs={len(emb)}")
    for i, e in enumerate(emb):
        print(f"  input[{i}] dim={len(e)}  head={[round(x, 5) for x in e[:5]]}")
    print(f"  meta billed_units={response.meta.billed_units}")
except Exception as exc:
    print(f"FAIL elapsed={time.time() - t0:.2f}s")
    print(f"  {type(exc).__name__}: {exc}")

# ---------- 2) command-a-plus-05-2026 chat ----------
print()
print("=" * 60)
print("[2] chat  model=command-a-plus-05-2026")
print("=" * 60)
t0 = time.time()
try:
    response = co.chat(
        model="command-a-plus-05-2026",
        messages=[{"role": "user", "content": "用一句话说明 RAG 和 Fine-tuning 的区别"}],
    )
    dt = time.time() - t0
    msg = response.message
    content = "".join(c.text or "" for c in msg.content if c.type == "text")
    print(f"OK  elapsed={dt:.2f}s")
    print(f"  reply: {content}")
    if msg.citations:
        print(f"  citations: {len(msg.citations)}")
    print(f"  usage: {msg.usage}")
except Exception as exc:
    print(f"FAIL elapsed={time.time() - t0:.2f}s")
    print(f"  {type(exc).__name__}: {exc}")
