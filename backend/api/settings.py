"""
设置管理 API — 查看和修改运行时配置

大部分配置支持运行时热改（不重启）：
  1. set_runtime() 写入运行时覆盖（同步 os.environ）
  2. apply_config_change() 执行组件重建钩子（reranker / 搜索引擎 / Milvus / Agent 等）
  3. 失败自动回滚旧值
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Dict

from config import settings, get_runtime, set_runtime, clear_runtime, init_logger
from services.runtime_config import (
    WRITABLE_CONFIGS,
    apply_config_change,
    get_config_meta,
    normalize_value,
    persist_to_env,
    remove_from_env,
    validate_value,
)
from api.auth import get_current_user

router = APIRouter()
logger = init_logger(__name__)


class ConfigUpdateItem(BaseModel):
    """单个配置更新项"""
    key: str
    value: Any


class ConfigUpdateRequest(BaseModel):
    """批量配置更新请求"""
    configs: list[ConfigUpdateItem]


class ConfigUpdateResponse(BaseModel):
    status: str = "ok"
    updated: Dict[str, Any] = {}
    errors: Dict[str, str] = {}


@router.get("")
async def get_settings(_=Depends(get_current_user)):
    """获取全部配置（元信息 + 当前值，敏感项不回显明文）"""
    return {
        "status": "ok",
        **get_config_meta(),
    }


@router.put("", response_model=ConfigUpdateResponse)
async def update_settings(
    body: ConfigUpdateRequest,
    request: Request,
    _=Depends(get_current_user),
):
    """批量更新运行时配置（失败自动回滚）"""
    resp = ConfigUpdateResponse()
    app_state = request.app.state

    for item in body.configs:
        key = str(item.key).upper()
        meta = WRITABLE_CONFIGS.get(key)
        if not meta:
            resp.errors[key] = f"未知配置项: {key}"
            continue

        # 敏感项传空字符串 = 不修改
        raw_value = item.value
        if meta.get("sensitive") and str(raw_value).strip() == "":
            continue

        old_value = get_runtime(key, None)
        if old_value is None:
            old_value = getattr(settings, key, None)

        # value=null = 清除运行时覆盖，恢复 .env/默认值
        if raw_value is None:
            try:
                clear_runtime(key)
                await asyncio.to_thread(apply_config_change, key, app_state)
                # 同步从 .env 删除该项，重启后同样恢复代码默认
                try:
                    await asyncio.to_thread(remove_from_env, key)
                except Exception as e:
                    logger.warning(f"[Settings] {key} 从 .env 移除失败: {e}")
            except Exception as e:
                logger.warning(f"[Settings] {key} 清除失败，回滚: {e}")
                if old_value is not None:
                    set_runtime(key, old_value)
                try:
                    await asyncio.to_thread(apply_config_change, key, app_state)
                except Exception as rollback_err:
                    logger.error(f"[Settings] {key} 清除回滚失败，需要重启服务: {rollback_err}")
                resp.errors[key] = f"配置清除失败（已回滚）: {e}"
                continue
            resp.updated[key] = None
            continue

        # 校验
        err = validate_value(key, raw_value)
        if err:
            resp.errors[key] = err
            continue

        new_value = normalize_value(key, raw_value)

        # 写入运行时覆盖
        set_runtime(key, new_value)

        # 写回 .env 持久化，重启后仍生效（写盘失败不影响本次运行时生效）
        try:
            await asyncio.to_thread(persist_to_env, key, new_value)
        except Exception as e:
            logger.warning(f"[Settings] {key} 写入 .env 失败（重启后会丢失）: {e}")

        # 执行应用钩子（组件重建），在独立线程执行避免阻塞事件循环，失败回滚
        try:
            await asyncio.to_thread(apply_config_change, key, app_state)
        except Exception as e:
            logger.warning(f"[Settings] {key} 应用失败，回滚: {e}")
            try:
                if old_value is not None:
                    set_runtime(key, old_value)
                else:
                    clear_runtime(key)
                await asyncio.to_thread(apply_config_change, key, app_state)
            except Exception as rollback_err:
                logger.error(f"[Settings] {key} 回滚失败，需要重启服务: {rollback_err}")
            resp.errors[key] = f"配置应用失败（已回滚）: {e}"
            continue

        resp.updated[key] = new_value

    if resp.errors:
        resp.status = "partial_error"

    return resp
