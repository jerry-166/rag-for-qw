"""
测试集管理页面后端 — 端到端验证脚本

验证项：
1. 从 session 提取测试集 → 确认有 pending 样本
2. approve 单条 → 确认 status=approved
3. generate-gt → 确认返回非空字符串
4. 导入 ours 格式 + ragas 格式小样例 → 确认导入成功
5. /run 门控 → approved<30 时返回 400

运行方式：
  cd d:\workspace\rag-for-qw\backend
  ..\.venv\Scripts\python.exe ..\work\evaluation-page\verify_backend.py
"""

import json
import sys
import os
import time
from pathlib import Path

# 把 backend 加到 path
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

os.chdir(str(BACKEND_DIR))  # 切到 backend 目录，确保 config .env 能加载

import requests
from services.auth import create_access_token

BASE_URL = "http://127.0.0.1:8003"

# 生成测试用 token（用真实存在的 admin 用户）
_token = create_access_token(data={"sub": "admin", "user_id": 1, "role": "admin"})
HEADERS = {"Authorization": f"Bearer {_token}"}

results = {}


def step(name, ok, detail=""):
    results[name] = {"ok": ok, "detail": detail}
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: {detail}")


# ─────────────────────────────────────────────────────────────
# 1. 从 session 提取测试集
# ─────────────────────────────────────────────────────────────
print("\n=== Step 1: 从 session 提取测试集 ===")
try:
    resp = requests.post(
        f"{BASE_URL}/api/evaluation/dataset/from-sessions",
        json={"max_samples": 20, "save": True},
        headers=HEADERS,
        timeout=60,
    )
    if resp.status_code == 200:
        data = resp.json()
        ds_name = data.get("dataset_name", "")
        stats = data.get("stats", {})
        total = stats.get("total", 0)
        step("from_sessions", total > 0, f"dataset={ds_name}, total={total}, stats={json.dumps(stats, ensure_ascii=False)}")
    else:
        step("from_sessions", False, f"HTTP {resp.status_code}: {resp.text[:200]}")
        ds_name = None
except Exception as e:
    step("from_sessions", False, f"Exception: {e}")
    ds_name = None


# ─────────────────────────────────────────────────────────────
# 2. GET samples?status=pending → 确认有 pending 样本
# ─────────────────────────────────────────────────────────────
print("\n=== Step 2: GET samples?status=pending ===")
if ds_name:
    try:
        resp = requests.get(
            f"{BASE_URL}/api/evaluation/dataset/{ds_name}/samples",
            params={"status": "pending", "page": 1, "page_size": 20},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            pending_count = data.get("total", 0)
            step("get_pending", pending_count > 0, f"pending samples={pending_count}")
        else:
            step("get_pending", False, f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        step("get_pending", False, f"Exception: {e}")
else:
    step("get_pending", False, "No dataset from step 1")


# ─────────────────────────────────────────────────────────────
# 3. POST sample/0/approve → 重新 GET 确认 status=approved
# ─────────────────────────────────────────────────────────────
print("\n=== Step 3: approve sample 0 ===")
if ds_name:
    try:
        resp = requests.post(
            f"{BASE_URL}/api/evaluation/dataset/{ds_name}/sample/0/approve",
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            sample = resp.json().get("sample", {})
            approved = sample.get("status") == "approved"
            step("approve", approved, f"sample[0].status={sample.get('status')}")
        else:
            step("approve", False, f"HTTP {resp.status_code}: {resp.text[:200]}")

        # 重新 GET 确认
        resp2 = requests.get(
            f"{BASE_URL}/api/evaluation/dataset/{ds_name}/sample/0",
            headers=HEADERS,
            timeout=10,
        )
        if resp2.status_code == 200:
            sample2 = resp2.json().get("sample", {})
            persisted = sample2.get("status") == "approved"
            step("approve_persist", persisted, f"reloaded sample[0].status={sample2.get('status')}")
        else:
            step("approve_persist", False, f"HTTP {resp2.status_code}")
    except Exception as e:
        step("approve", False, f"Exception: {e}")
else:
    step("approve", False, "No dataset")


# ─────────────────────────────────────────────────────────────
# 4. POST sample/0/generate-gt → 确认返回非空字符串
# ─────────────────────────────────────────────────────────────
print("\n=== Step 4: generate-gt for sample 0 ===")
if ds_name:
    try:
        resp = requests.post(
            f"{BASE_URL}/api/evaluation/dataset/{ds_name}/sample/0/generate-gt",
            headers=HEADERS,
            timeout=120,
        )
        if resp.status_code == 200:
            gt = resp.json().get("ground_truth", "")
            step("generate_gt", bool(gt), f"ground_truth length={len(gt)}, preview={gt[:80]}...")
        else:
            step("generate_gt", False, f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        step("generate_gt", False, f"Exception: {e}")
else:
    step("generate_gt", False, "No dataset")


# ─────────────────────────────────────────────────────────────
# 5. POST import ours 格式 + ragas 格式
# ─────────────────────────────────────────────────────────────
print("\n=== Step 5: import ours + ragas format ===")

# ours 格式小样例
ours_data = {
    "name": "verify_ours",
    "samples": [
        {
            "question": f"测试问题 {i}",
            "answer": f"测试答案 {i}",
            "contexts": [f"上下文片段 {i}"],
            "ground_truth": f"标准答案 {i}",
            "metadata": {"source": "manual"},
            "status": "approved",
        }
        for i in range(1, 4)
    ],
}
ours_json = json.dumps(ours_data, ensure_ascii=False)

try:
    resp = requests.post(
        f"{BASE_URL}/api/evaluation/dataset/import",
        data={"fmt": "auto", "dataset_name": "verify_ours_import"},
        files={"file": ("verify_ours.json", ours_json.encode("utf-8"), "application/json")},
        headers=HEADERS,
        timeout=15,
    )
    if resp.status_code == 200:
        rdata = resp.json()
        ok = rdata.get("count", 0) == 3 and rdata.get("format") == "ours"
        step("import_ours", ok, f"format={rdata.get('format')}, count={rdata.get('count')}, name={rdata.get('dataset_name')}")
    else:
        step("import_ours", False, f"HTTP {resp.status_code}: {resp.text[:200]}")
except Exception as e:
    step("import_ours", False, f"Exception: {e}")

# ragas 格式小样例
ragas_data = [
    {"question": f"RAGAS 问题 {i}", "answer": f"RAGAS 答案 {i}", "contexts": [f"RAGAS 上下文 {i}"], "ground_truth": f"RAGAS GT {i}"}
    for i in range(1, 4)
]
ragas_json = json.dumps(ragas_data, ensure_ascii=False)

try:
    resp = requests.post(
        f"{BASE_URL}/api/evaluation/dataset/import",
        data={"fmt": "auto", "dataset_name": "verify_ragas_import"},
        files={"file": ("verify_ragas.json", ragas_json.encode("utf-8"), "application/json")},
        headers=HEADERS,
        timeout=15,
    )
    if resp.status_code == 200:
        rdata = resp.json()
        ok = rdata.get("count", 0) == 3 and rdata.get("format") == "ragas"
        step("import_ragas", ok, f"format={rdata.get('format')}, count={rdata.get('count')}, name={rdata.get('dataset_name')}")
    else:
        step("import_ragas", False, f"HTTP {resp.status_code}: {resp.text[:200]}")
except Exception as e:
    step("import_ragas", False, f"Exception: {e}")


# ─────────────────────────────────────────────────────────────
# 6. POST /run 门控 → approved<30 时返回 400
# ─────────────────────────────────────────────────────────────
print("\n=== Step 6: /run gating (approved < 30) ===")
if ds_name:
    try:
        resp = requests.post(
            f"{BASE_URL}/api/evaluation/run",
            json={"dataset_name": ds_name, "auto_fill": False},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code == 400:
            detail = resp.json().get("detail", "")
            ok = "不足 30" in detail or "统计显著性" in detail
            step("run_gating", ok, f"HTTP 400: {detail[:120]}")
        else:
            step("run_gating", False, f"Expected 400, got HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        step("run_gating", False, f"Exception: {e}")
else:
    step("run_gating", False, "No dataset")


# ─────────────────────────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
total_steps = len(results)
passed = sum(1 for v in results.values() if v["ok"])
print(f"Total: {passed}/{total_steps} passed")

# 写 JSON
out_path = Path(__file__).parent / "verify_backend.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"Results written to: {out_path}")
