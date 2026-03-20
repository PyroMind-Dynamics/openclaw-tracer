#!/bin/bash
set -e

# 获取项目版本
VERSION="${VERSION:-$(grep '^version' pyproject.toml | head -1 | sed 's/version = "\([^"]*\)"/\1/')}"
USERNAME="${DOCKER_USERNAME:-openclawtracer}"
IMAGE_NAME="${USERNAME}/openclaw-tracer"

echo "================================"
echo "Building ${IMAGE_NAME}:${VERSION}"
echo "================================"

# 构建镜像
docker build -t ${IMAGE_NAME}:${VERSION} .
docker tag ${IMAGE_NAME}:${VERSION} ${IMAGE_NAME}:latest

echo ""
echo "Built successfully:"
echo "  - ${IMAGE_NAME}:${VERSION}"
echo "  - ${IMAGE_NAME}:latest"
echo ""
echo "To push to Docker Hub:"
echo "  docker login"
echo "  ./scripts/push-docker.sh"
