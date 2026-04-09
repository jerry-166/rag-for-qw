#!/usr/bin/env python3
"""
从SQLite迁移数据到PostgreSQL的脚本
"""

import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from config import settings


def connect_sqlite(db_path):
    """连接到SQLite数据库"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        print(f"成功连接到SQLite数据库: {db_path}")
        return conn
    except Exception as e:
        print(f"连接SQLite数据库失败: {e}")
        return None


def connect_postgres():
    """连接到PostgreSQL数据库"""
    try:
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB
        )
        conn.autocommit = True
        print("成功连接到PostgreSQL数据库")
        return conn
    except Exception as e:
        print(f"连接PostgreSQL数据库失败: {e}")
        return None


def create_postgres_tables(cursor):
    """在PostgreSQL中创建表结构"""
    try:
        # 创建用户表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建文档表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                enhanced_md_path TEXT,
                status TEXT DEFAULT 'uploaded',
                metadata JSONB,
                processing_time REAL,
                user_id INTEGER,
                es_indexed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # 创建文档块表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_chunk (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES document (id)
            )
        ''')
        
        # 创建子问题表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sub_question (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL,
                chunk_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES document (id),
                FOREIGN KEY (chunk_id) REFERENCES document_chunk (id)
            )
        ''')
        
        # 创建摘要表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chunk_summary (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL,
                chunk_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES document (id),
                FOREIGN KEY (chunk_id) REFERENCES document_chunk (id)
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_status ON document (status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_user_id ON document (user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_chunk_document_id ON document_chunk (document_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_question_chunk_id ON sub_question (chunk_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chunk_summary_chunk_id ON chunk_summary (chunk_id)')
        
        print("成功创建PostgreSQL表结构")
        return True
    except Exception as e:
        print(f"创建PostgreSQL表结构失败: {e}")
        return False


def migrate_users(sqlite_conn, postgres_cursor):
    """迁移用户数据"""
    try:
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT * FROM users")
        users = sqlite_cursor.fetchall()
        
        for user in users:
            # 处理可能的NULL值
            username = user['username'] if 'username' in user else None
            email = user['email'] if 'email' in user else None
            password_hash = user['password_hash'] if 'password_hash' in user else None
            role = user['role'] if 'role' in user else 'user'
            created_at = user['created_at'] if 'created_at' in user else None
            
            # 插入到PostgreSQL
            postgres_cursor.execute('''
                INSERT INTO users (username, email, password_hash, role, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (username) DO NOTHING
            ''', (username, email, password_hash, role, created_at))
        
        print(f"成功迁移 {len(users)} 个用户")
        return True
    except Exception as e:
        print(f"迁移用户数据失败: {e}")
        return False


def migrate_documents(sqlite_conn, postgres_cursor):
    """迁移文档数据"""
    try:
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT * FROM document")
        documents = sqlite_cursor.fetchall()
        
        for doc in documents:
            # 处理可能的NULL值和数据类型
            filename = doc['filename'] if 'filename' in doc else None
            file_path = doc['file_path'] if 'file_path' in doc else None
            enhanced_md_path = doc['enhanced_md_path'] if 'enhanced_md_path' in doc else None
            status = doc['status'] if 'status' in doc else 'uploaded'
            metadata = doc['metadata'] if 'metadata' in doc else None
            processing_time = doc['processing_time'] if 'processing_time' in doc else None
            user_id = doc['user_id'] if 'user_id' in doc else None
            es_indexed = doc['es_indexed'] if 'es_indexed' in doc else False
            created_at = doc['created_at'] if 'created_at' in doc else None
            updated_at = doc['updated_at'] if 'updated_at' in doc else None
            
            # 插入到PostgreSQL
            postgres_cursor.execute('''
                INSERT INTO document (filename, file_path, enhanced_md_path, status, metadata, processing_time, user_id, es_indexed, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (filename, file_path, enhanced_md_path, status, metadata, processing_time, user_id, es_indexed, created_at, updated_at))
        
        print(f"成功迁移 {len(documents)} 个文档")
        return True
    except Exception as e:
        print(f"迁移文档数据失败: {e}")
        return False


def migrate_document_chunks(sqlite_conn, postgres_cursor):
    """迁移文档块数据"""
    try:
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT * FROM document_chunk")
        chunks = sqlite_cursor.fetchall()
        
        for chunk in chunks:
            # 处理可能的NULL值
            document_id = chunk['document_id'] if 'document_id' in chunk else None
            chunk_index = chunk['chunk_index'] if 'chunk_index' in chunk else 0
            content = chunk['content'] if 'content' in chunk else ''
            metadata = chunk['metadata'] if 'metadata' in chunk else None
            created_at = chunk['created_at'] if 'created_at' in chunk else None
            
            # 插入到PostgreSQL
            postgres_cursor.execute('''
                INSERT INTO document_chunk (document_id, chunk_index, content, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (document_id, chunk_index, content, metadata, created_at))
        
        print(f"成功迁移 {len(chunks)} 个文档块")
        return True
    except Exception as e:
        print(f"迁移文档块数据失败: {e}")
        return False


def migrate_sub_questions(sqlite_conn, postgres_cursor):
    """迁移子问题数据"""
    try:
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT * FROM sub_question")
        sub_questions = sqlite_cursor.fetchall()
        
        for sq in sub_questions:
            # 处理可能的NULL值
            document_id = sq['document_id'] if 'document_id' in sq else None
            chunk_id = sq['chunk_id'] if 'chunk_id' in sq else None
            content = sq['content'] if 'content' in sq else ''
            metadata = sq['metadata'] if 'metadata' in sq else None
            created_at = sq['created_at'] if 'created_at' in sq else None
            
            # 插入到PostgreSQL
            postgres_cursor.execute('''
                INSERT INTO sub_question (document_id, chunk_id, content, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (document_id, chunk_id, content, metadata, created_at))
        
        print(f"成功迁移 {len(sub_questions)} 个子问题")
        return True
    except Exception as e:
        print(f"迁移子问题数据失败: {e}")
        return False


def migrate_chunk_summaries(sqlite_conn, postgres_cursor):
    """迁移摘要数据"""
    try:
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT * FROM chunk_summary")
        summaries = sqlite_cursor.fetchall()
        
        for summary in summaries:
            # 处理可能的NULL值
            document_id = summary['document_id'] if 'document_id' in summary else None
            chunk_id = summary['chunk_id'] if 'chunk_id' in summary else None
            content = summary['content'] if 'content' in summary else ''
            metadata = summary['metadata'] if 'metadata' in summary else None
            created_at = summary['created_at'] if 'created_at' in summary else None
            
            # 插入到PostgreSQL
            postgres_cursor.execute('''
                INSERT INTO chunk_summary (document_id, chunk_id, content, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (document_id, chunk_id, content, metadata, created_at))
        
        print(f"成功迁移 {len(summaries)} 个摘要")
        return True
    except Exception as e:
        print(f"迁移摘要数据失败: {e}")
        return False


def verify_data_consistency(sqlite_conn, postgres_conn):
    """验证数据一致性"""
    try:
        # 验证用户数量
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT COUNT(*) FROM users")
        sqlite_user_count = sqlite_cursor.fetchone()[0]
        
        postgres_cursor = postgres_conn.cursor()
        postgres_cursor.execute("SELECT COUNT(*) FROM users")
        postgres_user_count = postgres_cursor.fetchone()[0]
        
        print(f"用户数量验证: SQLite={sqlite_user_count}, PostgreSQL={postgres_user_count}")
        
        # 验证文档数量
        sqlite_cursor.execute("SELECT COUNT(*) FROM document")
        sqlite_doc_count = sqlite_cursor.fetchone()[0]
        
        postgres_cursor.execute("SELECT COUNT(*) FROM document")
        postgres_doc_count = postgres_cursor.fetchone()[0]
        
        print(f"文档数量验证: SQLite={sqlite_doc_count}, PostgreSQL={postgres_doc_count}")
        
        # 验证文档块数量
        sqlite_cursor.execute("SELECT COUNT(*) FROM document_chunk")
        sqlite_chunk_count = sqlite_cursor.fetchone()[0]
        
        postgres_cursor.execute("SELECT COUNT(*) FROM document_chunk")
        postgres_chunk_count = postgres_cursor.fetchone()[0]
        
        print(f"文档块数量验证: SQLite={sqlite_chunk_count}, PostgreSQL={postgres_chunk_count}")
        
        # 验证子问题数量
        sqlite_cursor.execute("SELECT COUNT(*) FROM sub_question")
        sqlite_sq_count = sqlite_cursor.fetchone()[0]
        
        postgres_cursor.execute("SELECT COUNT(*) FROM sub_question")
        postgres_sq_count = postgres_cursor.fetchone()[0]
        
        print(f"子问题数量验证: SQLite={sqlite_sq_count}, PostgreSQL={postgres_sq_count}")
        
        # 验证摘要数量
        sqlite_cursor.execute("SELECT COUNT(*) FROM chunk_summary")
        sqlite_summary_count = sqlite_cursor.fetchone()[0]
        
        postgres_cursor.execute("SELECT COUNT(*) FROM chunk_summary")
        postgres_summary_count = postgres_cursor.fetchone()[0]
        
        print(f"摘要数量验证: SQLite={sqlite_summary_count}, PostgreSQL={postgres_summary_count}")
        
        # 检查是否所有数量都匹配
        all_match = (
            sqlite_user_count == postgres_user_count and
            sqlite_doc_count == postgres_doc_count and
            sqlite_chunk_count == postgres_chunk_count and
            sqlite_sq_count == postgres_sq_count and
            sqlite_summary_count == postgres_summary_count
        )
        
        if all_match:
            print("✓ 数据一致性验证通过！")
        else:
            print("✗ 数据一致性验证失败！")
        
        return all_match
    except Exception as e:
        print(f"验证数据一致性失败: {e}")
        return False


def main():
    """主函数"""
    # SQLite数据库路径
    sqlite_db_path = os.path.join(os.path.dirname(__file__), "..", "data", "rag_system.db")
    
    # 连接SQLite数据库
    sqlite_conn = connect_sqlite(sqlite_db_path)
    if not sqlite_conn:
        print("无法连接到SQLite数据库，迁移终止")
        return
    
    # 连接PostgreSQL数据库
    postgres_conn = connect_postgres()
    if not postgres_conn:
        print("无法连接到PostgreSQL数据库，迁移终止")
        sqlite_conn.close()
        return
    
    postgres_cursor = postgres_conn.cursor()
    
    # 创建PostgreSQL表结构
    if not create_postgres_tables(postgres_cursor):
        print("创建PostgreSQL表结构失败，迁移终止")
        sqlite_conn.close()
        postgres_conn.close()
        return
    
    # 迁移数据
    print("开始迁移数据...")
    
    # 按照依赖顺序迁移
    migrate_users(sqlite_conn, postgres_cursor)
    migrate_documents(sqlite_conn, postgres_cursor)
    migrate_document_chunks(sqlite_conn, postgres_cursor)
    migrate_sub_questions(sqlite_conn, postgres_cursor)
    migrate_chunk_summaries(sqlite_conn, postgres_cursor)
    
    # 验证数据一致性
    print("验证数据一致性...")
    verify_data_consistency(sqlite_conn, postgres_conn)
    
    # 关闭连接
    sqlite_conn.close()
    postgres_cursor.close()
    postgres_conn.close()
    
    print("迁移完成！")


if __name__ == "__main__":
    main()
