#!/bin/bash
set -euo pipefail

# 在项目根目录执行 build（保证 -f Dockerfile 与上下文 . 正确）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

VERSION="${1:-}"
if [[ -z "${VERSION}" ]]; then
    echo "错误: 必须传入镜像版本号参数（必填）。" >&2
    echo "用法: $0 <版本号>" >&2
    echo "示例: $0 0.1.5.beta-1" >&2
    exit 1
fi

IMAGE="pyrominddynamics/openclaw-tracer:${VERSION}"

run_nerdctl() {
    if "$@"; then
        return 0
    fi
    echo "命令失败，使用 sudo 重试: $*" >&2
    sudo "$@"
}

echo "================================"
echo "镜像: ${IMAGE}"
echo "================================"

run_nerdctl nerdctl build -t "${IMAGE}" -f Dockerfile .
run_nerdctl nerdctl push "${IMAGE}"

echo ""
echo "================================"
echo "构建并推送完成: ${IMAGE}"
echo "================================"
