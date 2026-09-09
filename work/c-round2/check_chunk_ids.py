"""查 crud_000/091/001 的 chunk_id + 内容"""
import psycopg2
conn = psycopg2.connect('host=localhost port=5432 dbname=rag_system user=postgres password=1234')
cur = conn.cursor()
cur.execute("""
    SELECT id, chunk_index, metadata->>'source', LEFT(content, 80)
    FROM document_chunk
    WHERE knowledge_base_id=65 AND metadata->>'source' IN ('crud_000.md','crud_091.md','crud_001.md')
    ORDER BY metadata->>'source', chunk_index
""")
for r in cur.fetchall():
    print(f'  chunk_id={r[0]} idx={r[1]} source={r[2]} content={r[3]}')
cur.close()
conn.close()
