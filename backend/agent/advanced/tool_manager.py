"""
工具调用管理模块

管理工具注册、调用和错误处理，支持：
- 工具注册与发现
- 超时控制
- 重试机制
- 批量执行
- 执行统计
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
from functools import wraps, partial

import sys
import os

# 添加backend/agent目录到搜索路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# 直接导入exceptions模块
from .exceptions import (
    ToolExecutionError, ToolTimeoutError, ToolNotFoundError
)
from config import init_logger

logger = init_logger(__name__)


class ToolStatus(Enum):
    """工具执行状态"""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    RETRYING = "retrying"


@dataclass
class Tool:
    """工具定义"""
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 30.0
    max_retries: int = 2
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_execution_time: float = 0.0


@dataclass
class ToolResult:
    """工具执行结果"""
    status: ToolStatus
    data: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    retry_count: int = 0


class ToolManager:
    """
    工具管理器
    
    管理工具的注册、调用和执行统计
    """
    
    def __init__(self, default_timeout: float = 30.0, max_retries: int = 2):
        self.default_timeout = default_timeout
        self.max_retries = max_retries
        self.tools: Dict[str, Tool] = {}
        
        # 工具实现存储（延迟注入）
        self._tool_impls: Dict[str, Callable] = {}
        logger.info("工具管理器初始化")
    
    def register_tool(
        self,
        name: str,
        description: str,
        func: Callable,
        parameters: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        """
        注册工具
        
        Args:
            name: 工具名称
            description: 工具描述
            func: 工具函数
            parameters: 参数定义
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
        """
        self.tools[name] = Tool(
            name=name,
            description=description,
            func=func,
            parameters=parameters or {},
            timeout=timeout or self.default_timeout,
            max_retries=max_retries or self.max_retries,
        )
        logger.info(f"[ToolManager] 注册工具 {name}")
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """获取工具"""
        logger.info(f"[ToolManager] 获取工具 {name}")
        return self.tools.get(name)
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有工具"""
        logger.info(f"[ToolManager] 列出所有工具")
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self.tools.values()
        ]
    
    async def execute(self, name: str, **params) -> ToolResult:
        """
        执行工具
        
        Args:
            name: 工具名称
            **params: 工具参数
            
        Returns:
            ToolResult: 执行结果
        """
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(
                status=ToolStatus.NOT_FOUND,
                error=f"Tool '{name}' not found"
            )
        
        logger.info(f"[ToolManager] 开始执行工具 {name} with params: {params}")
        start_time = time.time()
        retry_count = 0
        
        while retry_count <= tool.max_retries:
            try:
                # 执行工具（带超时）
                if asyncio.iscoroutinefunction(tool.func):
                    result = await asyncio.wait_for(
                        tool.func(**params),
                        timeout=tool.timeout
                    )
                else:
                    # 同步函数在线程池中执行
                    # run_in_executor 不支持 kwargs，需要用 partial 包装
                    loop = asyncio.get_event_loop()
                    sync_call = partial(tool.func, **params)
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, sync_call),
                        timeout=tool.timeout
                    )
                
                execution_time = time.time() - start_time
                
                # 更新统计
                tool.call_count += 1
                tool.success_count += 1
                tool.total_execution_time += execution_time
                logger.info(f"[ToolManager] 工具 {name} 执行成功，耗时 {execution_time:.2f}s，重试次数 {retry_count}")
                
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    data=result,
                    execution_time=execution_time,
                    retry_count=retry_count,
                )
                
            except asyncio.TimeoutError:
                retry_count += 1
                if retry_count > tool.max_retries:
                    execution_time = time.time() - start_time
                    tool.call_count += 1
                    tool.failure_count += 1
                    tool.total_execution_time += execution_time
                    logger.error(f"[ToolManager] 工具 {name} 执行超时，耗时 {execution_time:.2f}s，重试次数 {retry_count - 1}")
                    
                    return ToolResult(
                        status=ToolStatus.TIMEOUT,
                        error=f"Tool '{name}' execution timeout after {tool.timeout}s",
                        execution_time=execution_time,
                        retry_count=retry_count - 1,
                    )
            except Exception as e:
                retry_count += 1
                print(f"[ToolManager] 异常： {e}")
                if retry_count > tool.max_retries:
                    execution_time = time.time() - start_time
                    tool.call_count += 1
                    tool.failure_count += 1
                    tool.total_execution_time += execution_time
                    logger.error(f"[ToolManager] 工具 {name} 执行失败，耗时 {execution_time:.2f}s，重试次数 {retry_count - 1}")
                    
                    return ToolResult(
                        status=ToolStatus.FAILURE,
                        error=str(e),
                        execution_time=execution_time,
                        retry_count=retry_count - 1,
                    )
        
        # 不应该执行到这里
        return ToolResult(
            status=ToolStatus.FAILURE,
            error="Unexpected error"
        )
    
    async def execute_batch(
        self,
        tool_calls: List[Dict[str, Any]],
        parallel: bool = True,
    ) -> List[ToolResult]:
        """
        批量执行工具
        
        Args:
            tool_calls: 工具调用列表，每个元素包含tool_name和params
            parallel: 是否并行执行
            
        Returns:
            List[ToolResult]: 执行结果列表
        """
        if parallel:
            # 并行执行
            logger.info(f"[ToolManager] 开始并行执行 {len(tool_calls)} 个工具调用")
            tasks = [
                self.execute(call["tool_name"], **call.get("params", {}))
                for call in tool_calls
            ]
            return await asyncio.gather(*tasks)
        else:
            # 串行执行
            logger.info(f"[ToolManager] 开始串行执行 {len(tool_calls)} 个工具调用")
            results = []
            for call in tool_calls:
                result = await self.execute(
                    call["tool_name"],
                    **call.get("params", {})
                )
                results.append(result)
            return results
    
    def get_tool_stats(self, name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取工具统计信息
        
        Args:
            name: 工具名称，为None时返回所有工具统计
            
        Returns:
            Dict: 统计信息
        """
        logger.info(f"[ToolManager] 获取工具统计信息，工具名称: {name}")
        if name:
            tool = self.get_tool(name)
            if not tool:
                return {}
            return {
                "name": tool.name,
                "call_count": tool.call_count,
                "success_count": tool.success_count,
                "failure_count": tool.failure_count,
                "success_rate": tool.success_count / tool.call_count if tool.call_count > 0 else 0,
                "avg_execution_time": tool.total_execution_time / tool.call_count if tool.call_count > 0 else 0,
            }
        else:
            # 所有工具的统计
            return {
                name: self.get_tool_stats(name)
                for name in self.tools.keys()
            }
    
    def inject_tool_impl(self, name: str, func: Callable):
        """
        注入工具实现
        
        用于在构建后注入实际的工具函数
        """
        logger.info(f"[ToolManager] 注入工具实现，工具名称: {name}")
        if name in self.tools:
            self.tools[name].func = func
        else:
            # 如果工具不存在，注册一个占位符
            self.register_tool(
                name=name,
                description=f"Injected tool: {name}",
                func=func,
            )


# 测试
if __name__ == "__main__":
    async def test():
        manager = ToolManager(default_timeout=5.0, max_retries=1)
        
        # 注册测试工具
        async def success_tool(**kwargs):
            await asyncio.sleep(0.1)
            return {"result": "success", "params": kwargs}
        
        async def error_tool(**kwargs):
            raise ValueError("Test error")
        
        async def slow_tool(**kwargs):
            await asyncio.sleep(10.0)  # 超过超时
            return "too slow"
        
        manager.register_tool("success", "成功工具", success_tool)
        manager.register_tool("error", "错误工具", error_tool)
        manager.register_tool("slow", "慢工具", slow_tool, timeout=0.5)
        
        # 测试执行
        print("测试成功工具:")
        result = await manager.execute("success", param1="value1")
        print(f"  状态: {result.status.value}")
        print(f"  数据: {result.data}")
        print(f"  耗时: {result.execution_time:.3f}s")
        
        print("\n测试错误工具:")
        result = await manager.execute("error")
        print(f"  状态: {result.status.value}")
        print(f"  错误: {result.error}")
        
        print("\n测试超时工具:")
        result = await manager.execute("slow")
        print(f"  状态: {result.status.value}")
        print(f"  错误: {result.error}")
        
        print("\n测试不存在的工具:")
        result = await manager.execute("nonexistent")
        print(f"  状态: {result.status.value}")
        
        print("\n工具统计:")
        stats = manager.get_tool_stats()
        for name, s in stats.items():
            print(f"  {name}: 调用{s['call_count']}次, 成功率{s.get('success_rate', 0):.1%}")
    
    asyncio.run(test())
