"""修复 testset：answer dict → str"""
import json, os

TESTSET_DIR = 'd:/workspace/rag-for-qw/backend/evaluation/testsets'

for fname in os.listdir(TESTSET_DIR):
    if not fname.startswith('c2_crud_ours_') or not fname.endswith('.json'):
        continue
    fpath = os.path.join(TESTSET_DIR, fname)
    with open(fpath, encoding='utf-8') as f:
        d = json.load(f)
    
    fixed = 0
    for s in d.get('samples', []):
        ans = s.get('answer')
        if isinstance(ans, dict):
            s['answer'] = ans.get('content', '') or ans.get('response', '') or str(ans)
            fixed += 1
        elif not isinstance(ans, str):
            s['answer'] = str(ans) if ans else ''
            fixed += 1
    
    if fixed > 0:
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        print(f'{fname}: fixed {fixed} answer dict→str')
    else:
        print(f'{fname}: no fix needed')

print('done')
