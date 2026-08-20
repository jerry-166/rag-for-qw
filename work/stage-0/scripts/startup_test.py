import subprocess, time, urllib.request, sys, os
PY = r"D:\workspace\rag-for-qw\backend\.venv\Scripts\python.exe"
results = []
for i in range(1, 4):
    t0 = time.time()
    p = subprocess.Popen([PY, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"],
                         cwd=r"D:\workspace\rag-for-qw\backend",
                         stdout=open(rf"D:\workspace\rag-for-qw\work\stage-0\server_run{i}.log", "w"),
                         stderr=subprocess.STDOUT)
    while True:
        try:
            r = urllib.request.urlopen("http://localhost:8003/health", timeout=2)
            if r.status == 200:
                break
        except Exception:
            try:
                r = urllib.request.urlopen("http://localhost:8003/docs", timeout=2)
                if r.status == 200: break
            except Exception: pass
        time.sleep(0.2)
    el = time.time() - t0
    # wait for steady state (reranker + agents warmup)
    time.sleep(15)
    rss = pm = None
    out = subprocess.run(["powershell","-Command",
        f"(Get-Process -Id {p.pid}).WorkingSet64; (Get-Process -Id {p.pid}).PrivateMemorySize64"],
        capture_output=True, text=True).stdout.split()
    if len(out) >= 2:
        rss, pm = int(out[0])/1048576, int(out[1])/1048576
    print(f"RUN{i} startup_seconds={el:.2f} RSS_MB={rss and round(rss,1)} PrivateMB={pm and round(pm,1)}")
    results.append(el)
    p.kill()
    try: p.wait(10)
    except Exception: pass
    time.sleep(5)
print(f"MEAN={sum(results)/len(results):.2f} individual={['%.2f'%x for x in results]}")
