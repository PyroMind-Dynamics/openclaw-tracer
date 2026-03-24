#!/bin/bash
set -e

# 获取项目版本
VERSION="${VERSION:-$(grep '^version' pyproject.toml | head -1 | awk -F'"' '{print $2}')}"
USERNAME="${DOCKER_USERNAME:-pyrominddynamics}"
IMAGE_NAME="${USERNAME}/openclaw-tracer"
PLATFORMS="linux/amd64,linux/arm64"

echo "================================"
echo "Building multi-arch ${IMAGE_NAME}:${VERSION}"
echo "Platforms: ${PLATFORMS}"
echo "================================"

# 确保已登录 Docker Hub
if ! docker info | grep -q "Username"; then
    echo "Warning: Not logged in to Docker Hub. Run 'docker login' first."
    echo "Continuing with build (push will fail if not authenticated)..."
fi

# 创建并使用 buildx builder（如果不存在）
BUILDER_NAME="multiarch-builder"
if ! docker buildx inspect ${BUILDER_NAME} &>/dev/null; then
    echo "Creating buildx builder: ${BUILDER_NAME}"
    docker buildx create --name ${BUILDER_NAME} --driver docker-container --use
else
    echo "Using existing buildx builder: ${BUILDER_NAME}"
    docker buildx use ${BUILDER_NAME}
fi

# 构建并推送多架构镜像
docker buildx build \
  --platform ${PLATFORMS} \
  -t ${IMAGE_NAME}:${VERSION} \
  -t ${IMAGE_NAME}:latest \
  --load \
  .

echo ""
echo "================================"
echo "Built and successfully:"
echo "  - ${IMAGE_NAME}:${VERSION}"
echo "  - ${IMAGE_NAME}:latest"
echo ""
echo "Supported platforms: linux/amd64, linux/arm64"
echo "================================"
