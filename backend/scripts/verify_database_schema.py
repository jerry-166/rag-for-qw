#!/usr/bin/env python3
"""
验证PostgreSQL数据库架构与设计一致性的脚本
"""

import psycopg2
from config import settings


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


def check_table_exists(cursor, table_name):
    """检查表是否存在"""
    try:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (table_name,))
        return cursor.fetchone()[0]
    except Exception as e:
        print(f"检查表 {table_name} 是否存在失败: {e}")
        return False


def check_column_exists(cursor, table_name, column_name):
    """检查列是否存在"""
    try:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = %s 
                AND column_name = %s
            )
        """, (table_name, column_name))
        return cursor.fetchone()[0]
    except Exception as e:
        print(f"检查表 {table_name} 中的列 {column_name} 是否存在失败: {e}")
        return False


def check_column_type(cursor, table_name, column_name, expected_type):
    """检查列类型是否正确"""
    try:
        cursor.execute("""
            SELECT data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = %s 
            AND column_name = %s
        """, (table_name, column_name))
        result = cursor.fetchone()
        if not result:
            return False
        actual_type = result[0]
        return actual_type == expected_type
    except Exception as e:
        print(f"检查表 {table_name} 中的列 {column_name} 类型失败: {e}")
        return False


def check_index_exists(cursor, index_name):
    """检查索引是否存在"""
    try:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM pg_indexes 
                WHERE indexname = %s
            )
        """, (index_name,))
        return cursor.fetchone()[0]
    except Exception as e:
        print(f"检查索引 {index_name} 是否存在失败: {e}")
        return False


def check_foreign_key_exists(cursor, table_name, constraint_name):
    """检查外键约束是否存在"""
    try:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.table_constraints 
                WHERE table_schema = 'public' 
                AND table_name = %s 
                AND constraint_name = %s 
                AND constraint_type = 'FOREIGN KEY'
            )
        """, (table_name, constraint_name))
        return cursor.fetchone()[0]
    except Exception as e:
        print(f"检查表 {table_name} 中的外键约束 {constraint_name} 是否存在失败: {e}")
        return False


def verify_users_table(cursor):
    """验证用户表结构"""
    print("\n=== 验证 users 表 ===")
    
    # 检查表是否存在
    if not check_table_exists(cursor, 'users'):
        print("✗ users 表不存在")
        return False
    
    # 检查必要列是否存在
    required_columns = [
        ('id', 'integer'),
        ('username', 'text'),
        ('email', 'text'),
        ('password_hash', 'text'),
        ('role', 'text'),
        ('created_at', 'timestamp without time zone')
    ]
    
    all_columns_exist = True
    for column_name, expected_type in required_columns:
        if not check_column_exists(cursor, 'users', column_name):
            print(f"✗ users 表缺少列: {column_name}")
            all_columns_exist = False
        elif not check_column_type(cursor, 'users', column_name, expected_type):
            print(f"✗ users 表列 {column_name} 类型不正确")
            all_columns_exist = False
    
    if all_columns_exist:
        print("✓ users 表结构验证通过")
    
    return all_columns_exist


def verify_document_table(cursor):
    """验证文档表结构"""
    print("\n=== 验证 document 表 ===")
    
    # 检查表是否存在
    if not check_table_exists(cursor, 'document'):
        print("✗ document 表不存在")
        return False
    
    # 检查必要列是否存在
    required_columns = [
        ('id', 'integer'),
        ('filename', 'text'),
        ('file_path', 'text'),
        ('enhanced_md_path', 'text'),
        ('status', 'text'),
        ('metadata', 'jsonb'),
        ('processing_time', 'real'),
        ('user_id', 'integer'),
        ('es_indexed', 'boolean'),
        ('created_at', 'timestamp without time zone'),
        ('updated_at', 'timestamp without time zone')
    ]
    
    all_columns_exist = True
    for column_name, expected_type in required_columns:
        if not check_column_exists(cursor, 'document', column_name):
            print(f"✗ document 表缺少列: {column_name}")
            all_columns_exist = False
        elif not check_column_type(cursor, 'document', column_name, expected_type):
            print(f"✗ document 表列 {column_name} 类型不正确")
            all_columns_exist = False
    
    # 检查外键约束
    if not check_foreign_key_exists(cursor, 'document', 'document_user_id_fkey'):
        print("✗ document 表缺少外键约束: document_user_id_fkey")
        all_columns_exist = False
    
    if all_columns_exist:
        print("✓ document 表结构验证通过")
    
    return all_columns_exist


def verify_document_chunk_table(cursor):
    """验证文档块表结构"""
    print("\n=== 验证 document_chunk 表 ===")
    
    # 检查表是否存在
    if not check_table_exists(cursor, 'document_chunk'):
        print("✗ document_chunk 表不存在")
        return False
    
    # 检查必要列是否存在
    required_columns = [
        ('id', 'integer'),
        ('document_id', 'integer'),
        ('chunk_index', 'integer'),
        ('content', 'text'),
        ('metadata', 'jsonb'),
        ('created_at', 'timestamp without time zone')
    ]
    
    all_columns_exist = True
    for column_name, expected_type in required_columns:
        if not check_column_exists(cursor, 'document_chunk', column_name):
            print(f"✗ document_chunk 表缺少列: {column_name}")
            all_columns_exist = False
        elif not check_column_type(cursor, 'document_chunk', column_name, expected_type):
            print(f"✗ document_chunk 表列 {column_name} 类型不正确")
            all_columns_exist = False
    
    # 检查外键约束
    if not check_foreign_key_exists(cursor, 'document_chunk', 'document_chunk_document_id_fkey'):
        print("✗ document_chunk 表缺少外键约束: document_chunk_document_id_fkey")
        all_columns_exist = False
    
    if all_columns_exist:
        print("✓ document_chunk 表结构验证通过")
    
    return all_columns_exist


def verify_sub_question_table(cursor):
    """验证子问题表结构"""
    print("\n=== 验证 sub_question 表 ===")
    
    # 检查表是否存在
    if not check_table_exists(cursor, 'sub_question'):
        print("✗ sub_question 表不存在")
        return False
    
    # 检查必要列是否存在
    required_columns = [
        ('id', 'integer'),
        ('document_id', 'integer'),
        ('chunk_id', 'integer'),
        ('content', 'text'),
        ('metadata', 'jsonb'),
        ('created_at', 'timestamp without time zone')
    ]
    
    all_columns_exist = True
    for column_name, expected_type in required_columns:
        if not check_column_exists(cursor, 'sub_question', column_name):
            print(f"✗ sub_question 表缺少列: {column_name}")
            all_columns_exist = False
        elif not check_column_type(cursor, 'sub_question', column_name, expected_type):
            print(f"✗ sub_question 表列 {column_name} 类型不正确")
            all_columns_exist = False
    
    # 检查外键约束
    if not check_foreign_key_exists(cursor, 'sub_question', 'sub_question_document_id_fkey'):
        print("✗ sub_question 表缺少外键约束: sub_question_document_id_fkey")
        all_columns_exist = False
    if not check_foreign_key_exists(cursor, 'sub_question', 'sub_question_chunk_id_fkey'):
        print("✗ sub_question 表缺少外键约束: sub_question_chunk_id_fkey")
        all_columns_exist = False
    
    if all_columns_exist:
        print("✓ sub_question 表结构验证通过")
    
    return all_columns_exist


def verify_chunk_summary_table(cursor):
    """验证摘要表结构"""
    print("\n=== 验证 chunk_summary 表 ===")
    
    # 检查表是否存在
    if not check_table_exists(cursor, 'chunk_summary'):
        print("✗ chunk_summary 表不存在")
        return False
    
    # 检查必要列是否存在
    required_columns = [
        ('id', 'integer'),
        ('document_id', 'integer'),
        ('chunk_id', 'integer'),
        ('content', 'text'),
        ('metadata', 'jsonb'),
        ('created_at', 'timestamp without time zone')
    ]
    
    all_columns_exist = True
    for column_name, expected_type in required_columns:
        if not check_column_exists(cursor, 'chunk_summary', column_name):
            print(f"✗ chunk_summary 表缺少列: {column_name}")
            all_columns_exist = False
        elif not check_column_type(cursor, 'chunk_summary', column_name, expected_type):
            print(f"✗ chunk_summary 表列 {column_name} 类型不正确")
            all_columns_exist = False
    
    # 检查外键约束
    if not check_foreign_key_exists(cursor, 'chunk_summary', 'chunk_summary_document_id_fkey'):
        print("✗ chunk_summary 表缺少外键约束: chunk_summary_document_id_fkey")
        all_columns_exist = False
    if not check_foreign_key_exists(cursor, 'chunk_summary', 'chunk_summary_chunk_id_fkey'):
        print("✗ chunk_summary 表缺少外键约束: chunk_summary_chunk_id_fkey")
        all_columns_exist = False
    
    if all_columns_exist:
        print("✓ chunk_summary 表结构验证通过")
    
    return all_columns_exist


def verify_indexes(cursor):
    """验证索引结构"""
    print("\n=== 验证索引 ===")
    
    required_indexes = [
        'idx_document_status',
        'idx_document_user_id',
        'idx_document_chunk_document_id',
        'idx_sub_question_chunk_id',
        'idx_chunk_summary_chunk_id'
    ]
    
    all_indexes_exist = True
    for index_name in required_indexes:
        if not check_index_exists(cursor, index_name):
            print(f"✗ 索引 {index_name} 不存在")
            all_indexes_exist = False
    
    if all_indexes_exist:
        print("✓ 所有索引验证通过")
    
    return all_indexes_exist


def main():
    """主函数"""
    # 连接PostgreSQL数据库
    postgres_conn = connect_postgres()
    if not postgres_conn:
        print("无法连接到PostgreSQL数据库，验证终止")
        return
    
    postgres_cursor = postgres_conn.cursor()
    
    # 验证各个表结构
    print("开始验证数据库架构...")
    
    users_valid = verify_users_table(postgres_cursor)
    document_valid = verify_document_table(postgres_cursor)
    document_chunk_valid = verify_document_chunk_table(postgres_cursor)
    sub_question_valid = verify_sub_question_table(postgres_cursor)
    chunk_summary_valid = verify_chunk_summary_table(postgres_cursor)
    indexes_valid = verify_indexes(postgres_cursor)
    
    # 总体验证结果
    print("\n=== 总体验证结果 ===")
    all_valid = (
        users_valid and
        document_valid and
        document_chunk_valid and
        sub_question_valid and
        chunk_summary_valid and
        indexes_valid
    )
    
    if all_valid:
        print("✓ 数据库架构完全符合设计要求！")
    else:
        print("✗ 数据库架构存在问题，请检查上述错误信息")
    
    # 关闭连接
    postgres_cursor.close()
    postgres_conn.close()
    
    print("\n验证完成！")


if __name__ == "__main__":
    main()
