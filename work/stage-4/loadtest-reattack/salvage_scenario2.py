import json
lines = [l for l in open(r'd:\workspace\rag-for-qw\scenario2_run.log', encoding='utf-8') if '"tag"' in l]
s = {json.loads(l)['tag']: json.loads(l) for l in lines}
json.dump({
    'note': 'recovered from stdout log after client KeyError crash (detail lost, summaries intact)',
    'crashed_group': 'hybrid_endpoint (backend c10.dll APPCRASH 0xc0000005 at 22:28)',
    'summaries': s,
}, open(r'd:\workspace\rag-for-qw\work\stage-4\loadtest-reattack\scenario2_recovered_summaries.json', 'w', encoding='utf-8'),
    ensure_ascii=False, indent=1)
print('saved', list(s))
