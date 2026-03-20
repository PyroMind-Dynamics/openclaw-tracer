#!/bin/bash
set -e

# 确定配置文件路径
# 优先级: 用户挂载的 /app/config/models.json > 内置空配置
if [ -f /app/config/models.json ]; then
    CONFIG_FILE="/app/config/models.json"
    echo "✓ 使用用户配置: ${CONFIG_FILE}"
else
    CONFIG_FILE="/app/config/default_models.json"
    echo "⚠ 未找到 /app/config/models.json，使用默认空配置"
    echo "  模型将通过环境变量 (TARGET_MODEL, ORIGIN_MODEL 等) 配置"
fi

# 构建启动参数
ARGS=(
    "--config" "${CONFIG_FILE}"
    "--output-dir" "/app/data"
    "--port" "${PORT:-43886}"
    "--buffer-size" "${BUFFER_SIZE:-100}"
    "--time-window" "${TIME_WINDOW_MINUTES:-30}"
    "--log-file" "/app/logs/http.jsonl"
    "--trajectory-buffer-size" "${TRAJECTORY_BUFFER_SIZE:-0}"
    "--flush-interval" "${FLUSH_INTERVAL_SECONDS:-1800}"
)

echo "=========================================="
echo " Agent Data Collect - Starting"
echo "=========================================="
echo "  Config:     ${CONFIG_FILE}"
echo "  Port:       ${PORT:-43886}"
echo "  Buffer:     ${BUFFER_SIZE:-100}"
echo "  Trajectory: ${TRAJECTORY_BUFFER_SIZE:-0}"
echo "  FlushInterval: ${FLUSH_INTERVAL_SECONDS:-1800}s"
[ -n "${TARGET_MODEL}" ] && echo "  Model:      ${TARGET_MODEL} -> ${API_MODE:+${API_MODE}/}${ORIGIN_MODEL}"
echo "=========================================="

exec python /app/scripts/serve.py "${ARGS[@]}"
