import psycopg2
import os
import json
from pathlib import Path
from datetime import datetime
from psycopg2.extras import RealDictCursor

from config import settings, init_logger

# 初始化日志记录器
logger = init_logger(__name__)

class Database:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """连接到PostgreSQL数据库"""
        try:
            # 首先连接到PostgreSQL服务器的默认数据库
            temp_conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname="postgres"  # 使用默认的postgres数据库
            )
            temp_conn.autocommit = True
            temp_cursor = temp_conn.cursor()
            
            # 检查目标数据库是否存在
            temp_cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings.POSTGRES_DB,))
            exists = temp_cursor.fetchone()
            
            # 如果数据库不存在，创建它
            if not exists:
                logger.info(f"创建数据库: {settings.POSTGRES_DB}")
                # 验证数据库名称合法性，防止SQL注入
                import re
                db_name = settings.POSTGRES_DB
                # PostgreSQL数据库名称只能包含字母、数字、下划线和美元符号，且不能以数字开头
                if not re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', db_name):
                    raise ValueError(f"无效的数据库名称: {db_name}")
                # PostgreSQL的CREATE DATABASE语句不能使用参数化查询，所以直接使用字符串
                temp_cursor.execute(f"CREATE DATABASE {db_name}")
                logger.info(f"数据库 {db_name} 创建成功")
            else:
                logger.info(f"数据库 {settings.POSTGRES_DB} 已存在")
            
            # 关闭临时连接
            temp_cursor.close()
            temp_conn.close()
            
            # 连接到目标数据库
            self.conn = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                dbname=settings.POSTGRES_DB
            )
            self.conn.autocommit = True
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            logger.info(f"成功连接到数据库: {settings.POSTGRES_DB}")
            return True
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            return False
    
    def create_tables(self):
        """创建数据库表"""
        try:
            # 创建用户表
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 创建知识库表
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    kb_name TEXT NOT NULL,
                    description TEXT,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # 创建用户知识库权限表
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_kb_permission (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    knowledge_base_id INTEGER NOT NULL,
                    permission TEXT NOT NULL DEFAULT 'read',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base (id),
                    UNIQUE (user_id, knowledge_base_id)
                )
            ''')
            
            # 创建文档表
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS document (
                    id SERIAL PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    enhanced_md_path TEXT,
                    status TEXT DEFAULT 'uploaded',
                    metadata JSONB,
                    processing_time REAL,
                    upload_time REAL, -- 上传时间（毫秒）
                    split_time REAL, -- 切割时间（毫秒）
                    generate_time REAL, -- 生成时间（毫秒）
                    import_time REAL, -- 导入时间（毫秒）
                    user_id INTEGER,
                    knowledge_base_id INTEGER,
                    file_hash TEXT, -- 文件哈希值，用于判断是否为相同文档
                    es_indexed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base (id)
                )
            ''')
            
            # 创建文档块表（同一文档的 chunk_index 必须唯一，防止重复切割入库）
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS document_chunk (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL,
                    knowledge_base_id INTEGER,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES document (id),
                    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base (id),
                    UNIQUE (document_id, chunk_index)
                )
            ''')
            
            # 创建子问题表（防止同一 chunk_id 重复插入子问题）
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS sub_question (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL,
                    knowledge_base_id INTEGER,
                    chunk_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES document (id),
                    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base (id),
                    FOREIGN KEY (chunk_id) REFERENCES document_chunk (id)
                )
            ''')
            
            # 创建摘要表
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS chunk_summary (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL,
                    knowledge_base_id INTEGER,
                    chunk_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES document (id),
                    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base (id),
                    FOREIGN KEY (chunk_id) REFERENCES document_chunk (id)
                )
            ''')
            
            # 创建工作流日志表
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS workflow_log (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER,
                    knowledge_base_id INTEGER,
                    operation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    processing_time REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES document (id) ON DELETE SET NULL,
                    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base (id) ON DELETE SET NULL
                )
            ''')
            
            # 创建索引
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_status ON document (status)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_user_id ON document (user_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_knowledge_base_id ON document (knowledge_base_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_chunk_document_id ON document_chunk (document_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_document_chunk_knowledge_base_id ON document_chunk (knowledge_base_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_question_chunk_id ON sub_question (chunk_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_sub_question_knowledge_base_id ON sub_question (knowledge_base_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_chunk_summary_chunk_id ON chunk_summary (chunk_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_chunk_summary_knowledge_base_id ON chunk_summary (knowledge_base_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_base_user_id ON knowledge_base (user_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_kb_permission_user_id ON user_kb_permission (user_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_kb_permission_kb_id ON user_kb_permission (knowledge_base_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_workflow_log_document_id ON workflow_log (document_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_workflow_log_knowledge_base_id ON workflow_log (knowledge_base_id)')
            
            return True
        except Exception as e:
            logger.error(f"创建表失败: {e}")
            return False
    
    def execute(self, query, params=None):
        """执行SQL查询"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            return True
        except Exception as e:
            logger.error(f"执行查询失败: {e}")
            return False
    
    def fetchall(self, query, params=None):
        """执行查询并返回所有结果"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []
    
    def fetchone(self, query, params=None):
        """执行查询并返回第一条结果"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            return self.cursor.fetchone()
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return None
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
    
    # 用户相关方法
    def add_user(self, username, email, password_hash, role='user'):
        """添加用户"""
        query = '''
            INSERT INTO users (username, email, password_hash, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        '''
        try:
            self.cursor.execute(query, (username, email, password_hash, role))
            return self.cursor.fetchone()['id']
        except Exception as e:
            logger.error(f"添加用户失败: {e}")
            return None
    
    # 知识库相关方法
    def add_knowledge_base(self, user_id, kb_name, description=None, metadata=None):
        """添加知识库"""
        query = '''
            INSERT INTO knowledge_base (user_id, kb_name, description, metadata)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        '''
        try:
            # 将metadata转换为JSON字符串
            metadata_json = json.dumps(metadata) if metadata else None
            self.cursor.execute(query, (user_id, kb_name, description, metadata_json))
            kb_id = self.cursor.fetchone()['id']
            # 为创建者添加完全权限
            self.add_user_kb_permission(user_id, kb_id, 'write')
            return kb_id
        except Exception as e:
            logger.error(f"添加知识库失败: {e}")
            return None
    
    def get_user_knowledge_bases(self, user_id):
        """获取用户的知识库列表"""
        query = '''
            SELECT kb.* FROM knowledge_base kb
            LEFT JOIN user_kb_permission perm ON kb.id = perm.knowledge_base_id
            WHERE kb.user_id = %s OR perm.user_id = %s
            GROUP BY kb.id
        '''
        try:
            self.cursor.execute(query, (user_id, user_id))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"获取知识库列表失败: {e}")
            return []
    
    def get_pending_documents(self, kb_ids):
        """获取待处理的文档列表"""
        if not kb_ids:
            return []
        
        placeholders = ','.join(['%s'] * len(kb_ids))
        query = f'''
            SELECT * FROM document
            WHERE knowledge_base_id IN ({placeholders})
            AND status NOT IN ('completed')
            ORDER BY created_at DESC
        '''
        try:
            self.cursor.execute(query, kb_ids)
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"获取待处理文档失败: {e}")
            return []
    
    def get_knowledge_base(self, kb_id):
        """获取知识库详情"""
        query = "SELECT * FROM knowledge_base WHERE id = %s"
        try:
            self.cursor.execute(query, (kb_id,))
            return self.cursor.fetchone()
        except Exception as e:
            logger.error(f"获取知识库详情失败: {e}")
            return None

    def update_knowledge_base(self, kb_id, update_data):
        """更新知识库信息"""
        set_clauses = []
        params = []
        for key, value in update_data.items():
            set_clauses.append(f"{key} = %s")
            params.append(value)
        params.append(kb_id)
        
        query = f'''
            UPDATE knowledge_base
            SET {', '.join(set_clauses)}
            WHERE id = %s
        '''
        try:
            self.cursor.execute(query, params)
            return True
        except Exception as e:
            logger.error(f"更新知识库失败: {e}")
            return False
    
    def add_user_kb_permission(self, user_id, knowledge_base_id, permission='read'):
        """添加用户知识库权限"""
        query = '''
            INSERT INTO user_kb_permission (user_id, knowledge_base_id, permission)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, knowledge_base_id) DO UPDATE
            SET permission = EXCLUDED.permission
        '''
        try:
            self.cursor.execute(query, (user_id, knowledge_base_id, permission))
            return True
        except Exception as e:
            logger.error(f"添加用户知识库权限失败: {e}")
            return False
    
    def check_kb_permission(self, user_id, knowledge_base_id, required_permission='read'):
        """检查用户对知识库的权限"""
        # 类型检查，确保user_id是整数
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            logger.error(f"无效的用户ID: {user_id}")
            return False
        
        # 检查是否是知识库的创建者
        query = "SELECT * FROM knowledge_base WHERE id = %s AND user_id = %s"
        try:
            self.cursor.execute(query, (knowledge_base_id, user_id))
            if self.cursor.fetchone():
                return True
        except Exception as e:
            logger.error(f"检查知识库创建者失败: {e}")
        
        # 检查是否有授权权限
        query = '''
            SELECT * FROM user_kb_permission
            WHERE user_id = %s AND knowledge_base_id = %s
            AND (permission = 'write' OR (permission = 'read' AND %s = 'read'))
        '''
        try:
            self.cursor.execute(query, (user_id, knowledge_base_id, required_permission))
            return bool(self.cursor.fetchone())
        except Exception as e:
            logger.error(f"检查知识库权限失败: {e}")
            return False
    
    def get_user_by_username(self, username):
        """根据用户名获取用户"""
        query = "SELECT * FROM users WHERE username = %s"
        return self.fetchone(query, (username,))
    
    def get_user_by_email(self, email):
        """根据邮箱获取用户"""
        query = "SELECT * FROM users WHERE email = %s"
        return self.fetchone(query, (email,))
    
    # 文档相关方法
    def add_document(self, filename, file_path, enhanced_md_path=None, status='uploaded', metadata=None, processing_time=None, upload_time=None, user_id=None, knowledge_base_id=None, file_hash=None):
        """添加文档"""
        query = '''
            INSERT INTO document (filename, file_path, enhanced_md_path, status, metadata, processing_time, upload_time, user_id, knowledge_base_id, file_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        '''
        try:
            # 将metadata转换为JSON字符串
            metadata_json = json.dumps(metadata) if metadata else None
            self.cursor.execute(query, (filename, file_path, enhanced_md_path, status, metadata_json, processing_time, upload_time, user_id, knowledge_base_id, file_hash))
            return self.cursor.fetchone()['id']
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            return None
    
    def update_document(self, document_id, **kwargs):
        """更新文档信息"""
        set_clauses = []
        params = []
        for key, value in kwargs.items():
            set_clauses.append(f"{key} = %s")
            params.append(value)
        params.append(document_id)
        
        query = f'''
            UPDATE document
            SET {', '.join(set_clauses)},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        '''
        return self.execute(query, params)
    
    def get_document(self, document_id):
        """根据ID获取文档"""
        query = "SELECT * FROM document WHERE id = %s"
        return self.fetchone(query, (document_id,))
    
    def get_documents_by_status(self, status):
        """根据状态获取文档"""
        query = "SELECT * FROM document WHERE status = %s"
        return self.fetchall(query, (status,))
    
    def get_all_documents(self):
        """获取所有文档"""
        query = "SELECT * FROM document"
        return self.fetchall(query)
    
    def get_documents_by_user(self, user_id):
        """根据用户ID获取文档"""
        query = "SELECT * FROM document WHERE user_id = %s"
        return self.fetchall(query, (user_id,))
    
    def get_documents_by_user_and_status(self, user_id, status):
        """根据用户ID和状态获取文档"""
        query = "SELECT * FROM document WHERE user_id = %s AND status = %s"
        return self.fetchall(query, (user_id, status))
    
    def get_document_by_hash_and_kb(self, file_hash, knowledge_base_id):
        """根据文件哈希值和知识库ID获取文档"""
        query = "SELECT * FROM document WHERE file_hash = %s AND knowledge_base_id = %s"
        return self.fetchone(query, (file_hash, knowledge_base_id))
    
    def delete_document(self, document_id, knowledge_base_id=None):
        """删除文档及其相关数据（仅数据库层），并记录到workflow日志
        
        文件存储、向量数据库、ES 索引的删除由 app.py 统一调度，
        此方法只负责清理 PostgreSQL 中的关联数据。
        """
        try:
            # 获取文档信息用于日志记录
            doc_info = self.get_document(document_id)
            filename = doc_info['filename'] if doc_info else '未知文件'
            kb_id = knowledge_base_id or (doc_info['knowledge_base_id'] if doc_info else None)
            
            # 先删除子问题（因为子问题引用了document_chunk）
            self.cursor.execute("DELETE FROM sub_question WHERE document_id = %s", (document_id,))
            subq_count = self.cursor.rowcount
            
            # 然后删除摘要（因为摘要也引用了document_chunk）
            self.cursor.execute("DELETE FROM chunk_summary WHERE document_id = %s", (document_id,))
            summary_count = self.cursor.rowcount
            
            # 再删除文档块
            self.cursor.execute("DELETE FROM document_chunk WHERE document_id = %s", (document_id,))
            chunk_count = self.cursor.rowcount
            
            # 记录删除操作到workflow日志（在删除文档之前记录，这样可以使用document_id）
            self.add_workflow_log(
                document_id=document_id,
                operation="delete_document",
                status="completed",
                message=f"删除文档: {filename}, 清理了 {chunk_count} 个文档块, {subq_count} 个子问题, {summary_count} 个摘要",
                knowledge_base_id=kb_id
            )
            
            # 删除文档
            self.cursor.execute("DELETE FROM document WHERE id = %s", (document_id,))
            
            return True
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            # 记录删除失败日志
            self.add_workflow_log(
                document_id=document_id,
                operation="delete_document",
                status="failed",
                message=f"删除文档失败: {str(e)}",
                knowledge_base_id=knowledge_base_id
            )
            return False
    
    def delete_knowledge_base(self, kb_id):
        """删除知识库及其所有相关数据，并记录到workflow日志"""
        try:
            # 获取知识库信息用于日志记录
            kb_info = self.get_knowledge_base(kb_id)
            kb_name = kb_info['kb_name'] if kb_info else '未知知识库'
            
            # 获取知识库下的所有文档
            self.cursor.execute("SELECT id FROM document WHERE knowledge_base_id = %s", (kb_id,))
            documents = self.cursor.fetchall()
            doc_count = len(documents)
            
            # 删除用户知识库权限
            self.cursor.execute("DELETE FROM user_kb_permission WHERE knowledge_base_id = %s", (kb_id,))
            perm_count = self.cursor.rowcount
            
            # 记录删除操作到workflow日志（在删除知识库之前记录，这样可以使用knowledge_base_id）
            self.add_workflow_log(
                document_id=None,
                operation="delete_knowledge_base",
                status="completed",
                message=f"删除知识库: {kb_name}(ID: {kb_id}), 包含 {doc_count} 个文档, {perm_count} 个权限记录",
                knowledge_base_id=kb_id
            )
            
            # 删除每个文档及其相关数据
            for doc in documents:
                self.delete_document(doc['id'], knowledge_base_id=kb_id)
            
            # 删除知识库
            self.cursor.execute("DELETE FROM knowledge_base WHERE id = %s", (kb_id,))
            
            return True
        except Exception as e:
            logger.error(f"删除知识库失败: {e}")
            # 记录删除失败日志
            self.add_workflow_log(
                document_id=None,
                operation="delete_knowledge_base",
                status="failed",
                message=f"删除知识库失败: {str(e)}",
                knowledge_base_id=kb_id
            )
            return False
    
    # 文档块相关方法
    def add_document_chunk(self, document_id, chunk_index, content, metadata=None, knowledge_base_id=None):
        """添加文档块（幂等：同一 document_id + chunk_index 重复插入时更新内容）"""
        query = '''
            INSERT INTO document_chunk (document_id, knowledge_base_id, chunk_index, content, metadata)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (document_id, chunk_index) DO UPDATE SET
                content = EXCLUDED.content,
                metadata = COALESCE(EXCLUDED.metadata, document_chunk.metadata)
            RETURNING id
        '''
        try:
            # 将metadata转换为JSON字符串
            metadata_json = json.dumps(metadata) if metadata else None
            self.cursor.execute(query, (document_id, knowledge_base_id, chunk_index, content, metadata_json))
            return self.cursor.fetchone()['id']
        except Exception as e:
            logger.error(f"添加文档块失败: {e}")
            return None
    
    def get_document_chunks(self, document_id):
        """获取文档的所有块"""
        query = "SELECT * FROM document_chunk WHERE document_id = %s ORDER BY chunk_index"
        return self.fetchall(query, (document_id,))
    
    def get_chunk_by_id(self, chunk_id):
        """根据ID获取文档块"""
        query = "SELECT * FROM document_chunk WHERE id = %s"
        return self.fetchone(query, (chunk_id,))
    
    def get_document_chunks_by_ids(self, chunk_ids):
        """根据ID列表获取文档块"""
        if not chunk_ids:
            return []
        # 构建查询参数
        placeholders = ','.join(['%s'] * len(chunk_ids))
        query = f"SELECT * FROM document_chunk WHERE id IN ({placeholders})"
        return self.fetchall(query, chunk_ids)
    
    # 子问题相关方法
    def add_sub_question(self, document_id, chunk_id, content, metadata=None, knowledge_base_id=None):
        """添加子问题"""
        query = '''
            INSERT INTO sub_question (document_id, knowledge_base_id, chunk_id, content, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        '''
        try:
            # 将metadata转换为JSON字符串
            metadata_json = json.dumps(metadata) if metadata else None
            self.cursor.execute(query, (document_id, knowledge_base_id, chunk_id, content, metadata_json))
            return self.cursor.fetchone()['id']
        except Exception as e:
            logger.error(f"添加子问题失败: {e}")
            return None
    
    def get_sub_questions_by_chunk(self, chunk_id):
        """获取块的所有子问题"""
        query = "SELECT * FROM sub_question WHERE chunk_id = %s"
        return self.fetchall(query, (chunk_id,))
    
    # 摘要相关方法
    def add_chunk_summary(self, document_id, chunk_id, content, metadata=None, knowledge_base_id=None):
        """添加摘要"""
        query = '''
            INSERT INTO chunk_summary (document_id, knowledge_base_id, chunk_id, content, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        '''
        try:
            # 将metadata转换为JSON字符串
            metadata_json = json.dumps(metadata) if metadata else None
            self.cursor.execute(query, (document_id, knowledge_base_id, chunk_id, content, metadata_json))
            return self.cursor.fetchone()['id']
        except Exception as e:
            logger.error(f"添加摘要失败: {e}")
            return None
    
    def get_chunk_summary(self, chunk_id):
        """获取块的摘要"""
        query = "SELECT * FROM chunk_summary WHERE chunk_id = %s"
        return self.fetchone(query, (chunk_id,))
    
    def delete_sub_questions_by_document(self, document_id):
        """删除文档的所有子问题（用于重新生成时的幂等保护）"""
        query = "DELETE FROM sub_question WHERE document_id = %s"
        try:
            self.cursor.execute(query, (document_id,))
            count = self.cursor.rowcount
            logger.info(f"已清理文档 {document_id} 的 {count} 条子问题")
            return count
        except Exception as e:
            logger.error(f"清理文档子问题失败: {e}")
            return 0
    
    def delete_summaries_by_document(self, document_id):
        """删除文档的所有摘要（用于重新生成时的幂等保护）"""
        query = "DELETE FROM chunk_summary WHERE document_id = %s"
        try:
            self.cursor.execute(query, (document_id,))
            count = self.cursor.rowcount
            logger.info(f"已清理文档 {document_id} 的 {count} 条摘要")
            return count
        except Exception as e:
            logger.error(f"清理文档摘要失败: {e}")
            return 0

    def delete_sub_questions_by_chunk(self, chunk_id):
        """删除指定块的所有子问题（用于增量重新生成时的幂等保护）"""
        query = "DELETE FROM sub_question WHERE chunk_id = %s"
        try:
            self.cursor.execute(query, (chunk_id,))
            count = self.cursor.rowcount
            if count > 0:
                logger.info(f"已清理块 {chunk_id} 的 {count} 条子问题")
            return count
        except Exception as e:
            logger.error(f"清理块子问题失败: {e}")
            return 0

    def delete_summary_by_chunk(self, chunk_id):
        """删除指定块的摘要（用于增量重新生成时的幂等保护）"""
        query = "DELETE FROM chunk_summary WHERE chunk_id = %s"
        try:
            self.cursor.execute(query, (chunk_id,))
            count = self.cursor.rowcount
            if count > 0:
                logger.info(f"已清理块 {chunk_id} 的摘要")
            return count
        except Exception as e:
            logger.error(f"清理块摘要失败: {e}")
            return 0
    
    # 工作流日志相关方法
    def add_workflow_log(self, document_id, operation, status, message=None, knowledge_base_id=None, processing_time=None):
        """添加工作流日志"""
        query = '''
            INSERT INTO workflow_log (document_id, knowledge_base_id, operation, status, message, processing_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        '''
        try:
            self.cursor.execute(query, (document_id, knowledge_base_id, operation, status, message, processing_time))
            return self.cursor.fetchone()['id']
        except Exception as e:
            logger.error(f"添加工作流日志失败: {e}")
            return None
    
    def get_document_workflow_logs(self, document_id):
        """获取文档的工作流日志"""
        query = "SELECT * FROM workflow_log WHERE document_id = %s ORDER BY created_at DESC"
        return self.fetchall(query, (document_id,))
    
    # 统计相关方法
    def get_total_documents(self):
        """获取总文档数"""
        query = "SELECT COUNT(*) as count FROM document"
        result = self.fetchone(query)
        return result['count'] if result else 0
    
    def get_total_chunks(self):
        """获取总Chunk数"""
        query = "SELECT COUNT(*) as count FROM document_chunk"
        result = self.fetchone(query)
        return result['count'] if result else 0
    
    def get_total_sub_questions(self):
        """获取总子问题数"""
        query = "SELECT COUNT(*) as count FROM sub_question"
        result = self.fetchone(query)
        return result['count'] if result else 0
    
    def get_total_summaries(self):
        """获取总摘要数"""
        query = "SELECT COUNT(*) as count FROM chunk_summary"
        result = self.fetchone(query)
        return result['count'] if result else 0
    
    def get_total_users(self):
        """获取总用户数"""
        query = "SELECT COUNT(*) as count FROM users"
        result = self.fetchone(query)
        return result['count'] if result else 0
    
    def get_user_documents_count(self, user_id):
        """获取用户文档数"""
        query = "SELECT COUNT(*) as count FROM document WHERE user_id = %s"
        result = self.fetchone(query, (user_id,))
        return result['count'] if result else 0
    
    def get_user_chunks_count(self, user_id):
        """获取用户Chunk数"""
        query = '''
            SELECT COUNT(*) as count FROM document_chunk dc
            JOIN document d ON dc.document_id = d.id
            WHERE d.user_id = %s
        '''
        result = self.fetchone(query, (user_id,))
        return result['count'] if result else 0
    
    def get_user_sub_questions_count(self, user_id):
        """获取用户子问题数"""
        query = '''
            SELECT COUNT(*) as count FROM sub_question sq
            JOIN document d ON sq.document_id = d.id
            WHERE d.user_id = %s
        '''
        result = self.fetchone(query, (user_id,))
        return result['count'] if result else 0
    
    def get_user_summaries_count(self, user_id):
        """获取用户摘要数"""
        query = '''
            SELECT COUNT(*) as count FROM chunk_summary cs
            JOIN document d ON cs.document_id = d.id
            WHERE d.user_id = %s
        '''
        result = self.fetchone(query, (user_id,))
        return result['count'] if result else 0

# 全局数据库实例
db = Database()