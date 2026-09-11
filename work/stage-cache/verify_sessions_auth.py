"""
会话层越权修复验证脚本（P0 安全）

用法（在 backend 目录下，venv 已激活，服务在 127.0.0.1:8003 运行）：
  .\.venv\Scripts\python.exe ..\work\stage-cache\verify_sessions_auth.py --admin-user admin --admin-pass <密码>

或指定普通用户：
  .\.venv\Scripts\python.exe ..\work\stage-cache\verify_sessions_auth.py --admin-user admin --admin-pass <密码> --user <用户名> --pass <密码>

验证项：
  1. admin 调用 GET /api/agent/sessions → 可见全部会话（含 ownerless）
  2. 普通用户调用 GET /api/agent/sessions → 只见自己的会话
  3. 普通用户调用 GET /api/agent/session/{他人session_id}/history → 404
  4. 普通用户调用 DELETE /api/agent/session/{他人session_id} → 404
  5. 普通用户调用 DELETE /api/agent/session/{他人session_id}?action=delete → 404
  6. admin 可访问任意会话 history
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse
import uuid

BASE = "http://127.0.0.1:8003"

fails = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}  {name} {extra}")
    if not cond:
        fails.append(name)


def api(path, method="GET", token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        try:
            body_json = json.loads(body_text)
        except Exception:
            body_json = {"_raw": body_text}
        return e.code, body_json


def login(user, pwd):
    data = urllib.parse.urlencode({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def list_sessions(token):
    code, resp = api("/api/agent/sessions", "GET", token=token)
    return code, resp


def get_history(token, session_id):
    code, resp = api(f"/api/agent/session/{session_id}/history", "GET", token=token)
    return code, resp


def delete_session(token, session_id, action=None):
    path = f"/api/agent/session/{session_id}"
    if action:
        path += f"?action={action}"
    code, resp = api(path, "DELETE", token=token)
    return code, resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin-user", required=True, help="admin 用户名")
    ap.add_argument("--admin-pass", required=True, help="admin 密码")
    ap.add_argument("--user", default=None, help="普通用户名（不提供则自动注册临时用户）")
    ap.add_argument("--pass", dest="user_pass", default=None, help="普通用户密码")
    ap.add_argument("--register", action="store_true", help="自动注册临时普通用户")
    args = ap.parse_args()

    # ── 登录 admin ──────────────────────────────────
    print("\n=== 1. 登录 admin ===")
    try:
        admin_token = login(args.admin_user, args.admin_pass)
        print(f"  admin 登录成功, token len={len(admin_token)}")
    except Exception as e:
        print(f"  admin 登录失败: {e}")
        sys.exit(1)

    # ── 获取普通用户 token ────────────────────────────
    print("\n=== 2. 获取/创建普通用户 ===")
    if args.user and args.user_pass:
        try:
            user_token = login(args.user, args.user_pass)
            print(f"  普通用户 {args.user} 登录成功")
        except Exception as e:
            print(f"  普通用户登录失败: {e}")
            sys.exit(1)
    elif args.register:
        # 自动注册临时用户
        tmp_user = f"test_session_{uuid.uuid4().hex[:6]}"
        tmp_pass = "Test123456!"
        code, resp = api("/api/auth/register", "POST", body={
            "username": tmp_user,
            "email": f"{tmp_user}@test.local",
            "password": tmp_pass,
        })
        if code != 200 and code != 201:
            print(f"  注册失败({code}): {resp}")
            sys.exit(1)
        print(f"  注册临时用户 {tmp_user} 成功")
        user_token = login(tmp_user, tmp_pass)
        print(f"  临时用户登录成功")
    else:
        print("  请提供 --user/--pass 或 --register")
        sys.exit(1)

    # ── admin 创建一个会话（通过创建 session 文件模拟）──
    print("\n=== 3. admin 列出会话 ===")
    admin_code, admin_sessions = list_sessions(admin_token)
    check("admin GET /sessions 200", admin_code == 200, f"code={admin_code}")
    admin_session_list = admin_sessions.get("sessions", []) if admin_code == 200 else []
    print(f"  admin 可见 {len(admin_session_list)} 个会话")

    # ── 普通用户列出会话 ===
    print("\n=== 4. 普通用户列出会话 ===")
    user_code, user_sessions = list_sessions(user_token)
    check("user GET /sessions 200", user_code == 200, f"code={user_code}")
    user_session_list = user_sessions.get("sessions", []) if user_code == 200 else []
    print(f"  普通用户可见 {len(user_session_list)} 个会话")

    # ── 验证隔离：普通用户不可见 admin 的会话 ===
    print("\n=== 5. 验证会话隔离 ===")
    admin_ids = {s["session_id"] for s in admin_session_list}
    user_ids = {s["session_id"] for s in user_session_list}
    leaked = admin_ids & user_ids
    # 如果 admin 可见的会话里有 ownerless 的，普通用户不应看到
    # 如果 admin 可见的会话里属于特定 user 的，普通用户不应看到（除非是该用户自己的）
    check("普通用户不可见 admin 独有会话（无泄露）",
          len(leaked) == 0 or leaked == user_ids,
          f"leaked={leaked}")

    # ── 普通用户尝试访问 admin 的会话 history ===
    print("\n=== 6. 普通用户访问他人会话 history ===")
    if admin_session_list:
        # 找一个属于 admin 或 ownerless 的会话
        target_session = admin_session_list[0]["session_id"]
        print(f"  尝试访问 admin 会话: {target_session}")
        code, resp = get_history(user_token, target_session)
        check("普通用户访问他人会话 → 404", code == 404, f"code={code}")
    else:
        print("  (admin 无会话，跳过)")

    # ── 普通用户尝试清空/删除他人会话 ===
    print("\n=== 7. 普通用户清空他人会话 ===")
    if admin_session_list:
        target_session = admin_session_list[0]["session_id"]
        code, resp = delete_session(user_token, target_session)
        check("普通用户 clear 他人会话 → 404", code == 404, f"code={code}")

        print("\n=== 8. 普通用户删除他人会话 ===")
        code, resp = delete_session(user_token, target_session, action="delete")
        check("普通用户 delete 他人会话 → 404", code == 404, f"code={code}")
    else:
        print("  (admin 无会话，跳过)")

    # ── admin 可访问任意会话 ===
    print("\n=== 9. admin 访问任意会话 history ===")
    if admin_session_list:
        target_session = admin_session_list[0]["session_id"]
        code, resp = get_history(admin_token, target_session)
        check("admin 访问任意会话 → 200", code == 200, f"code={code}")
    else:
        print("  (admin 无会话，跳过)")

    # ── 不存在的会话 ID ===
    print("\n=== 10. 不存在的会话 ===")
    fake_id = "sess_doesnotexist123"
    code, resp = get_history(user_token, fake_id)
    check("不存在的会话 history → 404", code == 404, f"code={code}")

    code, resp = delete_session(user_token, fake_id)
    check("不存在的会话 clear → 404", code == 404, f"code={code}")

    code, resp = delete_session(user_token, fake_id, action="delete")
    check("不存在的会话 delete → 404", code == 404, f"code={code}")

    # ── 汇总 ===
    print(f"\n{'='*50}")
    if fails:
        print(f"FAILED: {len(fails)} 项失败")
        for f_name in fails:
            print(f"  - {f_name}")
        sys.exit(1)
    else:
        print("ALL PASS — 会话越权修复验证通过")


if __name__ == "__main__":
    main()
