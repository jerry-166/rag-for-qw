#!/usr/bin/env python3
"""检查密码哈希值脚本"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.database import db
from services.auth import get_password_hash, verify_password

def check_password():
    """检查密码哈希值"""
    print("开始检查密码哈希值...")
    
    # 检查数据库连接
    if not db.connect():
        print("数据库连接失败")
        return
    
    # 获取所有用户
    users = db.fetchall("SELECT * FROM users")
    print(f"数据库中的用户数量: {len(users)}")
    
    for user in users:
        print(f"\n用户: {user}")
        print(f"用户名: {user['username']}")
        print(f"密码哈希: {user['password_hash']}")
        print(f"密码哈希类型: {type(user['password_hash'])}")
        print(f"密码哈希长度: {len(user['password_hash'])}")
        
        # 测试密码验证
        try:
            # 尝试使用正确的密码验证
            if user['username'] == 'admin':
                password = 'admin123'
            elif user['username'] == 'user':
                password = 'user123'
            elif user['username'] == 'jerry666':
                password = 'jerry123'
            else:
                password = 'password'
            
            print(f"尝试使用密码: {password}")
            
            # 测试bcrypt.checkpw直接使用字节类型
            import bcrypt
            hashed_password_bytes = user['password_hash'].encode('utf-8')
            print(f"密码哈希字节长度: {len(hashed_password_bytes)}")
            print(f"密码哈希字节前20个字符: {hashed_password_bytes[:20]}")
            
            is_valid = bcrypt.checkpw(password.encode('utf-8'), hashed_password_bytes)
            print(f"直接使用bcrypt.checkpw验证结果: {is_valid}")
            
            # 测试使用verify_password函数
            is_valid2 = verify_password(password, user['password_hash'])
            print(f"使用verify_password函数验证结果: {is_valid2}")
            
        except Exception as e:
            print(f"密码验证失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 测试生成新的密码哈希
    print("\n测试生成新的密码哈希...")
    test_password = "test123"
    new_hash = get_password_hash(test_password)
    print(f"新密码哈希: {new_hash}")
    print(f"新密码哈希类型: {type(new_hash)}")
    print(f"新密码哈希长度: {len(new_hash)}")
    
    # 测试验证新生成的密码哈希
    try:
        is_valid = verify_password(test_password, new_hash)
        print(f"验证新生成的密码哈希结果: {is_valid}")
    except Exception as e:
        print(f"验证新生成的密码哈希失败: {e}")
    
    # 关闭数据库连接
    db.close()

if __name__ == "__main__":
    check_password()
