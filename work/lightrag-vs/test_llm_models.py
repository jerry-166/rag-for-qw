"""测 litellm 可用 LLM 模型"""
import requests, json
H = {"Authorization": "Bearer sk-jerry166"}
models = ["gpt-4o","deepseek-chat","glm-5.1","glm-5-turbo","glm-4.5-air","mimo-v2-flash","Agnes-2.0-Flash","deepseek-v3-2-251201","gemini-2.5-pro"]
for m in models:
    try:
        r = requests.post("http://localhost:4000/v1/chat/completions",
            headers=H, json={"model": m, "messages":[{"role":"user","content":"hi"}], "max_tokens": 5},
            timeout=15)
        if r.status_code == 200:
            print(f"{m}: OK ({r.json()['choices'][0]['message']['content'][:20]})")
        else:
            err = r.json().get('error',{}).get('message','')[:60]
            print(f"{m}: {r.status_code} {err}")
    except Exception as e:
        print(f"{m}: err {str(e)[:50]}")
