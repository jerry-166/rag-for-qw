"""测试 litellm 哪些模型能用（不 429/402）。"""
import requests, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
models = ['glm-5.1','gpt-5.2','gemini-2.5-pro','mimo-v2.5-pro','Agnes-2.0-Flash','glm-5-turbo','glm-4.5-air','xiaomi/mimo-v2.5-pro']
for m in models:
    try:
        r = requests.post('http://localhost:4000/v1/chat/completions',
            headers={'Authorization':'Bearer sk-jerry166'},
            json={'model':m,'messages':[{'role':'user','content':'回复OK'}],'max_tokens':10},
            timeout=20)
        body = r.text[:120] if r.status_code != 200 else r.json().get('choices',[{}])[0].get('message',{}).get('content','')[:60]
        print(f"{m}: {r.status_code} {body}", flush=True)
    except Exception as e:
        print(f"{m}: ERR {e}", flush=True)
