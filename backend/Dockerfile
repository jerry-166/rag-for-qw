# RAG System Backend Dockerfile
# 基于 python:3.11-slim，适配 4核8G 服务器
FROM python:3.11-slim

# 系统依赖（PDF解析、编译、网络）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建必要目录
RUN mkdir -p /app/data /app/logs /app/temp /app/output

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8003/ || exit 1

# 暴露端口
EXPOSE 8003

# 启动命令：单 worker（验证期，省内存）
# 生产环境并发上来后可改为 -w 2 -k uvicorn.workers.UvicornWorker
CMD ["python", "app.py"]
