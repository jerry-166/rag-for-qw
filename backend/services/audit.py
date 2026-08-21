"""全局审计中心服务（文档 07 基础设施）

- audit.log(...)：业务埋点入口，同步入队（微秒级，无 IO），后台任务批量落库；
- 降级链：队列满 / DB 写失败 → 写本地 audit_fallback.log 后丢弃，绝不反压业务；
- 脱敏：detail 写入前过 mask_sensitive()，key 名匹配 (?i)(key|secret|password|token) 的值打掩码。
"""

import re
import json
import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from config import settings, init_logger

logger = init_logger(__name__)

# 敏感字段名匹配规则（key|secret|password|token，忽略大小写）
_SENSITIVE_KEY_RE = re.compile(r'(?i)(key|secret|password|token)')


def mask_sensitive(value):
    """递归脱敏：dict/list 中 key 名匹配敏感规则的值替换为掩码（保留前4后4位）"""
    if isinstance(value, dict):
        return {
            k: (_mask_value(v) if _SENSITIVE_KEY_RE.search(str(k)) else mask_sensitive(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def _mask_value(value):
    """对敏感值打掩码：保留前 4 后 4 位，如 sk-1a***yz9"""
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= 8:
        return '***'
    return f"{value[:4]}***{value[-4:]}"


class AuditService:
    """审计服务单例：异步队列 + 后台批量 flush"""

    BATCH_SIZE = 100       # 攒满即写
    FLUSH_INTERVAL = 0.5   # 500ms 定时刷盘

    def __init__(self):
        self.queue = None
        self._task = None
        self._fallback_path = Path("audit_fallback.log")
        self._started = False

    # ---------- 生命周期 ----------

    def start(self):
        """lifespan 启动时调用：创建队列与后台消费任务"""
        if self._started:
            return
        self.queue = asyncio.Queue(maxsize=10000)
        self._task = asyncio.create_task(self._consume_loop())
        self._started = True
        logger.info("[Audit] 审计管道已启动（批量 %d 条 / %.0fms）", self.BATCH_SIZE, self.FLUSH_INTERVAL * 1000)

    async def stop(self):
        """lifespan shutdown：停止消费任务并 flush 队列残留"""
        if not self._started:
            return
        self._started = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._flush()

    # ---------- 埋点入口（业务侧调用，微秒级） ----------

    def log_from_request(self, request, action, **kwargs):
        """便捷埋点：从 request.state 自动补全 request_id / client_ip / user_agent

        业务侧用法（文档 07 显式埋点）：
            audit.log_from_request(request, "kb.create", user_id=..., ...)
        """
        try:
            state = getattr(request, 'state', None)
            kwargs.setdefault('request_id', getattr(state, 'request_id', None))
            client = getattr(request, 'client', None)
            kwargs.setdefault('client_ip', client.host if client else None)
            kwargs.setdefault('user_agent', request.headers.get('user-agent'))
        except Exception:
            pass
        return self.log(action, **kwargs)

    def log(self, action, *, user_id=None, resource_type=None, resource_id=None,
            kb_id=None, request_id=None, client_ip=None, user_agent=None, detail=None):
        """记录一条审计事件（不阻塞、不抛异常）"""
        try:
            event = {
                'occurred_at': datetime.now(timezone.utc),
                'user_id': user_id,
                'action': action,
                'resource_type': resource_type,
                'resource_id': str(resource_id) if resource_id is not None else None,
                'kb_id': kb_id,
                'request_id': request_id,
                'client_ip': client_ip,
                'user_agent': user_agent,
                'detail': mask_sensitive(detail) if detail else None,
            }
            if self.queue is None or not self._started:
                # 服务未启动（如启动期）→ 降级写本地文件
                self._fallback_write([event])
                return
            try:
                self.queue.put_nowait(event)
            except asyncio.QueueFull:
                self._fallback_write([event])
        except Exception as e:  # 双保险：审计绝不影响业务
            logger.error("[Audit] 审计入队异常: %s", e)

    # ---------- 后台消费 ----------

    async def _consume_loop(self):
        while True:
            try:
                batch = [await asyncio.wait_for(self.queue.get(), timeout=self.FLUSH_INTERVAL)]
            except asyncio.TimeoutError:
                continue
            # 尽量凑批（不阻塞等待）
            while len(batch) < self.BATCH_SIZE:
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            self._write_batch(batch)

    async def _flush(self):
        """flush 队列残留（优雅停机用）"""
        batch = []
        while True:
            try:
                batch.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            self._write_batch(batch)

    def _write_batch(self, batch):
        try:
            # psycopg2 是同步的，丢到线程池避免阻塞事件循环
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._do_insert, batch)
        except RuntimeError:
            # 无事件循环（极端情况）→ 直接同步插入
            self._do_insert(batch)

    @staticmethod
    def _do_insert(batch):
        try:
            from services.database import db
            inserted = db.insert_audit_batch(batch)
            if inserted < len(batch):
                raise RuntimeError(f"仅写入 {inserted}/{len(batch)} 条")
        except Exception as e:
            AuditService._fallback_write_static(batch)
            logger.error("[Audit] 批量落库失败，已降级写本地文件: %s", e)

    # ---------- 降级 ----------

    def _fallback_write(self, events):
        self._fallback_write_static(events)

    @staticmethod
    def _fallback_write_static(events):
        """降级：审计事件写入本地 audit_fallback.log（JSON Lines）"""
        try:
            with open(AuditService._static_fallback_path(), 'a', encoding='utf-8') as f:
                for ev in events:
                    row = dict(ev)
                    row['occurred_at'] = row['occurred_at'].isoformat()
                    row['detail'] = json.loads(json.dumps(
                        row.get('detail'), ensure_ascii=False, default=str))
                    f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        except Exception as e:
            logger.error("[Audit] 降级文件写入失败（事件丢弃）: %s", e)

    @staticmethod
    def _static_fallback_path():
        return Path("audit_fallback.log")


# 全局单例，业务侧：from services.audit import audit; audit.log(...)
audit = AuditService()


def new_request_id() -> str:
    """生成 request_id（中间件用，透传已有 X-Request-ID）"""
    return uuid.uuid4().hex
