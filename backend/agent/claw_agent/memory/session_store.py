"""
文件式会话存储

参考 mini-openclew 的设计：
- 每个 session 一个 JSON 文件
- 支持创建、加载、追加、删除、列表
- 消息格式兼容 LangChain message dict

安全说明（P0 修复）：
- 所有方法均需 user_id 参数，按用户隔离会话
- user_id=None 表示 admin 角色调用，跳过属主校验返回全量
- 无 user_id 字段的存量会话视为 ownerless（仅 admin 可见）
"""

import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import settings, init_logger

logger = init_logger(__name__)

# 会话存储目录（相对 backend/）
SESSIONS_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / "sessions"


class SessionStore:
    """
    文件式会话存储

    每个会话对应 sessions/{session_id}.json，格式：
    {
        "session_id": "...",
        "user_id": 123,           # 属主用户 ID，null 表示 ownerless（admin 可见）
        "created_at": "ISO8601",
        "updated_at": "ISO8601",
        "title": "会话标题（自动从第一条消息生成）",
        "messages": [
            {"role": "user", "content": "...", "timestamp": "..."},
            {"role": "assistant", "content": "...", "timestamp": "...",
             "metadata": {"intent": "...", "sources": [...]}},
        ]
    }
    """

    def __init__(self, sessions_dir: Optional[Path] = None):
        self.sessions_dir = sessions_dir or SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[session_store] SessionStore 初始化，存储目录: {self.sessions_dir}")

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    @staticmethod
    def _is_owner(session_data: Dict[str, Any], user_id: Optional[int]) -> bool:
        """
        校验会话属主。

        - user_id=None → admin 调用，跳过校验返回 True
        - 会话无 user_id 字段（ownerless）→ 仅 admin 可见，user_id != None 时返回 False
        - 正常会话 → data["user_id"] == user_id
        """
        if user_id is None:
            return True
        session_user_id = session_data.get("user_id")
        if session_user_id is None:
            # ownerless 会话，仅 admin 可见
            return False
        return session_user_id == user_id

    def create_session(
        self,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        title: str = "",
    ) -> str:
        """创建新会话，返回 session_id

        Args:
            user_id: 属主用户 ID（None 表示 admin 或未认证场景，会话将为 ownerless）
            session_id: 可选，不提供则自动生成
            title: 会话标题
        """
        if not session_id:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"

        now = datetime.now().isoformat()
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now,
            "updated_at": now,
            "title": title or f"会话 {session_id[:8]}",
            "messages": [],
        }

        path = self._session_path(session_id)
        if path.exists():
            logger.debug(f"会话已存在，跳过创建: {session_id}")
            return session_id

        with open(path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        logger.info(f"[session_store] 创建新会话: {session_id}, user_id={user_id}")
        return session_id

    def load_session(
        self,
        session_id: str,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """加载会话数据（校验属主）

        Args:
            session_id: 会话 ID
            user_id: 调用者用户 ID，None 表示 admin（跳过属主校验）

        Returns:
            会话数据 dict，不存在或不属于该用户则返回 None
        """
        path = self._session_path(session_id)
        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not self._is_owner(data, user_id):
            # 不属于该用户，视为不存在（避免泄露会话存在性信息）
            logger.warning(f"[session_store] 会话属主校验失败: session={session_id}, user_id={user_id}")
            return None

        logger.info(f"[session_store] 加载会话: {session_id}, user_id={user_id}")
        return data

    def get_messages(
        self,
        session_id: str,
        user_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """获取会话消息（最近 limit 条，校验属主）"""
        logger.info(f"[session_store] 获取会话消息: {session_id}, user_id={user_id}")
        session = self.load_session(session_id, user_id=user_id)
        if not session:
            return []
        messages = session.get("messages", [])
        return messages[-limit:] if len(messages) > limit else messages

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """追加一条消息到会话（校验属主）

        如果会话不存在则创建（带 user_id）。
        如果会话存在但不属于该用户，返回 False。
        """
        path = self._session_path(session_id)
        if not path.exists():
            self.create_session(user_id=user_id, session_id=session_id)

        session = self.load_session(session_id, user_id=user_id)
        if session is None:
            # 属主校验失败
            return False

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            message["metadata"] = metadata

        session["messages"].append(message)
        session["updated_at"] = datetime.now().isoformat()

        # 自动从第一条用户消息生成标题
        if len(session["messages"]) == 1 and role == "user":
            session["title"] = content[:30] + ("..." if len(content) > 30 else "")

        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        logger.info(f"[session_store] 追加消息到会话: {session_id}, user_id={user_id}")
        return True

    def delete_session(
        self,
        session_id: str,
        user_id: Optional[int] = None,
    ) -> bool:
        """删除会话（校验属主）"""
        logger.info(f"[session_store] 删除会话: {session_id}, user_id={user_id}")

        # 先校验属主
        session = self.load_session(session_id, user_id=user_id)
        if not session:
            return False

        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            logger.info(f"[session_store] 删除成功")
            return True
        return False

    def rename_session(
        self,
        session_id: str,
        title: str,
        user_id: Optional[int] = None,
    ) -> bool:
        """重命名会话（校验属主）"""
        session = self.load_session(session_id, user_id=user_id)
        if not session:
            return False

        session["title"] = title
        session["updated_at"] = datetime.now().isoformat()

        path = self._session_path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        logger.info(f"[session_store] 重命名会话: {session_id}, user_id={user_id}")
        return True

    def list_sessions(
        self,
        user_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """列出会话（按更新时间降序，按 user_id 过滤）

        Args:
            user_id: 调用者用户 ID。None 表示 admin，返回全部（含 ownerless）
            limit: 最多返回条数
        """
        sessions = []

        for path in self.sessions_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 属主过滤
                if not self._is_owner(data, user_id):
                    continue

                sessions.append({
                    "session_id": data["session_id"],
                    "title": data.get("title", path.stem),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": len(data.get("messages", [])),
                    "user_id": data.get("user_id"),
                })
            except Exception as e:
                logger.warning(f"读取会话文件失败 {path}: {e}")

        # 按更新时间倒序
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions[:limit]

    def get_recent_context(
        self,
        session_id: str,
        user_id: Optional[int] = None,
        window: int = 5,
    ) -> str:
        """
        获取最近对话的文本上下文（用于拼入 System Prompt 或传给意图分类器）

        Returns:
            格式化的对话历史字符串
        """
        messages = self.get_messages(session_id, user_id=user_id, limit=window * 2)
        if not messages:
            return ""

        lines = []
        for msg in messages:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:200]
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def clear_session(
        self,
        session_id: str,
        user_id: Optional[int] = None,
    ) -> bool:
        """清空会话的所有消息，但保留会话本身（校验属主）"""
        logger.info(f"[session_store] 清空会话消息: {session_id}, user_id={user_id}")
        session = self.load_session(session_id, user_id=user_id)
        if not session:
            return False

        session["messages"] = []
        session["updated_at"] = datetime.now().isoformat()

        path = self._session_path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        logger.info(f"[session_store] 清空会话消息成功: {session_id}, user_id={user_id}")
        return True
