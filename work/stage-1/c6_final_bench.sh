#!/bin/bash
# 圈6 收尾：3 次启动计时 + 登录/healthz 门/混合检索验证
cd /d/workspace/rag-for-qw/backend
LOG=/d/workspace/rag-for-qw/work/stage-1/verify.log
PY=.venv/Scripts/python.exe
for i in 1 2 3; do
  $PY -m uvicorn app:app --host 127.0.0.1 --port 8003 > /d/workspace/rag-for-qw/work/stage-1/c6_final_run$i.log 2>&1 &
  PID=$!
  T0=$(date +%s.%N)
  # 等首个 200（轮询根路径）
  for j in $(seq 1 300); do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 1 http://127.0.0.1:8003/ 2>/dev/null)
    [ "$CODE" = "200" ] && break
    sleep 0.05
  done
  T1=$(date +%s.%N)
  S=$(echo "$T0 $T1" | awk '{printf "%.2f", $1-$2 * 0 + ($2-$1)}')
  echo "run$i first200=${S}s code=$CODE"
  if [ $i -eq 3 ]; then
    # 登录
    TOKEN=$(curl -s -X POST http://127.0.0.1:8003/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"Stage1@Test"}' | $PY -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
    echo "login token len: ${#TOKEN}"
    # healthz 门：等 200
    HCODES=""
    for j in $(seq 1 600); do
      HC=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8003/healthz)
      HCODES="$HCODES $HC"
      [ "$HC" = "200" ] && break
      sleep 0.5
    done
    echo "healthz codes:$HCODES" | tail -c 300
    # 混合检索
    KB=$(curl -s http://127.0.0.1:8003/api/knowledge-bases -H "Authorization: Bearer $TOKEN" | $PY -c "import sys,json;d=json.load(sys.stdin);print(d[0]['id'] if isinstance(d,list) and d else (d.get('knowledge_bases',[{}])[0].get('id','')))" 2>/dev/null)
    echo "kb_id=$KB"
    curl -s -X POST http://127.0.0.1:8003/api/search/hybrid -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"query\":\"Claude Code\",\"top_k\":3,\"kb_id\":$KB}" -o /d/workspace/rag-for-qw/work/stage-1/c6_final_hybrid.json -w "hybrid http %{http_code}\n"
    head -c 200 /d/workspace/rag-for-qw/work/stage-1/c6_final_hybrid.json; echo
  fi
  kill $PID 2>/dev/null; wait $PID 2>/dev/null
  sleep 1
done
