import subprocess, time, urllib.request, urllib.error, sys

def poll(url, to=240):
    s=time.time()
    while time.time()-s<to:
        try:
            r=urllib.request.urlopen(url,timeout=2); return r.status
        except urllib.error.HTTPError as e: return e.code
        except Exception: time.sleep(0.15)
    return None

for i in range(3):
    t0=time.time()
    p=subprocess.Popen([r'.venv\Scripts\python.exe','app.py'],stdout=open(rf'D:\workspace\rag-for-qw\work\stage-1\boot_bench{i+1}.log','w'),stderr=subprocess.STDOUT)
    root_t=None; hz503=None; hz200=None; login_code=None
    while time.time()-t0<240:
        c=poll('http://127.0.0.1:8003/',2)
        if c==200: root_t=time.time()-t0; break
    while time.time()-t0<240:
        c=poll('http://127.0.0.1:8003/healthz',2)
        if c==503 and hz503 is None: hz503=time.time()-t0
        if c==200: hz200=time.time()-t0; break
        time.sleep(0.3)
    # login immediately after service up
    if root_t:
        req=urllib.request.Request('http://127.0.0.1:8003/api/auth/login',data=b'username=admin&password=Stage1%40Test',headers={'Content-Type':'application/x-www-form-urlencoded'})
        try: login_code=urllib.request.urlopen(req,timeout=15).status
        except urllib.error.HTTPError as e: login_code=e.code
        except Exception as e: login_code=str(e)[:40]
    print(f"run{i+1}: root200={root_t:.2f}s healthz503@{hz503 and round(hz503,2)}s healthz200={hz200 and round(hz200,2)}s login@first-avail={login_code}",flush=True)
    p.terminate()
    try: p.wait(15)
    except: p.kill()
    time.sleep(2)
