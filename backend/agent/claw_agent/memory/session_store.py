"""
文件式会话存储

参考 mini-openclew 的设计：
- 每个 session 一个 JSON 文件
- 支持创建、加载、追加、删除、列表
- 消息格式兼容 LangChain message dict
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

    def create_session(self, session_id: Optional[str] = None, title: str = "") -> str:
        """创建新会话，返回 session_id"""
        if not session_id:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"

        now = datetime.now().isoformat()
        session_data = {
            "session_id": session_id,
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
        
        logger.info(f"[session_store] 创建新会话: {session_id}")
        return session_id

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """加载会话数据"""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        
        logger.info(f"[session_store] 加载会话: {session_id}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_messages(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """获取会话消息（最近 limit 条）"""
        logger.info(f"[session_store] 获取会话消息: {session_id}")
        session = self.load_session(session_id)
        if not session:
            return []
        messages = session.get("messages", [])
        return messages[-limit:] if len(messages) > limit else messages

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """追加一条消息到会话"""
        # 确保会话存在
        if not self._session_path(session_id).exists():
            self.create_session(session_id)

        session = self.load_session(session_id)
        if session is None:
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

        path = self._session_path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[session_store] 追加消息到会话: {session_id}")
        return True

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        logger.info(f"[session_store] 删除会话: {session_id}")
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            logger.info(f"[session_store] 删除成功")
            return True
        return False

    def rename_session(self, session_id: str, title: str) -> bool:
        """重命名会话"""
        session = self.load_session(session_id)
        if not session:
            return False

        session["title"] = title
        session["updated_at"] = datetime.now().isoformat()

        path = self._session_path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[session_store] 重命名会话: {session_id}")
        return True

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """列出所有会话（按更新时间降序）"""
        sessions = []

        for path in self.sessions_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data["session_id"],
                    "title": data.get("title", path.stem),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": len(data.get("messages", [])),
                })
            except Exception as e:
                logger.warning(f"读取会话文件失败 {path}: {e}")

        # 按更新时间倒序
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions[:limit]

    def get_recent_context(
        self,
        session_id: str,
        window: int = 5,
    ) -> str:
        """
        获取最近对话的文本上下文（用于拼入 System Prompt 或传给意图分类器）

        Returns:
            格式化的对话历史字符串
        """
        messages = self.get_messages(session_id, limit=window * 2)
        if not messages:
            return ""

        lines = []
        for msg in messages:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:200]
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def clear_session(self, session_id: str) -> bool:
        """清空会话的所有消息，但保留会话本身"""
        logger.info(f"[session_store] 清空会话消息: {session_id}")
        session = self.load_session(session_id)
        if not session:
            return False

        session["messages"] = []
        session["updated_at"] = datetime.now().isoformat()

        path = self._session_path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        logger.info(f"[session_store] 清空会话消息成功: {session_id}")
        return True
