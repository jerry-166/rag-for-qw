"""03§7 回退验证：单开路径（回退后=委托 CombinedEnhancer 只取所需字段）vs A 基线。

同 16 样本（doc19，种子 20260820），judge 复用 ab_c_experiment.py 的模板与流程。
只跑两组：A_old_combined（重建迁移前 gen_chain）与回退后的单开两组
（SubQuestionEnhancer / SummaryEnhancer，均已委托 CombinedEnhancer 合并 prompt）。
判定：与 A 的打分差 ≤0.3 达标。
"""
import asyncio, json, random, statistics, sys, os, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../backend/.env"))

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.output_parsers import OutputFixingParser
from pydantic import BaseModel

from config import settings
from services.database import db
from services.enhancers.sub_question import SubQuestionEnhancer
from services.enhancers.summary import SummaryEnhancer

N_SAMPLES = 16

def build_A_chain(model):
    class SubqAndSummary(BaseModel):
        subqs: list[str]
        summary: str
    parser = PydanticOutputParser(pydantic_object=SubqAndSummary)
    fixing = OutputFixingParser.from_llm(parser=parser, llm=model)
    tpl = PromptTemplate.from_template(
        "你是一个专业的文档解析助手，负责为给定的文档段落生成子问题和摘要。\n"
        "请根据以下文档段落，生成3~5个相关的子问题和摘要。\n"
        "文档段落：{document_text}\n"
        "请严格按照以下JSON格式返回结果：{{'subqs':['subq1', 'subq2', ...], 'summary':'摘要内容'}}，请至少生成1条子问题"
    )
    return tpl | model | fixing

def get_chat_model():
    return ChatOpenAI(
        model_name=settings.DEFAULT_MODEL,
        api_key=settings.LITELLM_API_KEY,
        base_url=settings.LITELLM_BASE_URL,
        max_retries=settings.LLM_MAX_RETRIES,
        timeout=settings.LLM_TIMEOUT,
    )

def sample_chunks():
    rows = db.fetchall("SELECT id, content FROM document_chunk WHERE document_id=19 ORDER BY id")
    rnd = random.Random(20260820)
    return rnd.sample(rows, N_SAMPLES)

async def run_group(name, enhance_fn, chunks):
    t0 = time.time()
    results = await enhance_fn([c["content"] for c in chunks])
    stats = {"group": name, "n": len(chunks), "wall_s": round(time.time() - t0, 1),
             "parse_ok": 0, "subq_counts": [], "summary_lens": [], "outputs": []}
    for c, r in zip(chunks, results):
        subqs, summary = r.get("subqs", []), r.get("summary", "")
        if subqs or summary:
            stats["parse_ok"] += 1
        stats["subq_counts"].append(len(subqs))
        stats["summary_lens"].append(len(summary))
        stats["outputs"].append({"chunk_id": c["id"], "chunk_head": c["content"][:80],
                                 "subqs": subqs, "summary": summary})
    return stats

JUDGE_TEMPLATE = """你是严格的评审员。给定文档段落和增强生成结果，按 1-5 分打分（5 最好）：
1. subq_relevance：子问题是否与段落内容相关、表述清晰可独立理解（无子问题则 0 分）；
2. subq_useful：子问题作为检索变体是否有区分度（不重复、不空泛）；
3. summary_faithful：摘要是否忠实概括段落要点、无幻觉（无摘要则 0 分）。
文档段落：{chunk}
子问题：{subqs}
摘要：{summary}
只输出 JSON：{{"subq_relevance": x, "subq_useful": x, "summary_faithful": x, "note": "一句话"}}"""

async def judge_all(model, stats_list):
    sem = asyncio.Semaphore(4)
    async def one(out):
        prompt = JUDGE_TEMPLATE.format(
            chunk=out["chunk_head"], subqs=json.dumps(out["subqs"], ensure_ascii=False),
            summary=out["summary"] or "（无摘要）")
        async with sem:
            try:
                resp = await model.ainvoke(prompt)
                txt = resp.content.strip().strip("`")
                if txt.startswith("json"): txt = txt[4:]
                return json.loads(txt)
            except Exception as e:
                return {"subq_relevance": None, "subq_useful": None, "summary_faithful": None, "note": f"judge_err:{e}"}
    for stats in stats_list:
        scores = await asyncio.gather(*[one(o) for o in stats["outputs"]])
        valid = [s for s in scores if s.get("subq_relevance") is not None]
        stats["judge_valid"] = len(valid)
        def avg(key):
            vals = [s[key] for s in valid if s.get(key) is not None]
            return round(statistics.mean(vals), 2) if vals else None
        stats["avg_subq_relevance"] = avg("subq_relevance")
        stats["avg_subq_useful"] = avg("subq_useful")
        stats["avg_summary_faithful"] = avg("summary_faithful")
        stats["judge_raw"] = scores

async def main():
    chunks = sample_chunks()
    print(f"基准集: {len(chunks)} chunks（doc19，固定种子 20260820）")
    model = get_chat_model()
    a_chain = build_A_chain(model)
    async def a_fn(texts):
        raws = await a_chain.abatch([{"document_text": t[:3000]} for t in texts])
        out = []
        for raw in raws:
            if isinstance(raw, BaseModel) and hasattr(raw, "subqs"):
                out.append({"subqs": raw.subqs, "summary": raw.summary})
            else:
                out.append({"subqs": [], "summary": ""})
        return out
    sq = SubQuestionEnhancer(model)
    sm = SummaryEnhancer(model)
    groups = await asyncio.gather(
        run_group("A_old_combined", a_fn, chunks),
        run_group("SubQ_solo_fallback", lambda ts: sq.enhance_batch(ts), chunks),
        run_group("Summary_solo_fallback", lambda ts: sm.enhance_batch(ts), chunks),
    )
    await judge_all(model, groups)
    print("\n=== 结构指标 ===")
    for g in groups:
        sqc = g["subq_counts"]
        print(f"{g['group']}: parse_ok={g['parse_ok']}/{g['n']} wall={g['wall_s']}s "
              f"subq_mean={statistics.mean(sqc):.2f} 越界={sum(1 for x in sqc if x<1 or x>5)} "
              f"摘要均长={statistics.mean(g['summary_lens']):.0f}")
    print("\n=== LLM-as-judge（1-5）===")
    for g in groups:
        print(f"{g['group']}: 有效={g['judge_valid']}/{g['n']} subq_rel={g['avg_subq_relevance']} "
              f"subq_use={g['avg_subq_useful']} sum_faith={g['avg_summary_faithful']}")
    a = groups[0]
    print("\n=== vs A 差值（|Δ|≤0.3 达标）===")
    for g in groups[1:]:
        print(f"{g['group']} vs A: subq_rel={round(g['avg_subq_relevance']-a['avg_subq_relevance'],2)} "
              f"subq_use={round(g['avg_subq_useful']-a['avg_subq_useful'],2)} "
              f"sum_faith={round(g['avg_summary_faithful']-a['avg_summary_faithful'],2)}")
    with open(os.path.join(os.path.dirname(__file__), "ab_c_fallback_results.json"), "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=1)
    print("\nsaved ab_c_fallback_results.json")

asyncio.run(main())
