#!/bin/bash
# 启动耗时测试: 3 次
cd /d/workspace/rag-for-qw/backend
PY=/d/workspace/rag-for-qw/backend/.venv/Scripts/python.exe
for i in 1 2 3; do
  START=$(date +%s.%N)
  $PY -m uvicorn app:app --host 0.0.0.0 --port 8003 > /d/workspace/rag-for-qw/work/stage-0/server_run$i.log 2>&1 &
  PID=$!
  while true; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:8003/health 2>/dev/null)
    if [ "$CODE" = "200" ]; then break; fi
    # also try /docs
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:8003/docs 2>/dev/null)
    if [ "$CODE" = "200" ]; then break; fi
    sleep 0.2
  done
  END=$(date +%s.%N)
  ELAPSED=$(echo "$END - $START" | bc)
  echo "RUN$i startup_seconds=$ELAPSED"
  # wait for steady state, record RSS
  sleep 10
  powershell -Command "Get-Process -Id $PID -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,@{n='WS_MB';e={[math]::Round(\$_.WorkingSet64/1MB,1)}},@{n='PM_MB';e={[math]::Round(\$_.PrivateMemorySize64/1MB,1)}} | Format-List"
  sleep 3
  powershell -Command "Get-Process -Id $PID -ErrorAction SilentlyContinue | Select-Object Id,@{n='WS_MB';e={[math]::Round(\$_.WorkingSet64/1MB,1)}},@{n='PM_MB';e={[math]::Round(\$_.PrivateMemorySize64/1MB,1)}} | Format-List"
  taskkill //F //PID $PID //T 2>/dev/null
  sleep 3
done
