#!/usr/bin/env bash
# RAGFlow 一键启动脚本（Git Bash 入口，实际逻辑在 start_all.ps1）
# 用法: bash start_all.sh [start|stop|status] [--milvus] [--no-redis]   默认 start
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="start"
PS_ARGS=()

for arg in "$@"; do
    case "$arg" in
        start|stop|status) ACTION="$arg" ;;
        --milvus)   PS_ARGS+=("-StartMilvus") ;;
        --no-redis) PS_ARGS+=("-NoRedis") ;;
        *) echo "未知参数: $arg（可用: start|stop|status|--milvus|--no-redis）"; exit 1 ;;
    esac
done

if command -v powershell >/dev/null 2>&1; then
    powershell -NoProfile -ExecutionPolicy Bypass -File "${SCRIPT_DIR}/start_all.ps1" -Action "${ACTION}" ${PS_ARGS[@]+"${PS_ARGS[@]}"}
else
    echo "未找到 powershell，请手动运行: powershell -ExecutionPolicy Bypass -File start_all.ps1"
    exit 1
fi
