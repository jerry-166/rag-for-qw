"""qwen3.8-flash 速率测试

保留用户原调用结构（流式 + thinking），增加：
- TTFT（首 token 延迟）
- thinking / answering 两阶段分别计时与 token 计数
- 总耗时与吞吐 (tokens/s)
- 多轮取样求均值（默认 3 轮，可改 --rounds）
"""
import os
import time
import argparse
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

PROMPT = "你是谁"
MODEL = "qwen3.8-flash"


def run_once(prompt: str, enable_thinking: bool):
    messages = [{"role": "user", "content": prompt}]
    t0 = time.perf_counter()
    completion = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        extra_body={"enable_thinking": enable_thinking},
        stream=True,
    )

    ttft = None
    thinking_tokens = 0
    answer_tokens = 0
    thinking_chars = 0
    answer_chars = 0
    phase = "thinking"  # 先 thinking 后 answering

    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if ttft is None:
            ttft = time.perf_counter() - t0

        # thinking 阶段
        if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
            thinking_chars += len(delta.reasoning_content)
            # 粗略 token 估计：中文按 1.5 char/token，英文按 4 char/token，折中 2
            thinking_tokens += max(1, len(delta.reasoning_content) // 2)
        # answering 阶段
        if hasattr(delta, "content") and delta.content:
            answer_chars += len(delta.content)
            answer_tokens += max(1, len(delta.content) // 2)
            if phase == "thinking":
                phase = "answering"

    total = time.perf_counter() - t0
    return {
        "ttft": ttft,
        "thinking_chars": thinking_chars,
        "thinking_tokens_est": thinking_tokens,
        "answer_chars": answer_chars,
        "answer_tokens_est": answer_tokens,
        "total": total,
    }


def fmt_stats(label, stats):
    print(f"\n===== {label} =====")
    print(f"  TTFT (首 token):        {stats['ttft']*1000:7.1f} ms")
    print(f"  thinking 字符数:        {stats['thinking_chars']}")
    print(f"  thinking token 估算:    {stats['thinking_tokens_est']}")
    print(f"  answering 字符数:       {stats['answer_chars']}")
    print(f"  answering token 估算:   {stats['answer_tokens_est']}")
    print(f"  总耗时:                 {stats['total']*1000:7.1f} ms")
    total_tokens = stats['thinking_tokens_est'] + stats['answer_tokens_est']
    if stats['total'] > 0 and total_tokens > 0:
        print(f"  总吞吐 (token/s):       {total_tokens/stats['total']:.1f}")
    if stats['answer_tokens_est'] > 0 and (stats['total'] - (stats['ttft'] or 0)) > 0:
        ans_dur = stats['total'] - (stats['ttft'] or 0)
        print(f"  answering 吞吐 (tok/s): {stats['answer_tokens_est']/ans_dur:.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3, help="重复轮数")
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--no-thinking", action="store_true", help="关闭深度思考")
    args = ap.parse_args()

    enable_thinking = not args.no_thinking
    print(f"模型: {MODEL} | thinking={enable_thinking} | prompt={args.prompt!r} | rounds={args.rounds}")

    all_stats = []
    for i in range(args.rounds):
        print(f"\n--- 第 {i+1}/{args.rounds} 轮 ---")
        s = run_once(args.prompt, enable_thinking)
        fmt_stats(f"Round {i+1}", s)
        all_stats.append(s)

    if args.rounds > 1:
        avg_ttft = sum(s['ttft'] for s in all_stats) / len(all_stats)
        avg_total = sum(s['total'] for s in all_stats) / len(all_stats)
        avg_think_tok = sum(s['thinking_tokens_est'] for s in all_stats) / len(all_stats)
        avg_ans_tok = sum(s['answer_tokens_est'] for s in all_stats) / len(all_stats)
        avg_total_tok = avg_think_tok + avg_ans_tok
        print("\n" + "=" * 50)
        print("===== 汇总均值 =====")
        print(f"  平均 TTFT:              {avg_ttft*1000:7.1f} ms")
        print(f"  平均总耗时:             {avg_total*1000:7.1f} ms")
        print(f"  平均 thinking tokens:  {avg_think_tok:.0f}")
        print(f"  平均 answering tokens:  {avg_ans_tok:.0f}")
        if avg_total > 0 and avg_total_tok > 0:
            print(f"  平均总吞吐 (tok/s):    {avg_total_tok/avg_total:.1f}")
        if avg_ans_tok > 0 and (avg_total - avg_ttft) > 0:
            print(f"  平均 answering 吞吐:   {avg_ans_tok/(avg_total-avg_ttft):.1f} tok/s")


if __name__ == "__main__":
    main()
