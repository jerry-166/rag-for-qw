# 圈6（收尾圈）：中断现场处理 + 启动懒加载收尾

> 本圈为 Stage 1 收尾性质，前半段在上一个被中断的会话中完成，本会话接续收尾验证。

## 1. 中断现场评估（任务步骤 1）

git status 显示圈6 留下一批未提交改动，逐一审查后判定为**完整可用，无半成品**，予以保留收尾：

| 文件 | 改动 | importtime 依据 |
|---|---|---|
| `backend/services/auth.py` | jose（JWTError/jwt）懒加载 `_jwt()`；顺带 ACCESS_TOKEN_EXPIRE_MINUTES 支持 runtime 覆盖 | jose+cryptography ~0.17s |
| `backend/services/milvus_client.py` | pymilvus 懒加载（延迟到首次连接/查询） | pymilvus（grpc/pandas）~1.7s |
| `backend/backend/app.py` + `api/files.py` | PDFParser 顶层 import 移除，请求内导入 | requests 链 ~0.2s |
| `backend/api/agent.py` | langfuse observe 延迟导入 | langfuse ~0.74s |
| `backend/services/database.py` | `Database()` 构造（同步 PG 连接+建表）延迟到首次使用 | ~0.4s |
| `backend/app.py` lifespan | tracing 初始化（langfuse import + 客户端 + auth_check 网络）移入后台任务 + 线程池，不阻塞首个 HTTP 200 | 同步路径实测 ~1.8s |

中途踩坑（已在中断前修复，本轮回归确认）：c6_run3 曾因 `_jwt()` 局部解包导致 `NameError: JWTError`，修复后登录链路正常。

## 2. 低成本优化判断（任务步骤 2）

中断会话已按 `python -X importtime` 实测挑出了上述 6 处高性价比点（见 work/stage-1/importtime_c6*.log），本会话不再新增编码，直接收尾验证。

## 3. 最终数字（任务步骤 3）

启动 → 首个 HTTP 200（uvicorn 127.0.0.1:8003，轮询 `GET /`，backend/.venv）：

| run | 耗时 |
|---|---|
| 1 | 1.27s |
| 2 | 2.68s |
| 3 | 1.66s |
| **均值** | **1.87s** |

演进：基线 28.67s → 圈1-5 7.26s（-74.7%）→ 圈6 收尾 **1.87s（-93.5%）**。
文档 01 的 <2s 目标：本轮均值 1.87s 恰好达标，但按用户裁决口径——不硬凑目标，达标与否均如实记录。

## 4. 验证（详见 verify.log 追加段）

1. `import app` → OK（1.04s）
2. 3 次启动计时见上表（work/stage-1/c6_final_bench.py）
3. 登录 `POST /api/auth/login`（admin / Stage1@Test，OAuth2 form-encoded）→ 200，token 159 字符
4. `/healthz` 就绪门：启动初期 503（约 18s，预热期含一次请求超时）→ 200，转换序列 [503, Timeout, 200] 正常
5. 就绪后 `POST /api/hybrid/search` → 200，status=success；results=0（存量 chunk 归属 user_id=0，admin 不命中，预存在现象非本轮回归）
6. 测后 taskkill 释放 8003

## 5. 备注

- 计时脚本第一版 awk 有 bug 输出了绝对时间戳，已改为 python 实现（c6_final_bench.py）后重测，数字以重测为准。
- 产物：本 notes、verify.log 追加段、c6_final_*.log/json。
