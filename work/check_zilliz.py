# -*- coding: utf-8 -*-
"""诊断：Zilliz Cloud 集合与数据核对"""
import sys, json
from pymilvus import connections, utility, db, Collection

URI = "https://in03-7dc201e632cee68.serverless.aws-eu-central-1.cloud.zilliz.com"
TOKENS = [
    "db_7dc201e632cee68:Sd6.1%|(SRWUy?C7---",   # txt 里的 username:password
]

connected = None
for tok in TOKENS:
    try:
        connections.connect(alias="diag", uri=URI, token=tok, secure=True, timeout=30)
        connected = tok
        print(f"[OK] 连接成功 (token=...{tok[-6:]})")
        break
    except Exception as e:
        print(f"[FAIL] token ...{tok[-6:]} -> {type(e).__name__}: {e}")

if not connected:
    sys.exit(1)

# 1. 数据库列表
try:
    dbs = db.list_database(using="diag")
    print("\n[数据库列表]", dbs)
except Exception as e:
    print("[数据库列表失败]", e)

# 2. 尝试各数据库下的集合
for dbname in dbs or ["default"]:
    try:
        db.using_database(dbname, using="diag")
    except Exception as e:
        print(f"[using_database {dbname} 失败] {e}")
        continue
    try:
        cols = utility.list_collections(using="diag")
        print(f"\n[数据库 {dbname}] 集合列表: {cols}")
        for cname in cols:
            try:
                c = Collection(cname, using="diag")
                stats = c.num_entities
                print(f"    - {cname}: num_entities={stats}")
            except Exception as e:
                print(f"    - {cname}: 查询实体数失败 {type(e).__name__}: {e}")
    except Exception as e:
        print(f"[数据库 {dbname}] 集合列表失败: {e}")
