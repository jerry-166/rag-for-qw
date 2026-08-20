import subprocess, time, urllib.request, json, urllib.parse
# 1. import app
import importlib, sys; sys.path.insert(0,"backend"); os_cwd=None
t0=time.perf_counter()
r=subprocess.run([r"backend\.venv\Scripts\python.exe","-c","import time;t=time.time();import app;print(f'import app OK {time.time()-t:.2f}s')"],cwd="backend",capture_output=True,text=True)
print(r.stdout.strip() or r.stderr.strip()[-500:])
# 2. start server
log=open("work/stage-1/c6_final_server.log","wb")
p=subprocess.Popen([r"backend\.venv\Scripts\python.exe","-m","uvicorn","app:app","--host","127.0.0.1","--port","8003"],cwd="backend",stdout=log,stderr=subprocess.STDOUT)
t0=time.perf_counter()
while time.perf_counter()-t0<60:
    try:
        if urllib.request.urlopen("http://127.0.0.1:8003/",timeout=1).status==200: break
    except Exception: pass
    time.sleep(0.05)
print(f"boot first200={time.perf_counter()-t0:.2f}s")
# 3. login
data=urllib.parse.urlencode({"username":"admin","password":"Stage1@Test"}).encode()
resp=urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8003/api/auth/login",data=data))
tok=json.load(resp)["access_token"]; print(f"login 200, token_len={len(tok)}")
# 4. healthz gate 503->200
codes=[]
t0=time.perf_counter()
while time.perf_counter()-t0<180:
    try: c=urllib.request.urlopen("http://127.0.0.1:8003/healthz",timeout=2).status
    except urllib.error.HTTPError as e: c=e.code
    except Exception as ex: c=type(ex).__name__
    codes.append(c)
    if c==200: break
    time.sleep(1)
uniq=[]
for c in codes: uniq.append(c) if not uniq or uniq[-1]!=c else None
print(f"healthz gate: {len(codes)}s, transitions {uniq}")
# 5. hybrid search
req=urllib.request.Request("http://127.0.0.1:8003/api/hybrid/search",data=json.dumps({"query":"Claude Code","top_k":3}).encode(),headers={"Authorization":f"Bearer {tok}","Content-Type":"application/json"})
resp=urllib.request.urlopen(req,timeout=120)
d=json.load(resp); print(f"hybrid 200, status={d.get('status')}, results={len(d.get('results',[]))}")
p.terminate()
try: p.wait(15)
except Exception: p.kill()
print("server stopped")
