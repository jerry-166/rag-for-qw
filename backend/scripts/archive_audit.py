"""审计日志归档脚本（文档 07 §6 保留策略）

将超过 AUDIT_RETENTION_DAYS（默认 365 天）的审计事件导出为 gzip JSON 后从表内删除。
归档文件写入 backend/archives/audit/audit_archive_<ts>.json.gz。

用法：
    python scripts/archive_audit.py            # 按配置保留期执行
    python scripts/archive_audit.py --dry-run  # 只统计不动数据
    python scripts/archive_audit.py --days 0   # 归档全部（危险，仅测试）
"""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

from services.database import db  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None,
                        help="保留天数（默认取 AUDIT_RETENTION_DAYS 配置，缺省 365）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不导出不删除")
    args = parser.parse_args()

    days = args.days
    if days is None:
        env_val = os.getenv("AUDIT_RETENTION_DAYS")
        days = int(env_val) if env_val and str(env_val).strip().isdigit() else 365

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    row = db.fetchone(
        "SELECT COUNT(*) AS cnt FROM audit_log WHERE occurred_at < %s", (cutoff_str,))
    total = row["cnt"] if row else 0
    print(f"保留期 {days} 天（cutoff={cutoff_str}），超期事件: {total} 条")

    if args.dry_run or total == 0:
        print("dry-run 或无超期数据，结束。")
        return

    # 流式导出（分批 1000 条）
    out_dir = Path("archives/audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"audit_archive_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json.gz"
    exported = 0
    max_id_row = db.fetchone(
        "SELECT MAX(id) AS mx FROM audit_log WHERE occurred_at < %s", (cutoff_str,))
    max_id = max_id_row["mx"] if max_id_row else None
    if max_id is None:
        print("无数据可归档。")
        return

    with gzip.open(out_file, "wt", encoding="utf-8") as f:
        cursor_id = 0
        while True:
            rows = db.fetchall(
                "SELECT * FROM audit_log WHERE id > %s AND id <= %s AND occurred_at < %s ORDER BY id LIMIT 1000",
                (cursor_id, max_id, cutoff_str))
            if not rows:
                break
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                exported += 1
            cursor_id = rows[-1]["id"]
    print(f"导出 {exported} 条 -> {out_file} ({out_file.stat().st_size} bytes)")

    if exported != total:
        print(f"[警告] 导出数 {exported} != 统计数 {total}，跳过删除（安全起见）")
        return

    # 校验导出文件可完整读回后再删除
    with gzip.open(out_file, "rt", encoding="utf-8") as f:
        recount = sum(1 for _ in f)
    if recount != total:
        print(f"[警告] 回读校验 {recount} != {total}，跳过删除")
        return
    print(f"回读校验通过（{recount} 条）")

    db.cursor.execute("DELETE FROM audit_log WHERE id <= %s AND occurred_at < %s", (max_id, cutoff_str))
    db.conn.commit()
    print(f"已从 audit_log 删除 {db.cursor.rowcount} 条（归档文件保留：{out_file}）")


if __name__ == "__main__":
    main()
