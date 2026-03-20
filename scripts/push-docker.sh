#!/bin/bash
set -e

# 获取项目版本
VERSION="${VERSION:-$(grep '^version' pyproject.toml | head -1 | sed 's/version = "\([^"]*\)"/\1/')}"
USERNAME="${DOCKER_USERNAME:-openclawtracer}"
IMAGE_NAME="${USERNAME}/openclaw-tracer"

echo "================================"
echo "Pushing ${IMAGE_NAME}:${VERSION}"
echo "================================"

# 检查是否已登录
if ! docker info | grep -q "Username"; then
    echo "Not logged in to Docker Hub."
    echo "Please run: docker login"
    exit 1
fi

# 推送镜像
docker push ${IMAGE_NAME}:${VERSION}
docker push ${IMAGE_NAME}:latest

echo ""
echo "Pushed successfully!"
echo "Pull with:"
echo "  docker pull ${IMAGE_NAME}:${VERSION}"
