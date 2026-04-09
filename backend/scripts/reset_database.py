#!/usr/bin/env python3
"""重置数据库脚本"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.database import db
from services.auth import get_password_hash

def reset_database():
    """重置数据库"""
    print("开始重置数据库...")
    
    # 检查数据库连接
    if not db.connect():
        print("数据库连接失败")
        return
    
    # 清空所有表
    print("清空所有表...")
    tables = [
        "workflow_log",
        "chunk_summary",
        "sub_question",
        "document_chunk",
        "user_kb_permission",
        "knowledge_base",
        "document",
        "users"
    ]
    
    for table in tables:
        try:
            db.execute(f"TRUNCATE TABLE {table} CASCADE")
            print(f"清空表 {table} 成功")
        except Exception as e:
            print(f"清空表 {table} 失败: {e}")
    
    # 重新创建表结构
    print("重新创建表结构...")
    db.create_tables()
    
    # 添加测试用户
    print("添加测试用户...")
    users = [
        {
            "username": "admin",
            "email": "admin@example.com",
            "password": "admin123",
            "role": "admin"
        },
        {
            "username": "user",
            "email": "user@example.com",
            "password": "user123",
            "role": "user"
        },
        {
            "username": "jerry666",
            "email": "jerry@example.com",
            "password": "jerry123",
            "role": "user"
        }
    ]
    
    for user in users:
        password_hash = get_password_hash(user["password"])
        user_id = db.add_user(
            username=user["username"],
            email=user["email"],
            password_hash=password_hash,
            role=user["role"]
        )
        if user_id:
            print(f"添加用户 {user['username']} 成功，ID: {user_id}")
            
            # 为每个用户创建一个默认知识库
            kb_id = db.add_knowledge_base(
                user_id=user_id,
                kb_name=f"{user['username']}的默认知识库",
                description=f"{user['username']}的默认知识库",
                metadata={}
            )
            if kb_id:
                print(f"为用户 {user['username']} 创建默认知识库成功，ID: {kb_id}")
        else:
            print(f"添加用户 {user['username']} 失败")
    
    # 关闭数据库连接
    db.close()
    print("数据库重置完成！")

if __name__ == "__main__":
    reset_database()
