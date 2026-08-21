"""优雅停机 flush 验证：发若干写请求后立刻 SIGTERM 停机，检查最后一批事件落库"""
import json, subprocess, time, urllib.request, urllib.parse, sys
sys.path.insert(0, "backend")
BASE="http://127.0.0.1:8003"
def login(u,p):
    r=urllib.request.Request(BASE+"/api/auth/login",data=urllib.parse.urlencode({"username":u,"password":p}).encode(),method="POST")
    r.add_header("Content-Type","application/x-www-form-urlencoded")
    return json.loads(urllib.request.urlopen(r).read())["access_token"]
tok=login("admin","admin123")
# 记录当前 feedback.like 总数
r=urllib.request.Request(BASE+"/api/audit?action=feedback.like&page_size=1",method="GET"); r.add_header("Authorization","Bearer "+tok)
before=json.loads(urllib.request.urlopen(r).read())["total"]
# 连发 5 个反馈（500ms flush 窗口内立即停机，模拟队列残留）
for i in range(5):
    r=urllib.request.Request(BASE+"/api/agent/feedback",data=json.dumps({"trace_id":"sdflush"+str(i),"value":1}).encode(),method="POST")
    r.add_header("Content-Type","application/json"); r.add_header("Authorization","Bearer "+tok)
    urllib.request.urlopen(r).read()
print("sent 5 feedback; before total:", before)
