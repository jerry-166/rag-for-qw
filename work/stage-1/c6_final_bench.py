import subprocess, time, urllib.request, sys, os
times=[]
for i in range(1,4):
    log=open(f"work/stage-1/c6_final_run{i}.log","wb")
    p=subprocess.Popen([r"backend\.venv\Scripts\python.exe","-m","uvicorn","app:app","--host","127.0.0.1","--port","8003"],cwd="backend",stdout=log,stderr=subprocess.STDOUT)
    t0=time.perf_counter(); code=0
    while time.perf_counter()-t0<60:
        try:
            r=urllib.request.urlopen("http://127.0.0.1:8003/",timeout=1)
            if r.status==200: break
        except Exception: pass
        time.sleep(0.05)
    el=time.perf_counter()-t0
    times.append(el); print(f"run{i}: first200={el:.2f}s")
    p.terminate()
    try: p.wait(15)
    except Exception: p.kill()
    log.close(); time.sleep(2)
print("avg:",round(sum(times)/len(times),2),"s  runs:",[round(t,2) for t in times])
