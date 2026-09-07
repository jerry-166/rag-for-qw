"""测 LightRAG query 是否已能返回结果（pipeline busy 时也能查已索引部分）"""
import requests, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
LR = 'http://localhost:9621'
for q in ['向量数据库的核心原理', 'BM25的打分公式', '重排序的作用']:
    for mode in ['naive', 'hybrid']:
        try:
            r = requests.post(f'{LR}/query',
                json={'query': q, 'mode': mode, 'top_k': 5},
                timeout=60)
            j = r.json()
            ans = j.get('response', '')
            refs = j.get('references', [])
            print(f'[{q}/{mode}] status={r.status_code} ans_len={len(ans)} refs={len(refs)}')
            if ans and len(ans) > 20:
                print(f'  ans[:100]: {ans[:100]}')
            time.sleep(0.5)
        except Exception as e:
            print(f'[{q}/{mode}] ERR: {str(e)[:80]}')
