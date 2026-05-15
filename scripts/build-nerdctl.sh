#!/bin/bash
set -e

# 获取项目版本
VERSION="${VERSION:-$(grep '^version' pyproject.toml | head -1 | awk -F'"' '{print $2}')}"
USERNAME="${DOCKER_USERNAME:-pyrominddynamics}"
IMAGE_NAME="${USERNAME}/openclaw-tracer"
PLATFORMS="linux/amd64,linux/arm64"

echo "================================"
echo "Building multi-arch ${IMAGE_NAME}:${VERSION} (nerdctl)"
echo "Platforms: ${PLATFORMS}"
echo "================================"

# 推送前需登录镜像仓库（与 docker login 用法一致）
if ! nerdctl info &>/dev/null; then
    echo "Warning: nerdctl info failed. Check nerdctl, containerd, and BuildKit."
    echo "Continuing with build (push will fail if not authenticated)..."
fi

# 使用 nerdctl + BuildKit 构建（无 docker buildx）
# 多架构推送到仓库时使用: nerdctl build ... --push
# 仅当前主机加载镜像时，可改为单平台，例如: PLATFORMS=linux/amd64
nerdctl build \
  --platform "${PLATFORMS}" \
  -t "${IMAGE_NAME}:${VERSION}" \
  -t "${IMAGE_NAME}:latest" \
  .

echo ""
echo "================================"
echo "Built successfully:"
echo "  - ${IMAGE_NAME}:${VERSION}"
echo "  - ${IMAGE_NAME}:latest"
echo ""
echo "Supported platforms: linux/amd64, linux/arm64"
echo "================================"
