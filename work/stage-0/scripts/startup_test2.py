import subprocess, time, urllib.request
PY = r"D:\workspace\rag-for-qw\backend\.venv\Scripts\python.exe"
results = []
for i in range(1, 4):
    # ensure port free
    r = subprocess.run(["powershell","-Command","(Get-NetTCPConnection -LocalPort 8003 -State Listen -ErrorAction SilentlyContinue).OwningProcess"], capture_output=True, text=True).stdout.strip()
    assert r == "", f"port 8003 still in use by {r}"
    t0 = time.time()
    p = subprocess.Popen([PY, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"],
                         cwd=r"D:\workspace\rag-for-qw\backend",
                         stdout=open(rf"D:\workspace\rag-for-qw\work\stage-0\server_run{i}.log", "w"),
                         stderr=subprocess.STDOUT)
    while True:
        try:
            resp = urllib.request.urlopen("http://localhost:8003/docs", timeout=2)
            if resp.status == 200: break
        except Exception: pass
        time.sleep(0.2)
        if time.time() - t0 > 300:
            print(f"RUN{i} TIMEOUT"); raise SystemExit(1)
    el = time.time() - t0
    time.sleep(15)  # steady state after warmup (reranker + agents)
    out = subprocess.run(["powershell","-Command",
        f"(Get-Process -Id {p.pid}).WorkingSet64; (Get-Process -Id {p.pid}).PrivateMemorySize64"],
        capture_output=True, text=True).stdout.split()
    rss, pm = (round(int(out[0])/1048576,1), round(int(out[1])/1048576,1)) if len(out)>=2 else (None,None)
    print(f"RUN{i} startup_seconds={el:.2f} RSS_MB={rss} PrivateMB={pm}")
    results.append(el)
    subprocess.run(["taskkill","/F","/T","/PID",str(p.pid)], capture_output=True)
    time.sleep(8)
print(f"MEAN={sum(results)/len(results):.2f} individual={['%.2f'%x for x in results]}")
