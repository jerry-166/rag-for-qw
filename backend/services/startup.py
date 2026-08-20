"""
启动就绪信号（设计文档 01-B）

- 各初始化任务（milvus / search / agents）完成后 mark；
- 请求路径通过 wait() 带锁等待而非报错，超时/失败返回明确错误；
- /healthz 根据 snapshot() 返回 200 / 503。
"""
import asyncio
from typing import Dict, Optional

from config import init_logger, get_runtime

logger = init_logger(__name__)


class Readiness:
    def __init__(self):
        self._events: Dict[str, asyncio.Event] = {}
        self._errors: Dict[str, str] = {}

    def set_pending(self, name: str):
        """注册一个待就绪组件（重复调用不重置已 set 的事件）。"""
        if name not in self._events:
            self._events[name] = asyncio.Event()
            self._errors.pop(name, None)

    def mark(self, name: str, error: Optional[str] = None):
        """标记组件就绪；error 非空表示初始化失败（同样 set 事件，让等待方放行后读错误）。"""
        self.set_pending(name)
        if error:
            self._errors[name] = error
            logger.error(f"[Readiness] {name} 初始化失败: {error}")
        else:
            self._errors.pop(name, None)
            logger.info(f"[Readiness] {name} 就绪")
        self._events[name].set()

    def is_set(self, name: str) -> bool:
        ev = self._events.get(name)
        return bool(ev and ev.is_set())

    async def wait(self, name: str) -> None:
        """等待组件就绪；超时或初始化失败抛 RuntimeError（由调用方转 503）。"""
        ev = self._events.get(name)
        if ev is None:  # 未注册（如禁用预热）——不阻塞
            return
        timeout = float(get_runtime("STARTUP_READY_TIMEOUT", 60))
        try:
            await asyncio.wait_for(ev.wait(), timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"{name} 初始化超时（>{timeout}s）")
        err = self._errors.get(name)
        if err:
            raise RuntimeError(f"{name} 初始化失败: {err}")

    def snapshot(self) -> Dict[str, str]:
        """各组件状态：pending / ready / error。"""
        out = {}
        for name, ev in self._events.items():
            if name in self._errors:
                out[name] = f"error: {self._errors[name]}"
            elif ev.is_set():
                out[name] = "ready"
            else:
                out[name] = "pending"
        return out

    def all_ready(self) -> bool:
        return bool(self._events) and all(
            ev.is_set() and name not in self._errors
            for name, ev in self._events.items()
        )


readiness = Readiness()
