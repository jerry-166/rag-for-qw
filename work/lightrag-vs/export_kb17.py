"""从本项目 KB17 导出 110 docs 原文，存 kb17_docs.json。
直接查 PG 拿 enhanced_md_path，然后从本地存储读全文。
"""
import json
import psycopg2
import os

# PG 连接信息（照抄 backend/.env）
PG_DSN = "host=localhost port=5432 dbname=rag_system user=postgres password=1234"
KB_ID = 17

# 本项目本地存储根目录
DOC_STORAGE_DIR = os.path.join("backend", "data", "doc_storage")

conn = psycopg2.connect(PG_DSN)
cur = conn.cursor()

# 查 KB17 所有文档的 enhanced_md_path 和 filename
cur.execute(
    "SELECT id, filename, enhanced_md_path, knowledge_base_id "
    "FROM document WHERE knowledge_base_id = %s ORDER BY created_at",
    (KB_ID,),
)
rows = cur.fetchall()
print(f"KB{KB_ID} 共 {len(rows)} 篇文档")

docs = []
missing = []
for row in rows:
    doc_id, filename, enhanced_md_path, kb_id = row
    if not enhanced_md_path:
        print(f"  [SKIP] {doc_id} {filename} - no enhanced_md_path")
        missing.append(doc_id)
        continue

    # 本项目 LocalStorage.read() 的路径: DOC_STORAGE_DIR / file_path
    full_path = os.path.join(DOC_STORAGE_DIR, enhanced_md_path)
    if not os.path.exists(full_path):
        print(f"  [MISS] {doc_id} {filename} - {full_path} not found")
        missing.append(doc_id)
        continue

    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    docs.append({
        "text": content,
        "metadata": {
            "doc_id": str(doc_id),
            "filename": filename,
            "kb_id": kb_id,
        }
    })
    print(f"  [OK] {doc_id} {filename} - {len(content)} chars")

cur.close()
conn.close()

out_path = os.path.join(os.path.dirname(__file__), "kb17_docs.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(docs, f, ensure_ascii=False, indent=1)

print(f"\n导出完成: {len(docs)} docs, {len(missing)} missing")
print(f"输出: {out_path}")
total_chars = sum(len(d["text"]) for d in docs)
print(f"总字符数: {total_chars}")
