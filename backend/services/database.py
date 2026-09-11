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
            
            # 创建审计日志表（只追加：业务代码路径上只有 INSERT，无 UPDATE/DELETE）
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    user_id INTEGER,
                    action VARCHAR(64) NOT NULL,
                    resource_type VARCHAR(32),
                    resource_id VARCHAR(64),
                    kb_id INTEGER,
                    request_id VARCHAR(64),
                    client_ip VARCHAR(64),
                    user_agent TEXT,
                    detail JSONB
                )
            ''')

            # 创建索引
            # 01-C：分词缓存列（TEXT 空格连接，靠 TOAST LZ4 压缩，PG14+ 生效，低版本自动忽略/退化 pglz）
            try:
                self.cursor.execute('ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS tokenized TEXT')
                self.cursor.execute('ALTER TABLE document_chunk ALTER COLUMN tokenized SET COMPRESSION lz4')
            except Exception as e:
                # PG < 14 不支持 SET COMPRESSION lz4 → 退化为默认 pglz 压缩（设计 §3.2）
                logger.warning(f"tokenized 列 LZ4 压缩设置失败（PG<14 退化为默认压缩）: {e}")
            # 02/03：知识库级策略配置（chunk_strategy 切割策略 / enhancers 启用增强器集合，NULL = 跟随全局）
            try:
                self.cursor.execute('ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS chunk_strategy VARCHAR(32)')
                self.cursor.execute('ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS enhancers JSONB')
            except Exception as e:
                logger.warning(f"knowledge_base 策略列迁移失败: {e}")

            # ==================== 06 自进化 RAG（Stage 3） ====================
            # L3 FAQ 记忆表：候选/正式双态 + 热度 + 按 KB 归属快照的蒸馏阈值
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS faq (
                    id SERIAL PRIMARY KEY,
                    kb_id INTEGER NOT NULL REFERENCES knowledge_base(id),
                    owner_id INTEGER NOT NULL REFERENCES users(id),
                    submitter_id INTEGER NOT NULL REFERENCES users(id),
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    hit_count INTEGER DEFAULT 1,
                    last_hit_time TIMESTAMP,
                    heat_score REAL DEFAULT 0,
                    source TEXT,
                    status VARCHAR(16) DEFAULT 'candidate',
                    distill_threshold INTEGER DEFAULT 2,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_faq_kb ON faq (kb_id, status)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_faq_owner ON faq (owner_id, status)')

            # KB 分享关系（GitHub 式协作的可见性基础）
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS kb_share (
                    id SERIAL PRIMARY KEY,
                    kb_id INTEGER NOT NULL REFERENCES knowledge_base(id),
                    shared_to_user_id INTEGER NOT NULL REFERENCES users(id),
                    shared_by_user_id INTEGER NOT NULL REFERENCES users(id),
                    can_write_directly BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (kb_id, shared_to_user_id)
                )
            ''')

            # FAQ PR 队列（他人共享 KB 的人工审核闸门）
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS faq_pr (
                    id SERIAL PRIMARY KEY,
                    source_faq_id INTEGER REFERENCES faq(id),
                    source_kb_id INTEGER,
                    target_kb_id INTEGER NOT NULL REFERENCES knowledge_base(id),
                    submitted_by INTEGER NOT NULL REFERENCES users(id),
                    status VARCHAR(16) DEFAULT 'open',
                    reviewed_by INTEGER REFERENCES users(id),
                    reviewed_at TIMESTAMP,
                    review_note TEXT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_faq_pr_target ON faq_pr (target_kb_id, status)')

            # ── 文档 08：缓存相关 ──
            # L1 查询 embedding 缓存（持久层；embedding 是纯函数，无需失效逻辑）
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS query_embedding_cache (
                    query_hash TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    model TEXT NOT NULL,
                    embedding JSONB NOT NULL,
                    hit_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_hit_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # L2 版本号失效：KB 内容变更 → cache_version+1 → 旧缓存 key 自动失配
            self.cursor.execute('''
                ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS cache_version INTEGER NOT NULL DEFAULT 0
            ''')

            # L2 图谱层：实体与关系（文档 06 Phase 2）
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS entity (
                    id SERIAL PRIMARY KEY,
                    kb_id INTEGER NOT NULL REFERENCES knowledge_base(id),
                    name TEXT NOT NULL,
                    type TEXT,
                    description TEXT,
                    source_chunk_ids JSONB DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (kb_id, name)
                )
            ''')
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS entity_relation (
                    id SERIAL PRIMARY KEY,
                    kb_id INTEGER NOT NULL REFERENCES knowledge_base(id),
                    head_entity_id INTEGER NOT NULL REFERENCES entity(id),
                    relation_type TEXT NOT NULL,
                    tail_entity_id INTEGER NOT NULL REFERENCES entity(id),
                    evidence TEXT,
                    source_chunk_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_entity_kb ON entity (kb_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_relation_head ON entity_relation (head_entity_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_relation_tail ON entity_relation (tail_entity_id)')
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
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log (occurred_at DESC)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log (action, occurred_at DESC)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log (user_id, occurred_at DESC)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_request_id ON audit_log (request_id)')
            
            return True
        except Exception as e:
            logger.error(f"创建表失败: {e}")
            return False
    
    def execute(self, query, params=None):
        """执行SQL写入（独立游标，理由同 fetchall）"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
            return True
        except Exception as e:
            logger.error(f"执行查询失败: {e}")
            return False
    
    def fetchall(self, query, params=None):
        """执行查询并返回所有结果

        每次调用使用独立游标（with conn.cursor()）：db.cursor 是进程级共享对象，
        asyncio 并发（如 hybrid 检索首请求耗时数秒的 Milvus 懒加载期间，其他
        协程并发写审计/查询 PG）会交错 execute/fetchall，导致
        "no results to fetch" 或结果串行污染——正是 /api/hybrid/search 不传
        use_rerank（=默认 rerank 路径，首请求触发集合懒加载）返回空的原因。
        psycopg2 连接本身是线程安全的（串行化访问），autocommit 下按调用
        分配游标无副作用。
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchall()
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return []

    def fetchone(self, query, params=None):
        """执行查询并返回第一条结果（独立游标，理由同 fetchall）"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchone()
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return None
    
    # ==================== 审计日志相关方法 ====================

    def insert_audit_batch(self, events):
        """批量插入审计事件（executemany），返回成功条数"""
        if not events:
            return 0
        query = '''
            INSERT INTO audit_log
                (occurred_at, user_id, action, resource_type, resource_id,
                 kb_id, request_id, client_ip, user_agent, detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        rows = [
            (
                ev.get('occurred_at'), ev.get('user_id'), ev.get('action'),
                ev.get('resource_type'), ev.get('resource_id'), ev.get('kb_id'),
                ev.get('request_id'), ev.get('client_ip'), ev.get('user_agent'),
                json.dumps(ev.get('detail'), ensure_ascii=False) if ev.get('detail') is not None else None,
            )
            for ev in events
        ]
        try:
            self.cursor.executemany(query, rows)
            return len(rows)
        except Exception as e:
            logger.error(f"批量插入审计日志失败: {e}")
            return 0

    def query_audit_logs(self, user_id=None, action=None, resource_type=None,
                         kb_id=None, request_id=None, start_time=None, end_time=None,
                         page=1, page_size=50):
        """分页查询审计日志（带过滤条件）"""
        conditions = []
        params = []

        if user_id is not None:
            conditions.append("user_id = %s")
            params.append(user_id)
        if action:
            conditions.append("action = %s")
            params.append(action)
        if resource_type:
            conditions.append("resource_type = %s")
            params.append(resource_type)
        if kb_id is not None:
            conditions.append("kb_id = %s")
            params.append(kb_id)
        if request_id:
            conditions.append("request_id = %s")
            params.append(request_id)
        if start_time:
            conditions.append("occurred_at >= %s")
            params.append(start_time)
        if end_time:
            conditions.append("occurred_at <= %s")
            params.append(end_time)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # 总数
        count_row = self.fetchone(f"SELECT COUNT(*) AS cnt FROM audit_log{where}", tuple(params) or None)
        total = count_row["cnt"] if count_row else 0

        # 分页数据
        offset = (max(page, 1) - 1) * page_size
        query = f'''
            SELECT * FROM audit_log{where}
            ORDER BY occurred_at DESC, id DESC
            LIMIT %s OFFSET %s
        '''
        rows = self.fetchall(query, tuple(params) + (page_size, offset))
        # detail JSONB 已由 psycopg2 自动反序列化为 dict
        return {"total": total, "page": page, "page_size": page_size, "items": rows}

    # ==================== 06 自进化 RAG：FAQ 记忆（Stage 3 Phase 1） ====================

    def add_faq(self, kb_id, owner_id, submitter_id, question, answer,
                source="supplement", status="candidate", distill_threshold=2):
        """新增 FAQ 记忆条目（默认 candidate，热度达标或审核后才升格 active）"""
        try:
            self.cursor.execute('''
                INSERT INTO faq (kb_id, owner_id, submitter_id, question, answer,
                                 source, status, distill_threshold, last_hit_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING id
            ''', (kb_id, owner_id, submitter_id, question, answer, source, status, distill_threshold))
            return self.cursor.fetchone()["id"]
        except Exception as e:
            logger.error(f"新增 FAQ 失败: {e}")
            return None

    def get_faq(self, faq_id):
        return self.fetchone("SELECT * FROM faq WHERE id = %s", (faq_id,))

    def find_faq_by_question(self, kb_id, question):
        """同一 KB 内按问题文本精确查重（向量相似判重在 milvus 层做）"""
        return self.fetchone(
            "SELECT * FROM faq WHERE kb_id = %s AND question = %s LIMIT 1",
            (kb_id, question))

    def increment_faq_hit(self, faq_id, half_life_days=7.0):
        """命中更新：hit_count+1、last_hit_time=now，并按半衰期重算 heat_score。

        heat = hit_count × 0.5^(距上次命中天数 / 半衰期)
        """
        try:
            self.cursor.execute('''
                UPDATE faq
                SET hit_count = hit_count + 1,
                    heat_score = (hit_count + 1) * POWER(0.5,
                        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - COALESCE(last_hit_time, CURRENT_TIMESTAMP)))
                        / 86400.0 / %s),
                    last_hit_time = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING hit_count, heat_score, status, distill_threshold
            ''', (half_life_days, faq_id))
            return self.cursor.fetchone()
        except Exception as e:
            logger.error(f"FAQ 命中更新失败: {e}")
            return None

    # ==================== 缓存相关方法（文档 08） ====================

    def bump_kb_cache_version(self, kb_id) -> int:
        """KB 内容变更后 bump 版本（旧缓存 key 自动失配）。返回新版本号，失败 -1。"""
        row = self.fetchone(
            "UPDATE knowledge_base SET cache_version = cache_version + 1 "
            "WHERE id = %s RETURNING cache_version", (kb_id,))
        return row["cache_version"] if row else -1

    def get_kb_cache_versions(self, kb_ids) -> dict:
        """批量取 KB 版本号 → {str(kb_id): version}（L2 key 版本维度）。"""
        ids = [int(k) for k in kb_ids if k is not None]
        if not ids:
            return {}
        rows = self.fetchall(
            "SELECT id, cache_version FROM knowledge_base WHERE id = ANY(%s)", (ids,))
        return {str(r["id"]): r["cache_version"] for r in rows}

    def get_user_cache_scope_version(self, user_id) -> int:
        """用户可见域（自有+被分享 KB）的最大版本号（无 KB 过滤的全局检索 key 用）。"""
        row = self.fetchone('''
            SELECT COALESCE(MAX(cache_version), 0) AS v FROM knowledge_base
            WHERE user_id = %s OR id IN (
                SELECT knowledge_base_id FROM user_kb_permission WHERE user_id = %s)
        ''', (user_id, user_id))
        return row["v"] if row else 0

    def get_global_cache_version(self) -> int:
        """全局最大版本号（admin 无过滤检索 key 用）。"""
        row = self.fetchone(
            "SELECT COALESCE(MAX(cache_version), 0) AS v FROM knowledge_base")
        return row["v"] if row else 0

    def get_query_embedding(self, query_hash):
        """L1 查询 embedding 缓存：命中返回向量 list 并累计 hit_count，miss 返回 None。"""
        row = self.fetchone(
            "SELECT embedding FROM query_embedding_cache WHERE query_hash = %s", (query_hash,))
        if row is None:
            return None
        vec = row["embedding"]
        if not isinstance(vec, list):
            vec = json.loads(vec)
        self.execute(
            "UPDATE query_embedding_cache SET hit_count = hit_count + 1, "
            "last_hit_at = CURRENT_TIMESTAMP WHERE query_hash = %s", (query_hash,))
        return vec

    def put_query_embedding(self, query_hash, query_text, model, embedding):
        """L1 写入（同 hash 同内容幂等；冲突只刷新 last_hit_at）。"""
        return self.execute('''
            INSERT INTO query_embedding_cache (query_hash, query_text, model, embedding)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (query_hash) DO UPDATE SET last_hit_at = CURRENT_TIMESTAMP
        ''', (query_hash, query_text, model, json.dumps(embedding)))

    def promote_faq(self, faq_id, answer=None):
        """升格 candidate → active（可携带蒸馏后的新答案）"""
        try:
            if answer is not None:
                self.cursor.execute('''
                    UPDATE faq SET status = 'active', answer = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (answer, faq_id))
            else:
                self.cursor.execute('''
                    UPDATE faq SET status = 'active', updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (faq_id,))
            return True
        except Exception as e:
            logger.error(f"FAQ 升格失败: {e}")
            return False

    def demote_faq(self, faq_id):
        return self.execute(
            "UPDATE faq SET status = 'candidate', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (faq_id,))

    def delete_faq(self, faq_id):
        return self.execute("DELETE FROM faq WHERE id = %s", (faq_id,))

    def list_faqs(self, kb_id=None, owner_id=None, submitter_id=None,
                  status=None, page=1, page_size=20):
        """FAQ 列表（管理页用），支持 kb/归属/提交者/状态过滤"""
        conditions, params = [], []
        if kb_id is not None:
            conditions.append("kb_id = %s")
            params.append(kb_id)
        if owner_id is not None:
            conditions.append("owner_id = %s")
            params.append(owner_id)
        if submitter_id is not None:
            conditions.append("submitter_id = %s")
            params.append(submitter_id)
        if status:
            conditions.append("status = %s")
            params.append(status)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        total = (self.fetchone(f"SELECT COUNT(*) AS cnt FROM faq{where}", tuple(params) or None) or {}).get("cnt", 0)
        offset = (max(page, 1) - 1) * page_size
        rows = self.fetchall(f'''
            SELECT * FROM faq{where}
            ORDER BY updated_at DESC, id DESC
            LIMIT %s OFFSET %s
        ''', tuple(params) + (page_size, offset))
        return {"total": total, "page": page, "page_size": page_size, "items": rows}

    # ==================== KB 分享（可见性基础） ====================

    def share_kb(self, kb_id, shared_to_user_id, shared_by_user_id, can_write_directly=False):
        """分享 KB 给用户；同步写 user_kb_permission 保持现有检索权限体系兼容"""
        try:
            self.cursor.execute('''
                INSERT INTO kb_share (kb_id, shared_to_user_id, shared_by_user_id, can_write_directly)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (kb_id, shared_to_user_id)
                DO UPDATE SET can_write_directly = EXCLUDED.can_write_directly
            ''', (kb_id, shared_to_user_id, shared_by_user_id, can_write_directly))
            # 权限表同步：can_write_directly → write，否则 read
            self.add_user_kb_permission(
                shared_to_user_id, kb_id, 'write' if can_write_directly else 'read')
            return True
        except Exception as e:
            logger.error(f"分享知识库失败: {e}")
            return False

    def unshare_kb(self, kb_id, shared_to_user_id):
        try:
            self.cursor.execute(
                "DELETE FROM kb_share WHERE kb_id = %s AND shared_to_user_id = %s",
                (kb_id, shared_to_user_id))
            self.cursor.execute(
                "DELETE FROM user_kb_permission WHERE knowledge_base_id = %s AND user_id = %s",
                (kb_id, shared_to_user_id))
            return True
        except Exception as e:
            logger.error(f"取消分享失败: {e}")
            return False

    def get_kb_shares(self, kb_id):
        """KB 分享列表（JOIN users 取用户名，前端展示与 unshare 需要）"""
        return self.fetchall('''
            SELECT s.*, u.username AS shared_to_username
            FROM kb_share s
            LEFT JOIN users u ON u.id = s.shared_to_user_id
            WHERE s.kb_id = %s
            ORDER BY s.created_at DESC
        ''', (kb_id,))

    def can_write_directly(self, user_id, kb_id):
        """用户对他人共享 KB 是否有直写权（有 → 补全走阈值路径；无 → 走 PR 审核）"""
        row = self.fetchone('''
            SELECT can_write_directly FROM kb_share
            WHERE kb_id = %s AND shared_to_user_id = %s
        ''', (kb_id, user_id))
        return bool(row and row["can_write_directly"])

    # ==================== FAQ PR 队列 ====================

    def create_faq_pr(self, source_faq_id, source_kb_id, target_kb_id,
                      submitted_by, question, answer):
        try:
            self.cursor.execute('''
                INSERT INTO faq_pr (source_faq_id, source_kb_id, target_kb_id,
                                    submitted_by, question, answer)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (source_faq_id, source_kb_id, target_kb_id, submitted_by, question, answer))
            return self.cursor.fetchone()["id"]
        except Exception as e:
            logger.error(f"创建 FAQ PR 失败: {e}")
            return None

    def get_faq_pr(self, pr_id):
        return self.fetchone("SELECT * FROM faq_pr WHERE id = %s", (pr_id,))

    def list_faq_prs(self, target_kb_id=None, submitted_by=None, status=None,
                     page=1, page_size=20, target_kb_ids=None):
        conditions, params = [], []
        if target_kb_id is not None:
            conditions.append("target_kb_id = %s")
            params.append(target_kb_id)
        elif target_kb_ids is not None:
            # P1-7：批量 KB 过滤（ANY 数组），避免逐 KB N+1 查询
            conditions.append("pr.target_kb_id = ANY(%s)")
            params.append(list(target_kb_ids))
        if submitted_by is not None:
            conditions.append("submitted_by = %s")
            params.append(submitted_by)
        if status:
            conditions.append("status = %s")
            params.append(status)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        total = (self.fetchone(f"SELECT COUNT(*) AS cnt FROM faq_pr pr{where}", tuple(params) or None) or {}).get("cnt", 0)
        offset = (max(page, 1) - 1) * page_size
        rows = self.fetchall(f'''
            SELECT pr.*, u.username AS submitter_name, kb.kb_name AS target_kb_name
            FROM faq_pr pr
            LEFT JOIN users u ON u.id = pr.submitted_by
            LEFT JOIN knowledge_base kb ON kb.id = pr.target_kb_id
            {where}
            ORDER BY pr.created_at DESC, pr.id DESC
            LIMIT %s OFFSET %s
        ''', tuple(params) + (page_size, offset))
        return {"total": total, "page": page, "page_size": page_size, "items": rows}

    def resolve_faq_pr(self, pr_id, status, reviewed_by, review_note=None):
        """库主审核：status = merged / rejected"""
        try:
            self.cursor.execute('''
                UPDATE faq_pr
                SET status = %s, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP,
                    review_note = %s
                WHERE id = %s AND status = 'open'
            ''', (status, reviewed_by, review_note, pr_id))
            return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"FAQ PR 审核失败: {e}")
            return False

    # ==================== KB 克隆（fork：PG 侧快照复制） ====================

    def clone_knowledge_base(self, source_kb_id, new_owner_id, new_name=None):
        """快照克隆 KB（PG 侧）：复制 KB 元数据 + 文档/chunk/增强 + FAQ。

        不追上游（后续上游变更不同步）。
        返回 {"kb_id", "doc_map", "chunk_map", "faq_map"}（old_id → new_id 映射，
        供 milvus_client.clone_kb_vectors 搬运向量时做 id 转换）；失败返回 None。
        """
        src = self.get_knowledge_base(source_kb_id)
        if not src:
            logger.error(f"克隆失败：源知识库 {source_kb_id} 不存在")
            return None
        try:
            new_kb_id = self.add_knowledge_base(
                user_id=new_owner_id,
                kb_name=new_name or f"{src['kb_name']}（克隆）",
                description=src.get("description"),
                metadata=src.get("metadata"),
                chunk_strategy=src.get("chunk_strategy"),
                enhancers=src.get("enhancers"),
            )
            if not new_kb_id:
                return None

            doc_map, chunk_map, faq_map = {}, {}, {}

            # 文档 + chunk + 增强（逐文档复制，记录 id 映射）
            docs = self.get_kb_documents(source_kb_id)
            for doc in docs:
                new_doc_id = self.add_document(
                    filename=doc["filename"], file_path=doc.get("file_path"),
                    enhanced_md_path=doc.get("enhanced_md_path"),
                    status=doc.get("status", "completed"),
                    metadata=doc.get("metadata"),
                    file_hash=doc.get("file_hash"),
                    user_id=new_owner_id, knowledge_base_id=new_kb_id)
                if not new_doc_id:
                    continue
                doc_map[doc["id"]] = new_doc_id
                chunks = self.get_document_chunks(doc["id"])
                for ch in chunks:
                    new_chunk_id = self.add_document_chunk(
                        document_id=new_doc_id, chunk_index=ch["chunk_index"],
                        content=ch["content"], metadata=ch.get("metadata"),
                        knowledge_base_id=new_kb_id)
                    if not new_chunk_id:
                        continue
                    chunk_map[ch["id"]] = new_chunk_id
                    # tokenized 缓存一并复制（01-C 红利：克隆版无需重分词）
                    if ch.get("tokenized") is not None:
                        self.cursor.execute(
                            "UPDATE document_chunk SET tokenized = %s WHERE id = %s",
                            (ch["tokenized"], new_chunk_id))
                    # 子问题 / 摘要
                    for sq in self.get_sub_questions_by_chunk(ch["id"]):
                        self.cursor.execute('''
                            INSERT INTO sub_question (document_id, knowledge_base_id, chunk_id, content, metadata)
                            VALUES (%s, %s, %s, %s, %s)
                        ''', (new_doc_id, new_kb_id, new_chunk_id, sq["content"],
                              json.dumps(sq.get("metadata")) if sq.get("metadata") else None))
                    sm = self.get_chunk_summary(ch["id"])
                    if sm:
                        self.cursor.execute('''
                            INSERT INTO chunk_summary (document_id, knowledge_base_id, chunk_id, content, metadata)
                            VALUES (%s, %s, %s, %s, %s)
                        ''', (new_doc_id, new_kb_id, new_chunk_id, sm["content"],
                              json.dumps(sm.get("metadata")) if sm.get("metadata") else None))

            # FAQ 记忆快照（active 保持 active，热度数据保留快照值）
            faqs = self.fetchall("SELECT * FROM faq WHERE kb_id = %s", (source_kb_id,))
            for f in faqs:
                self.cursor.execute('''
                    INSERT INTO faq (kb_id, owner_id, submitter_id, question, answer,
                                     hit_count, last_hit_time, heat_score, source,
                                     status, distill_threshold)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (new_kb_id, new_owner_id, new_owner_id, f["question"], f["answer"],
                      f["hit_count"], f["last_hit_time"], f["heat_score"],
                      f.get("source") or "clone", f["status"], f["distill_threshold"]))
                row = self.cursor.fetchone()
                if row:
                    faq_map[f["id"]] = row["id"]

            logger.info(f"KB 克隆完成: {source_kb_id} → {new_kb_id}"
                        f"（{len(docs)} 文档，{len(chunk_map)} chunk，{len(faqs)} FAQ）")
            return {"kb_id": new_kb_id, "doc_map": doc_map,
                    "chunk_map": chunk_map, "faq_map": faq_map}
        except Exception as e:
            # P1-5：尽力而为清理——中途失败时回滚未提交写入并删除已建的残留 KB
            logger.error(f"克隆知识库失败: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            if new_kb_id:
                try:
                    self.delete_knowledge_base(new_kb_id)
                    logger.info(f"已清理克隆残留知识库 {new_kb_id}")
                except Exception as ce:
                    logger.warning(f"清理克隆残留 KB {new_kb_id} 失败（需手工处理）: {ce}")
            return None

    # ==================== 06 Phase 2：实体/关系（L2 图谱层） ====================

    def upsert_entity(self, kb_id, name, entity_type=None, description=None, chunk_id=None):
        """实体合并写入：同名实体合并 source_chunk_ids，description 保留更长的版本。

        返回 entity_id。
        """
        name = (name or "").strip()
        if not name:
            return None
        try:
            existing = self.fetchone(
                "SELECT * FROM entity WHERE kb_id = %s AND name = %s", (kb_id, name))
            if existing:
                chunk_ids = existing.get("source_chunk_ids") or []
                if isinstance(chunk_ids, str):
                    chunk_ids = json.loads(chunk_ids)
                if chunk_id is not None and chunk_id not in chunk_ids:
                    chunk_ids.append(chunk_id)
                new_desc = existing.get("description") or ""
                if description and len(description) > len(new_desc):
                    new_desc = description
                new_type = existing.get("type") or entity_type
                self.cursor.execute('''
                    UPDATE entity SET source_chunk_ids = %s, description = %s,
                           type = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (json.dumps(chunk_ids), new_desc, new_type, existing["id"]))
                return existing["id"]
            self.cursor.execute('''
                INSERT INTO entity (kb_id, name, type, description, source_chunk_ids)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (kb_id, name, entity_type, description or "",
                  json.dumps([chunk_id] if chunk_id is not None else [])))
            return self.cursor.fetchone()["id"]
        except Exception as e:
            logger.error(f"实体写入失败（{name}）: {e}")
            return None

    def add_entity_relation(self, kb_id, head_entity_id, relation_type,
                            tail_entity_id, evidence=None, source_chunk_id=None):
        """关系写入：同 (head, relation, tail) 去重"""
        try:
            dup = self.fetchone('''
                SELECT id FROM entity_relation
                WHERE head_entity_id = %s AND relation_type = %s AND tail_entity_id = %s
            ''', (head_entity_id, relation_type, tail_entity_id))
            if dup:
                return dup["id"]
            self.cursor.execute('''
                INSERT INTO entity_relation
                    (kb_id, head_entity_id, relation_type, tail_entity_id, evidence, source_chunk_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (kb_id, head_entity_id, relation_type, tail_entity_id,
                  evidence, source_chunk_id))
            return self.cursor.fetchone()["id"]
        except Exception as e:
            logger.error(f"关系写入失败: {e}")
            return None

    def get_entity_neighbors(self, entity_ids, kb_id=None):
        """一跳邻居扩展：返回这些实体相关的所有关系 + 邻居实体 id 集合"""
        if not entity_ids:
            return [], set()
        id_list = ",".join(str(int(i)) for i in entity_ids)
        where_kb = f"AND kb_id = {int(kb_id)}" if kb_id is not None else ""
        relations = self.fetchall(f'''
            SELECT * FROM entity_relation
            WHERE (head_entity_id IN ({id_list}) OR tail_entity_id IN ({id_list}))
            {where_kb}
        ''')
        neighbor_ids = set(entity_ids)
        for r in relations:
            neighbor_ids.add(r["head_entity_id"])
            neighbor_ids.add(r["tail_entity_id"])
        return relations, neighbor_ids

    def get_entities_by_ids(self, entity_ids):
        if not entity_ids:
            return []
        id_list = ",".join(str(int(i)) for i in entity_ids)
        return self.fetchall(f"SELECT * FROM entity WHERE id IN ({id_list})")

    def find_entities_by_names(self, kb_id, names):
        """按名称匹配实体：先精确匹配，miss 的用 LIKE 模糊匹配 fallback"""
        if not names:
            return []
        # 1. 精确匹配
        placeholders = ",".join(["%s"] * len(names))
        exact = self.fetchall(
            f"SELECT * FROM entity WHERE kb_id = %s AND name IN ({placeholders})",
            tuple([kb_id] + list(names)))
        matched_names = {r["name"] for r in exact}
        # 2. 对精确匹配 miss 的 names，用 LIKE 模糊匹配
        miss_names = [n for n in names if n not in matched_names]
        fuzzy_results = []
        for n in miss_names:
            # 截取 name 的核心部分（去括号、引号）做 LIKE
            core = n.replace('（', '%').replace('）', '%').replace('"', '%').replace('"', '%').replace('"', '%')
            if len(core) < 2:
                continue
            # 限制 LIKE 的 pattern 长度，避免太长匹配不到
            pattern = f'%{core[:20]}%'
            rows = self.fetchall(
                "SELECT * FROM entity WHERE kb_id = %s AND name LIKE %s LIMIT 3",
                (kb_id, pattern))
            fuzzy_results.extend(rows)
        # 合并去重
        all_results = exact + fuzzy_results
        seen_ids = set()
        deduped = []
        for r in all_results:
            if r["id"] not in seen_ids:
                deduped.append(r)
                seen_ids.add(r["id"])
        return deduped

    def get_chunks_by_ids(self, chunk_ids):
        if not chunk_ids:
            return []
        id_list = ",".join(str(int(i)) for i in chunk_ids)
        return self.fetchall(f"SELECT * FROM document_chunk WHERE id IN ({id_list})")

    def get_kb_entities(self, kb_id, limit=500):
        return self.fetchall(
            "SELECT * FROM entity WHERE kb_id = %s ORDER BY updated_at DESC LIMIT %s",
            (kb_id, limit))

    def get_kb_relations(self, kb_id, limit=1000):
        return self.fetchall(
            "SELECT * FROM entity_relation WHERE kb_id = %s ORDER BY id DESC LIMIT %s",
            (kb_id, limit))

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
    def add_knowledge_base(self, user_id, kb_name, description=None, metadata=None,
                           chunk_strategy=None, enhancers=None):
        """添加知识库（文档 02/03：支持 KB 级切割策略与增强器配置，NULL = 跟随全局）"""
        query = '''
            INSERT INTO knowledge_base (user_id, kb_name, description, metadata, chunk_strategy, enhancers)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        '''
        try:
            # 将metadata/enhancers转换为JSON字符串
            metadata_json = json.dumps(metadata) if metadata else None
            enhancers_json = json.dumps(list(enhancers)) if enhancers is not None else None
            self.cursor.execute(query, (user_id, kb_name, description, metadata_json,
                                         chunk_strategy, enhancers_json))
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

    def get_kb_documents(self, knowledge_base_id):
        """获取知识库下全部文档（KB 克隆用）"""
        return self.fetchall(
            "SELECT * FROM document WHERE knowledge_base_id = %s ORDER BY id",
            (knowledge_base_id,))

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

            # Stage 3 表跟随清理（faq/entity 有 KB 外键，不先删会 FK 违约）
            self.cursor.execute("DELETE FROM kb_share WHERE kb_id = %s", (kb_id,))
            self.cursor.execute(
                "DELETE FROM faq_pr WHERE target_kb_id = %s OR source_kb_id = %s",
                (kb_id, kb_id))
            self.cursor.execute("DELETE FROM faq WHERE kb_id = %s", (kb_id,))
            self.cursor.execute(
                "DELETE FROM entity_relation er USING entity e "
                "WHERE er.head_entity_id = e.id AND e.kb_id = %s", (kb_id,))
            self.cursor.execute("DELETE FROM entity WHERE kb_id = %s", (kb_id,))

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
                metadata = COALESCE(EXCLUDED.metadata, document_chunk.metadata),
                tokenized = NULL  -- 01-C：内容变更自动置脏分词缓存
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
    
    def get_document_enhancement_progress(self, document_id):
        """Stage 5：文档处理进度聚合（纯 PG 单查，进度接口用）。

        返回 {total_chunks, chunks_with_summary, chunks_with_subq}。
        sub_question 按有记录的 chunk 去重计数。
        """
        query = '''
            SELECT
                (SELECT COUNT(*) FROM document_chunk WHERE document_id = %s) AS total_chunks,
                (SELECT COUNT(DISTINCT sq.chunk_id) FROM sub_question sq
                   JOIN document_chunk dc ON dc.id = sq.chunk_id
                  WHERE dc.document_id = %s) AS chunks_with_subq,
                (SELECT COUNT(DISTINCT cs.chunk_id) FROM chunk_summary cs
                   JOIN document_chunk dc ON dc.id = cs.chunk_id
                  WHERE dc.document_id = %s) AS chunks_with_summary
        '''
        row = self.fetchone(query, (document_id, document_id, document_id))
        if not row:
            return {"total_chunks": 0, "chunks_with_subq": 0, "chunks_with_summary": 0}
        return {
            "total_chunks": row["total_chunks"] or 0,
            "chunks_with_subq": row["chunks_with_subq"] or 0,
            "chunks_with_summary": row["chunks_with_summary"] or 0,
        }

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
    
    def set_chunk_tokenized_batch(self, mapping):
        """01-C：批量写回分词缓存。mapping: {chunk_id: [tokens]}，TEXT 空格连接存储。

        返回成功写入条数。"""
        if not mapping:
            return 0
        query = 'UPDATE document_chunk SET tokenized = %s WHERE id = %s'
        try:
            rows = [( ' '.join(tokens), cid) for cid, tokens in mapping.items()]
            self.cursor.executemany(query, rows)
            logger.info(f"分词缓存批量写回完成: {len(rows)} 条")
            return len(rows)
        except Exception as e:
            logger.error(f"批量写回分词缓存失败: {e}")
            return 0

    def get_tokenized_by_ids(self, chunk_ids):
        """01-C：批量读取分词缓存。返回 {chunk_id: [tokens]}，仅含已缓存（tokenized 非NULL）的条目。

        空串特判为 []（已分词但为空，防御性三态语义）。"""
        if not chunk_ids:
            return {}
        placeholders = ','.join(['%s'] * len(chunk_ids))
        query = f"SELECT id, tokenized FROM document_chunk WHERE id IN ({placeholders}) AND tokenized IS NOT NULL"
        rows = self.fetchall(query, list(chunk_ids))
        result = {}
        for row in rows:
            text = row['tokenized']
            result[row['id']] = [] if text == '' else text.split(' ')
        return result

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

    def save_chunk_enhanced_data_batch(self, chunk_data_list):
        """
        批量保存块的增强数据（子问题+摘要），使用事务确保原子性。

        chunk_data_list: List[dict], 每个元素包含:
            - chunk_db_id: int
            - document_id: int
            - knowledge_base_id: int
            - metadata: dict
            - subqs: List[str] 子问题列表
            - summary: str 摘要内容
            - skip_subqs: bool 未启用子问题时为 True——不删除已有子问题、不写入（文档 03）
            - skip_summary: bool 未启用摘要时为 True——不删除已有摘要、不写入（文档 03）

        事务保护：如果任何一步失败，整个批次回滚。
        """
        if not chunk_data_list:
            return True

        # 使用 psycopg2 的上下文管理器来处理事务
        try:
            # 使用连接的事务上下文
            with self.conn.cursor() as cur:
                for item in chunk_data_list:
                    chunk_db_id = item["chunk_db_id"]
                    document_id = item["document_id"]
                    knowledge_base_id = item["knowledge_base_id"]
                    metadata = item["metadata"]
                    subqs = item.get("subqs", [])
                    summary = item.get("summary", "")
                    skip_subqs = item.get("skip_subqs", False)
                    skip_summary = item.get("skip_summary", False)

                    # 幂等：先清理旧数据（仅清理本次会写入的字段，
                    # 未启用的字段跳过删除以保护已有增强内容）
                    if not skip_subqs:
                        cur.execute("DELETE FROM sub_question WHERE chunk_id = %s", (chunk_db_id,))
                    if not skip_summary:
                        cur.execute("DELETE FROM chunk_summary WHERE chunk_id = %s", (chunk_db_id,))

                    # 写入子问题
                    metadata_json = json.dumps(metadata) if metadata else None
                    if not skip_subqs:
                        for sq in subqs:
                            cur.execute(
                                """
                                INSERT INTO sub_question (document_id, knowledge_base_id, chunk_id, content, metadata)
                                VALUES (%s, %s, %s, %s, %s)
                                """,
                                (document_id, knowledge_base_id, chunk_db_id, sq, metadata_json)
                            )

                    # 写入摘要
                    if not skip_summary and summary:
                        cur.execute(
                            """
                            INSERT INTO chunk_summary (document_id, knowledge_base_id, chunk_id, content, metadata)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (document_id, knowledge_base_id, chunk_db_id, summary, metadata_json)
                        )

                self.conn.commit()
                logger.info(f"批量保存 {len(chunk_data_list)} 个块的增强数据成功")
                return True

        except Exception as e:
            logger.error(f"批量保存增强数据失败，执行回滚: {e}")
            try:
                self.conn.rollback()
            except Exception as rollback_e:
                logger.error(f"回滚失败: {rollback_e}")
            return False
    
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
# 圈6：Database() 构造含同步 PG 连接 + 建表（实测 ~0.4s），延迟到首次真正使用时初始化，
# 不阻塞 import/启动。所有调用方均只使用 `db.<method>()` 形式，代理对行为等价。
class _DbProxy:
    """Database 的懒加载代理：首次属性访问时才构建真实实例。"""
    __slots__ = ('_real', '_lock')

    def __init__(self):
        self._real = None

    def _ensure(self):
        if self._real is None:
            self._real = Database()
        return self._real

    def __getattr__(self, name):
        return getattr(self._ensure(), name)


db = _DbProxy()