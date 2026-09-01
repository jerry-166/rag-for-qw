"""
存量会话迁移脚本 — 给缺少 user_id 字段的会话文件补充 user_id=null（ownerless）

幂等：可重复运行，已有 user_id 字段的会话不会被修改。

用法：
    cd backend
    .venv\\Scripts\\python.exe scripts\\migrate_sessions_owner.py

迁移规则：
    - 无 user_id 字段 → 设 user_id = null（ownerless，仅 admin 可见）
    - 有 user_id 字段 → 保留不变
"""

import json
import sys
import os
from pathlib import Path

# 添加 backend 目录到搜索路径
backend_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(backend_dir))

from agent.claw_agent.memory.session_store import SessionStore


def main():
    store = SessionStore()
    sessions_dir = store.sessions_dir

    if not sessions_dir.exists():
        print(f"[migrate] sessions 目录不存在: {sessions_dir}")
        return

    json_files = list(sessions_dir.glob("*.json"))
    print(f"[migrate] 扫描到 {len(json_files)} 个会话文件")

    migrated = 0
    skipped = 0
    errors = 0

    for path in json_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "user_id" in data:
                # 已有 user_id 字段，跳过
                skipped += 1
                continue

            # 补充 user_id = null（ownerless）
            data["user_id"] = None

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            migrated += 1
            print(f"  [migrated] {path.name} → user_id=null")

        except Exception as e:
            errors += 1
            print(f"  [ERROR] {path.name}: {e}")

    print(f"\n[migrate] 完成: 迁移 {migrated} 个, 跳过 {skipped} 个, 错误 {errors} 个")


if __name__ == "__main__":
    main()
