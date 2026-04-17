"""
Memory Manager - mini-openclew 风格的记忆管理器

核心设计（参考 mini-openclew）：
1. System Prompt 动态拼接 —— 从 workspace/*.md 文件读取，无需重启服务即可修改
2. 长期记忆 —— MEMORY.md 追加式，累积知识
3. 每日日志 —— logs/YYYY-MM-DD.md

workspace/ 文件优先级（从通用到具体）：
  SYSTEM.md     → Agent 角色和能力定义
  MEMORY.md     → 积累的长期记忆
  AGENTS.md     → Agent 行为准则（可选）

与 mini-openclew 的对应关系：
  SOUL.md      → 本项目 SYSTEM.md
  MEMORY.md    → 本项目 MEMORY.md（格式相同）
  USER.md      → 暂不需要（RAG 系统多用户）
"""

import os
from datetime import datetime
from typing import Optional
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config import init_logger

logger = init_logger(__name__)

# workspace 目录（backend/workspace/）
WORKSPACE_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / "workspace"
LOGS_DIR = WORKSPACE_DIR / "logs"


class MemoryManager:
    """
    记忆管理器
    
    负责：
    - 从 workspace/*.md 拼接 System Prompt
    - 向 MEMORY.md 追加长期记忆
    - 每日对话日志写入
    """

    def __init__(self, workspace_dir: Optional[Path] = None):
        self.workspace_dir = workspace_dir or WORKSPACE_DIR
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        # 初始化 workspace 文件（若不存在）
        self._init_workspace_files()
        logger.info(f"[memory_manager] MemoryManager 初始化，workspace: {self.workspace_dir}")

    def _init_workspace_files(self):
        """初始化 workspace 默认文件"""

        system_md = self.workspace_dir / "SYSTEM.md"
        if not system_md.exists():
            system_md.write_text(
                """# RAG Agent System

你是一个专业的 RAG（检索增强生成）知识库助手。

## 核心能力
- 混合检索：同时使用向量语义检索（Milvus）和关键词检索（Elasticsearch）
- 智能精排：使用 Cross-Encoder 模型对检索结果进行相关性精排
- 查询扩展：将复杂查询分解为多个子问题，提升召回率
- 多轮对话：上下文感知，理解追问和指代

## 行为准则
1. 始终基于检索到的文档内容回答，不要凭空捏造
2. 当知识库中没有相关信息时，明确告知用户
3. 引用来源时注明文档来源（如有元数据）
4. 对于模糊查询，主动澄清用户意图
5. 回答要准确、简洁、有条理

## 回答格式
- 先直接回答核心问题
- 再补充相关背景或细节
- 最后注明信息来源（如适用）
""",
                encoding="utf-8",
            )
            logger.info(f"[memory_manager] 创建默认 SYSTEM.md")

        memory_md = self.workspace_dir / "MEMORY.md"
        if not memory_md.exists():
            memory_md.write_text(
                "# 长期记忆\n\n*（系统运行过程中会自动积累用户偏好和常见问题）*\n\n",
                encoding="utf-8",
            )
            logger.info(f"[memory_manager] 创建默认 MEMORY.md")

    def get_system_prompt(
        self,
        include_memory: bool = True,
        extra_context: Optional[str] = None,
    ) -> str:
        """
        动态拼接 System Prompt

        拼接顺序（参考 mini-openclew）：
        1. SYSTEM.md  → Agent 角色定义
        2. MEMORY.md  → 长期记忆（可选）
        3. extra_context → 当前对话相关上下文（如会话历史摘要）

        Args:
            include_memory: 是否包含长期记忆
            extra_context: 额外的上下文信息

        Returns:
            完整的 System Prompt 字符串
        """
        parts = []

        # 1. SYSTEM.md
        system_content = self._read_file("SYSTEM.md")
        if system_content:
            parts.append(system_content)

        # 2. MEMORY.md（可选）
        if include_memory:
            memory_content = self._read_file("MEMORY.md")
            if memory_content and len(memory_content.strip()) > 50:
                parts.append(f"\n---\n## 记忆上下文\n{memory_content}")

        # 3. 额外上下文
        if extra_context:
            parts.append(f"\n---\n## 当前会话上下文\n{extra_context}")

        full_prompt = "\n".join(parts)
        logger.debug(f"[memory_manager] System Prompt 拼接完成，总长度: {len(full_prompt)} 字符")
        return full_prompt

    def append_memory(
        self,
        content: str,
        category: str = "对话摘要",
    ) -> bool:
        """
        向 MEMORY.md 追加长期记忆

        Args:
            content: 要记录的内容
            category: 记忆类别标签

        Returns:
            是否成功
        """
        memory_path = self.workspace_dir / "MEMORY.md"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        entry = f"\n### [{timestamp}] {category}\n{content}\n"

        try:
            with open(memory_path, "a", encoding="utf-8") as f:
                f.write(entry)
            logger.info(f"[memory_manager] 已追加记忆: [{category}] {content[:50]}...")
            return True
        except Exception as e:
            logger.error(f"[memory_manager] 追加记忆失败: {e}")
            return False

    def write_daily_log(
        self,
        session_id: str,
        query: str,
        response: str,
        intent: str = "",
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        写入每日对话日志（追加到 logs/YYYY-MM-DD.md）

        Args:
            session_id: 会话 ID
            query: 用户查询
            response: Agent 回答（摘要，不超过 200 字符）
            intent: 识别到的意图
            metadata: 额外元数据
        """
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = LOGS_DIR / f"{today}.md"

        timestamp = datetime.now().strftime("%H:%M:%S")
        response_preview = response[:200] + ("..." if len(response) > 200 else "")

        entry_lines = [
            f"\n---",
            f"**时间**: {timestamp}",
            f"**会话**: `{session_id}`",
            f"**意图**: {intent or '未知'}",
            f"**问**: {query}",
            f"**答**: {response_preview}",
        ]

        if metadata:
            sources_count = metadata.get("sources_count", 0)
            if sources_count:
                entry_lines.append(f"**检索文档数**: {sources_count}")

        entry = "\n".join(entry_lines) + "\n"

        try:
            # 写入日志文件头（如果是新文件）
            if not log_path.exists():
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(f"# 对话日志 {today}\n\n")

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
            logger.info(f"[memory_manager] 写入每日对话日志: {session_id} {query} {response_preview}")
            return True
        except Exception as e:
            logger.error(f"[memory_manager] 写入日志失败: {e}")
            return False

    def _read_file(self, filename: str) -> Optional[str]:
        """读取 workspace 文件内容"""
        logger.info(f"[memory_manager] 读取文件: {filename}")
        path = self.workspace_dir / filename
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"读取文件失败 {filename}: {e}")
            return None

    def read_workspace_file(self, filename: str) -> Optional[str]:
        """公开接口：读取 workspace 文件"""
        logger.info(f"[memory_manager] 读取 workspace 文件: {filename}")
        return self._read_file(filename)

    def write_workspace_file(self, filename: str, content: str) -> bool:
        """公开接口：写入 workspace 文件（支持前端实时编辑）"""
        logger.info(f"[memory_manager] 写入 workspace 文件: {filename}")
        # 安全检查：只允许写 .md 文件
        if not filename.endswith(".md"):
            logger.warning(f"[memory_manager] 已拒绝写入非 .md 文件: {filename}")
            return False

        path = self.workspace_dir / filename
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"[memory_manager] 已更新 workspace 文件: {filename}")
            return True
        except Exception as e:
            logger.error(f"[memory_manager] 写入 workspace 文件失败 {filename}: {e}")
            return False

    def list_workspace_files(self) -> list:
        """列出 workspace 下所有 .md 文件"""
        logger.info(f"[memory_manager] 列出 workspace 下所有 .md 文件")
        files = []
        for path in self.workspace_dir.glob("*.md"):
            try:
                stat = path.stat()
                files.append({
                    "filename": path.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except Exception:
                pass
        return files
