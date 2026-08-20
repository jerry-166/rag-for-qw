# -*- coding: utf-8 -*-
"""Circle 2 基准：O(n²) index 查找修复 + 摘要/子问题嵌入串行→并行（模拟）
方法：直接对比旧实现（从 git 旧版代码摘出的等价逻辑）与新实现，输入规模递增。
"""
import asyncio, sys, time, statistics
sys.path.insert(0, ".")


class D:  # 模拟 StoredData
    def __init__(self):
        self.summary = "s"
        self.sub_questions = ["q"] * 3
        self.summary_embedding = []
        self.subq_embeddings = []


def bench_fill_old(datas):
    """旧实现：valid_datas.index(d) → O(n^2)"""
    valid_indices = [i for i, d in enumerate(datas) if d.summary and d.sub_questions]
    valid_datas = [datas[i] for i in valid_indices]
    summary_embeddings = list(range(len(valid_datas)))
    subq_embeddings = list(range(len(valid_datas) * 3))
    t0 = time.perf_counter()
    subq_offset = 0
    for idx, d in zip(valid_indices, valid_datas):
        datas[idx].summary_embedding = summary_embeddings[valid_datas.index(d)]
        datas[idx].subq_embeddings = subq_embeddings[subq_offset:subq_offset + len(d.sub_questions)]
        subq_offset += len(d.sub_questions)
    return time.perf_counter() - t0


def bench_fill_new(datas):
    """新实现：enumerate 按位置落位 → O(n)"""
    valid_indices = [i for i, d in enumerate(datas) if d.summary and d.sub_questions]
    valid_datas = [datas[i] for i in valid_indices]
    summary_embeddings = list(range(len(valid_datas)))
    subq_embeddings = list(range(len(valid_datas) * 3))
    t0 = time.perf_counter()
    subq_offset = 0
    for pos, (idx, d) in enumerate(zip(valid_indices, valid_datas)):
        datas[idx].summary_embedding = summary_embeddings[pos]
        datas[idx].subq_embeddings = subq_embeddings[subq_offset:subq_offset + len(d.sub_questions)]
        subq_offset += len(d.sub_questions)
    return time.perf_counter() - t0


def ratio_check(times):
    """超线性判定：相邻规模耗时比 vs 规模比"""
    out = []
    for i in range(1, len(times)):
        out.append(times[i] / times[i - 1])
    return out


async def fake_embed(delay, texts):
    await asyncio.sleep(delay * len(texts) and delay)  # 每批固定延迟
    return [i for i in range(len(texts))]


async def bench_serial_vs_parallel(n_batches=8, delay=0.05):
    """旧：两段 await 串行；新：gather 并行（共享 Semaphore 不影响总延迟模拟）"""
    async def one_call():
        await asyncio.sleep(delay)
        return [0]
    t0 = time.perf_counter()
    await one_call(); await one_call()
    serial = time.perf_counter() - t0
    t0 = time.perf_counter()
    await asyncio.gather(one_call(), one_call())
    par = time.perf_counter() - t0
    return serial, par


if __name__ == "__main__":
    print("=== O(n^2) fill benchmark ===")
    sizes = [1000, 2000, 4000, 8000, 16000]
    old_t, new_t = [], []
    for n in sizes:
        datas = [D() for _ in range(n)]
        to = min(bench_fill_old(datas), bench_fill_old(datas))
        datas = [D() for _ in range(n)]
        tn = min(bench_fill_new(datas), bench_fill_new(datas))
        old_t.append(to); new_t.append(tn)
        print(f"n={n:>6}  old={to*1000:9.2f}ms  new={tn*1000:8.3f}ms  speedup={to/tn:8.1f}x")
    print("old 耗时增长比（应≈4x，超线性）:", [f"{r:.2f}" for r in ratio_check(old_t)])
    print("new 耗时增长比（应≈2x，线性）  :", [f"{r:.2f}" for r in ratio_check(new_t)])
    # 正确性
    a = [D() for _ in range(500)]
    b = [D() for _ in range(500)]
    bench_fill_old(a); bench_fill_new(b)
    assert [d.summary_embedding for d in a] == [d.summary_embedding for d in b]
    assert all(x.subq_embeddings == y.subq_embeddings for x, y in zip(a, b))
    print("correctness: OK (新旧填充结果逐条一致)")

    print("\n=== serial vs parallel (simulated 2 embed calls, 50ms each) ===")
    s, p = asyncio.run(bench_serial_vs_parallel())
    print(f"serial={s*1000:.1f}ms  parallel={p*1000:.1f}ms (expect ~100 vs ~50)")
