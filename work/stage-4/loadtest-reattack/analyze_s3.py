import json, collections
log = json.load(open(r'd:\workspace\rag-for-qw\work\stage-4\loadtest-reattack\scenario3_result.json'))
print('ops:', collections.Counter(x['op'] for x in log))
print('actions:', collections.Counter(x.get('action', x['op']) for x in log))
fails = [x for x in log if not x['ok']]
for x in fails:
    r = x.get('resp')
    print('FAIL round', x['round'], x['op'], 'code', x['code'], 'resp/err:', str(r or x.get('err'))[:120])
print('ok =', sum(1 for x in log if x['ok']), '/', len(log))
