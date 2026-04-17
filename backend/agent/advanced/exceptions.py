"""
异常处理模块

定义Agent系统的异常类型和处理策略
"""
from typing import Optional, Dict, Any
from enum import Enum


class ErrorSeverity(Enum):
    """错误严重级别"""
    LOW = "low"           # 可忽略，继续执行
    MEDIUM = "medium"     # 需要处理，但可恢复
    HIGH = "high"         # 严重错误，可能需要重试
    CRITICAL = "critical" # 致命错误，终止执行


class AgentException(Exception):
    """Agent基础异常"""
    
    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
    ):
        super().__init__(message)
        self.message = message
        self.severity = severity
        self.error_code = error_code or "AGENT_ERROR"
        self.details = details or {}
        self.recoverable = recoverable
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "severity": self.severity.value,
            "details": self.details,
            "recoverable": self.recoverable,
        }


class IntentClassificationError(AgentException):
    """意图识别错误"""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=message,
            severity=ErrorSeverity.MEDIUM,
            error_code="INTENT_CLASSIFICATION_ERROR",
            details=details,
            recoverable=True,
        )


class EntityExtractionError(AgentException):
    """实体提取错误"""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=message,
            severity=ErrorSeverity.LOW,
            error_code="ENTITY_EXTRACTION_ERROR",
            details=details,
            recoverable=True,
        )


class TaskPlanningError(AgentException):
    """任务规划错误"""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=message,
            severity=ErrorSeverity.HIGH,
            error_code="TASK_PLANNING_ERROR",
            details=details,
            recoverable=True,
        )


class ToolExecutionError(AgentException):
    """工具执行错误"""
    
    def __init__(
        self,
        message: str,
        tool_name: Optional[str] = None,
        details: Optional[Dict] = None,
    ):
        super().__init__(
            message=message,
            severity=ErrorSeverity.HIGH,
            error_code="TOOL_EXECUTION_ERROR",
            details={"tool_name": tool_name, **(details or {})},
            recoverable=True,
        )
        self.tool_name = tool_name


class ToolTimeoutError(ToolExecutionError):
    """工具执行超时"""
    
    def __init__(self, tool_name: str, timeout: float):
        super().__init__(
            message=f"Tool '{tool_name}' execution timeout after {timeout}s",
            tool_name=tool_name,
            details={"timeout": timeout},
        )
        self.severity = ErrorSeverity.MEDIUM
        self.error_code = "TOOL_TIMEOUT_ERROR"


class ToolNotFoundError(ToolExecutionError):
    """工具未找到"""
    
    def __init__(self, tool_name: str):
        super().__init__(
            message=f"Tool '{tool_name}' not found",
            tool_name=tool_name,
        )
        self.severity = ErrorSeverity.HIGH
        self.error_code = "TOOL_NOT_FOUND_ERROR"
        self.recoverable = False


class ConversationError(AgentException):
    """对话管理错误"""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=message,
            severity=ErrorSeverity.MEDIUM,
            error_code="CONVERSATION_ERROR",
            details=details,
            recoverable=True,
        )


class ConfigurationError(AgentException):
    """配置错误"""
    
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            message=message,
            severity=ErrorSeverity.CRITICAL,
            error_code="CONFIGURATION_ERROR",
            details=details,
            recoverable=False,
        )


class RateLimitError(AgentException):
    """限流错误"""
    
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(
            message=message,
            severity=ErrorSeverity.MEDIUM,
            error_code="RATE_LIMIT_ERROR",
            details={"retry_after": retry_after},
            recoverable=True,
        )
        self.retry_after = retry_after


class ErrorHandler:
    """错误处理器"""
    
    # 用户友好的错误消息映射
    ERROR_MESSAGES = {
        "INTENT_CLASSIFICATION_ERROR": "我理解您的意图时遇到了困难，能否换个方式描述？",
        "ENTITY_EXTRACTION_ERROR": "我在识别关键信息时遇到了问题，但不影响继续回答。",
        "TASK_PLANNING_ERROR": "我在规划处理步骤时遇到了问题，请稍后再试。",
        "TOOL_EXECUTION_ERROR": "执行相关操作时出错，请稍后再试。",
        "TOOL_TIMEOUT_ERROR": "操作超时了，可能是网络问题，请稍后再试。",
        "TOOL_NOT_FOUND_ERROR": "所需的工具不可用，请联系管理员。",
        "CONVERSATION_ERROR": "对话处理出错，请重新开始对话。",
        "CONFIGURATION_ERROR": "系统配置错误，请联系管理员。",
        "RATE_LIMIT_ERROR": "请求太频繁了，请稍后再试。",
        "AGENT_ERROR": "处理时出现了问题，请稍后再试。",
    }
    
    @classmethod
    def handle(cls, error: Exception) -> Dict[str, Any]:
        """
        处理异常，返回标准化的错误响应
        
        Args:
            error: 异常对象
            
        Returns:
            Dict: 包含错误信息的字典
        """
        if isinstance(error, AgentException):
            error_info = error.to_dict()
            user_message = cls.ERROR_MESSAGES.get(
                error.error_code,
                "抱歉，处理您的请求时出现了问题。"
            )
        else:
            error_info = {
                "error_code": "UNKNOWN_ERROR",
                "message": str(error),
                "severity": ErrorSeverity.HIGH.value,
                "details": {},
                "recoverable": True,
            }
            user_message = "抱歉，系统遇到了意外错误。"
        
        return {
            "error": error_info,
            "user_message": user_message,
            "should_retry": error_info.get("recoverable", True) and 
                           error_info.get("severity") != ErrorSeverity.CRITICAL.value,
        }
    
    @classmethod
    def get_user_message(cls, error_code: str) -> str:
        """获取用户友好的错误消息"""
        return cls.ERROR_MESSAGES.get(error_code, "抱歉，处理您的请求时出现了问题。")


# 装饰器：自动异常处理
def handle_exceptions(fallback_return=None):
    """自动异常处理装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except AgentException as e:
                # 已处理的异常，继续抛出
                raise
            except Exception as e:
                # 未处理的异常，包装后抛出
                raise AgentException(
                    message=f"Unexpected error in {func.__name__}: {str(e)}",
                    severity=ErrorSeverity.HIGH,
                    error_code="UNEXPECTED_ERROR",
                    details={"function": func.__name__, "original_error": str(e)},
                )
        return wrapper
    return decorator
