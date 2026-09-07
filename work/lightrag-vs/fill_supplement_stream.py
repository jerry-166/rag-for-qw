"""逐条 fill kb17_supplement answer（claw agent，避免批量 API 超时）。
每条调 /api/chat 流式接口或直接 agent，拿 answer 保存。
用 /api/evaluation/fill 单条模式——但 API 是批量的。
改用直接调 agent.process 的 python 脚本。
"""
import sys, os, json, asyncio, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'evaluation', 'testsets', 'kb17_supplement.json'))

async def main():
    from agent.registry import get_registry, setup_registry, AgentType
    from agent.claw_agent.memory.memory_manager import MemoryManager
    from agent.claw_agent.memory.session_store import SessionStore
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix='eval_fill_'))
    setup_registry(claw_memory_manager=MemoryManager(), claw_session_store=SessionStore(sessions_dir=tmp))
    registry = get_registry()
    agent = registry.get(agent_type=AgentType.CLAW, fresh=True)

    d = json.load(open(OUT, encoding='utf-8'))
    samples = d['samples']
    print(f'total: {len(samples)}', flush=True)

    for i, s in enumerate(samples):
        if s.get('answer') and '抱歉' not in s['answer'] and '不足以回答' not in s.get('answer',''):
            continue
        try:
            resp = await agent.process(query=s['question'], knowledge_base_id=17)
            s['answer'] = resp.content or ''
            sources = resp.metadata.get('sources', []) if resp.metadata else []
            if not sources and hasattr(resp, 'sources'):
                sources = resp.sources or []
            # 更新 contexts 为 agent 检索的（native 默认）
            s['contexts'] = [src.get('chunk_text') or src.get('content', '') for src in sources if src.get('chunk_text') or src.get('content')]
            print(f'[{i+1}/{len(samples)}] {s["question"][:30]}: ans={len(s["answer"])}c ctx={len(s["contexts"])}', flush=True)
        except Exception as e:
            print(f'[{i+1}] err: {str(e)[:60]}', flush=True)
            s['answer'] = s.get('answer', '')

        # 每 5 条保存一次（防超时丢数据）
        if (i + 1) % 5 == 0:
            d['count'] = len(samples)
            json.dump(d, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            print(f'  saved checkpoint at {i+1}', flush=True)

    d['count'] = len(samples)
    json.dump(d, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    filled = sum(1 for s in samples if s.get('answer') and '抱歉' not in s['answer'])
    print(f'\n[done] filled={filled}/{len(samples)}', flush=True)

asyncio.run(main())
