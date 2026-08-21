"""Stage 4 第一圈：审计中心全局验收脚本（真实命令，输出到 verify.log）"""
import json, sys, time, io, urllib.request, urllib.parse, urllib.error

BASE = "http://127.0.0.1:8003"
OUT = io.StringIO()

def log(msg=""):
    print(msg)
    OUT.write(msg + "\n")

def req(method, path, token=None, body=None, raw=None, ctype="application/json", headers=None):
    url = BASE + path
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    elif raw is not None:
        data = raw
    r = urllib.request.Request(url, data=data, method=method)
    if body is not None or raw is not None:
        r.add_header("Content-Type", ctype)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            txt = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(txt), dict(resp.headers)
            except Exception:
                return resp.status, txt, dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8")), dict(e.headers)
        except Exception:
            return e.code, None, {}

def login(u, p):
    data = urllib.parse.urlencode({"username": u, "password": p}).encode()
    s, d, _ = req("POST", "/api/auth/login", raw=data, ctype="application/x-www-form-urlencoded")
    assert s == 200, f"login {u} failed: {s} {d}"
    return d["access_token"], d["user_id"]

def audit_query(tok, **params):
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v not in (None, ""))
    s, d, _ = req("GET", f"/api/audit?{qs}", tok)
    assert s == 200, f"audit query failed: {s} {d}"
    return d

def wait_action(tok, action, request_id=None, tries=10, extra=None):
    """轮询等待审计落库（异步管道 500ms 批量）"""
    for _ in range(tries):
        d = audit_query(tok, action=action, request_id=request_id, page_size=5)
        items = d.get("items", [])
        if extra:
            items = [i for i in items if extra(i)]
        if items:
            return items
        time.sleep(0.7)
    return []

def fmt(ev):
    d = ev.get("detail")
    return f"  id={ev['id']} action={ev['action']} user={ev.get('user_id')} kb={ev.get('kb_id')} rid={ev.get('request_id')} detail={json.dumps(d, ensure_ascii=False)[:220] if d else None}"

# ============ 0. 登录 ============
log("== 0. 登录 ==")
admin_tok, admin_id = login("admin", "admin123")
log(f"admin login ok (user_id={admin_id})")

# 先注册一个普通用户（本轮专用，幂等）
ts = str(int(time.time()))[-7:]
user2 = f"aud{ts}"
s, d, _ = req("POST", "/api/auth/register", body={"username": user2, "email": f"{user2}@t.cn", "password": "Passw0rd!xyz"})
log(f"register {user2}: {s}")
assert s == 200
u2_tok, u2_id = login(user2, "Passw0rd!xyz")
log(f"{user2} login ok (user_id={u2_id})")

# 登录失败路径
s, d, _ = req("POST", "/api/auth/login",
              raw=urllib.parse.urlencode({"username": "admin", "password": "wrong"}).encode(),
              ctype="application/x-www-form-urlencoded")
log(f"login failed path: {s} (expect 401)")

log("\n== 1. 事件目录走查（做了什么 vs 记了什么）==")

# --- KB CRUD ---
s, d, _ = req("POST", "/api/knowledge-bases", admin_tok,
              {"kb_name": "审计验收KB", "description": "stage4-circle1", "chunk_strategy": "recursive", "enhancers": ["summary"]})
kb_id = d.get("kb_id"); log(f"kb.create: {s} kb_id={kb_id}")
evs = wait_action(admin_tok, "kb.create", extra=lambda e: e.get("kb_id") == kb_id)
log(f"audit kb.create: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

s, d, _ = req("PUT", f"/api/knowledge-bases/{kb_id}", admin_tok,
              {"kb_name": "审计验收KB-改", "chunk_strategy": "markdown"})
log(f"kb.update: {s}")
evs = wait_action(admin_tok, "kb.update", extra=lambda e: e.get("kb_id") == kb_id)
log(f"audit kb.update: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

# --- doc upload (markdown) ---
md = ("# 审计验收文档\n\n## 简介\n这是一个用于 Stage 4 审计验收的 Markdown 文档。\n\n"
      "## RAG\nRAG 通过检索增强生成。\n\n## Milvus\nMilvus 是向量数据库，支持标量过滤。\n" * 3)
boundary = "----stage4boundary"
body_bytes = (
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"kb_id\"\r\n\r\n{kb_id}\r\n"
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audit_test.md\"\r\n"
    f"Content-Type: text/markdown\r\n\r\n{md}\r\n--{boundary}--\r\n"
).encode("utf-8")
s, d, _ = req("POST", "/api/upload/markdown", admin_tok, raw=body_bytes,
              ctype=f"multipart/form-data; boundary={boundary}")
doc_id = d.get("file_id"); log(f"doc.upload(markdown): {s} doc_id={doc_id}")
evs = wait_action(admin_tok, "doc.upload", extra=lambda e: e.get("resource_id") == str(doc_id))
log(f"audit doc.upload: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

# --- split / generate / import ---
s, d, _ = req("POST", f"/api/process/split/{doc_id}", admin_tok, {})
log(f"process.split: {s} chunks={d.get('chunk_count', d) if isinstance(d, dict) else d}")
evs = wait_action(admin_tok, "process.split.done", extra=lambda e: e.get("resource_id") == str(doc_id))
log(f"audit process.split.done: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

s, d, _ = req("POST", f"/api/process/generate/{doc_id}", admin_tok, {})
log(f"process.generate: {s}")
evs = wait_action(admin_tok, "process.generate.done", extra=lambda e: str(doc_id) in str(e.get("detail", {}).get("document_id", "")) or e.get("resource_id") == str(doc_id))
evs2 = wait_action(admin_tok, "process.generate.api_done")
log(f"audit process.generate.done: {'PASS' if evs or evs2 else 'MISS'}")
[log(fmt(e)) for e in (evs or evs2)]

s, d, _ = req("POST", f"/api/process/import/{doc_id}", admin_tok, {})
log(f"process.import: {s}")
evs = wait_action(admin_tok, "process.import.done", extra=lambda e: e.get("resource_id") == str(doc_id))
log(f"audit process.import.done: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

# --- 三种检索（request_id 串联验证也在其中之一）---
RID = "stage4rid" + ts
s, d, h = req("POST", "/api/milvus/query", admin_tok,
              {"query": "什么是RAG检索增强生成", "knowledge_base_id": kb_id, "limit": 3, "retrieval_mode": "native"},
              headers={"X-Request-ID": RID})
log(f"search native: {s} results={len(d.get('results', [])) if isinstance(d, dict) else '?'} resp_rid={h.get('X-Request-ID')}")
evs = wait_action(admin_tok, "request.write", request_id=RID)
log(f"audit request.write(native) with explicit RID: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

s, d, _ = req("POST", "/api/milvus/query", admin_tok,
              {"query": "什么是RAG检索增强生成", "knowledge_base_id": kb_id, "limit": 3, "retrieval_mode": "advanced"})
log(f"search advanced: {s}")
s, d, _ = req("POST", "/api/hybrid/search", admin_tok,
              {"query": "Milvus向量数据库", "knowledge_base_id": kb_id, "limit": 3, "use_rerank": False})
log(f"search hybrid: {s}")

# --- agent 对话 ---
s, d, _ = req("POST", "/api/agent/chat", admin_tok,
              {"query": "什么是RAG？", "agent_type": "claw", "knowledge_base_id": kb_id})
log(f"agent.chat: {s}")
evs = wait_action(admin_tok, "agent.chat")
log(f"audit agent.chat: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

# --- feedback ---
s, d, _ = req("POST", "/api/agent/feedback", admin_tok,
              {"trace_id": "stage4trace" + ts, "value": 1, "comment": "验收点赞"})
log(f"feedback.like: {s}")
evs = wait_action(admin_tok, "feedback.like")
log(f"audit feedback.like: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

# --- settings 修改（脱敏验证：敏感 key）---
s, d, _ = req("PUT", "/api/settings", admin_tok,
              {"configs": [{"key": "RETRIEVAL_TOP_K", "value": 7},
                           {"key": "LITELLM_API_KEY", "value": "sk-audit1234567890xyz"}]})
log(f"settings.update: {s} updated={list((d or {}).get('updated', {}).keys())}")
evs = wait_action(admin_tok, "settings.update")
log(f"audit settings.update: {'PASS' if evs else 'MISS'}")
det = evs[0].get("detail") if evs else None
log(f"  detail: {json.dumps(det, ensure_ascii=False)[:400]}")
if det:
    for ch in det.get("changes", []):
        if ch.get("key") == "LITELLM_API_KEY":
            after = str(ch.get("after"))
            ok = "sk-a" in after and "***" in after and "1234567890xyz" not in after
            log(f"  敏感 key={ch['key']} after={after} -> 脱敏 {'PASS' if ok else 'FAIL'}")
# 恢复（清除运行时覆盖）
req("PUT", "/api/settings", admin_tok, {"configs": [{"key": "LITELLM_API_KEY", "value": None}]})

# --- 普通用户权限过滤 ---
log("\n== 4. 权限过滤 ==")
d2 = audit_query(u2_tok, page_size=200)
users_seen = {i.get("user_id") for i in d2["items"]}
log(f"normal user {user2}(id={u2_id}) /api/audit: total={d2['total']} user_ids={users_seen} -> "
    f"{'PASS' if users_seen <= {u2_id, None} else 'FAIL'}")
s, d, _ = req("GET", "/api/audit?user_id=" + str(admin_id), u2_tok)
log(f"normal user queries others: {s} (expect 403) -> {'PASS' if s == 403 else 'FAIL'}")
s, d, _ = req("GET", "/api/audit/export?format=csv", u2_tok)
log(f"normal user export: {s} (expect 403) -> {'PASS' if s == 403 else 'FAIL'}")
s, d, _ = req("GET", "/api/audit/stats", u2_tok)
log(f"normal user stats: {s} (expect 403) -> {'PASS' if s == 403 else 'FAIL'}")
s, d, _ = req("GET", "/api/audit/stats", admin_tok)
log(f"admin stats: {s} -> {json.dumps(d, ensure_ascii=False)[:200] if s == 200 else d}")
s, d, h = req("GET", "/api/audit/export?format=csv", admin_tok)
log(f"admin export: {s} bytes={len(str(d))} starts={str(d)[:60]!r}")

# --- doc/KB delete ---
s, d, _ = req("DELETE", f"/api/documents/{doc_id}", admin_tok)
log(f"doc.delete: {s}")
evs = wait_action(admin_tok, "doc.delete", extra=lambda e: e.get("resource_id") == str(doc_id))
log(f"audit doc.delete: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

s, d, _ = req("DELETE", f"/api/knowledge-bases/{kb_id}", admin_tok)
log(f"kb.delete: {s}")
evs = wait_action(admin_tok, "kb.delete", extra=lambda e: e.get("kb_id") == kb_id)
log(f"audit kb.delete: {'PASS' if evs else 'MISS'}"); [log(fmt(e)) for e in evs]

# --- auth 事件 ---
log("\n== auth 事件 ==")
for act in ("auth.login", "auth.login_failed", "auth.register"):
    evs = wait_action(admin_tok, act, tries=8)
    log(f"audit {act}: {'PASS' if evs else 'MISS'} ({len(evs)} 条)")
    if evs: log(fmt(evs[0]))

# --- request_id 串联核对（native 检索 + agent chat 的兜底事件）---
log("\n== 2. request_id 串联 ==")
d_all = audit_query(admin_tok, request_id=RID, page_size=50)
log(f"request_id={RID} 共 {d_all['total']} 条事件，actions={[i['action'] for i in d_all['items']]}")

# --- 全库明文 grep（脱敏第 2 验证点）---
log("\n== 3. 脱敏全量复查 ==")
d_all = audit_query(admin_tok, page_size=200)
hits = []
for it in d_all["items"]:
    txt = json.dumps(it.get("detail"), ensure_ascii=False)
    if "sk-audit1234567890xyz" in txt:
        hits.append(it["id"])
log(f"全量 200 条 detail 中 grep 明文 key: {'PASS(无)' if not hits else 'FAIL ' + str(hits)}")

with open("../work/stage-4/verify-run.log", "w", encoding="utf-8") as f:
    f.write(OUT.getvalue())
log("\nDONE -> work/stage-4/verify-run.log")
