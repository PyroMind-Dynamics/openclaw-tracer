# Docker 镜像实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-step.

**目标:** 将 agent-data-collect 项目打包为 Docker 镜像，支持容器化部署并推送到 Docker Hub。

**架构:** 使用 Miniconda 基础镜像，多阶段构建优化镜像大小，支持配置/数据/日志目录挂载，通过环境变量灵活配置。

**技术栈:** Docker, Docker Compose, Miniconda, Python 3.10

---

## Task 1: 创建 .dockerignore 文件

**文件:**
- 创建: `.dockerignore`

**目的:** 排除不必要的文件，减小构建上下文大小，加快构建速度。

**Step 1: 创建 .dockerignore 文件**

```bash
# 创建文件
cat > /workspace/agent-data-collect/.dockerignore << 'EOF'
# Git
.git
.gitignore
.gitattributes

# Documentation
*.md
docs/

# Python
__pycache__
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
env/
ENV/
.conda/
micromamba/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/

# Data and logs (will be mounted as volumes)
data/
logs/
*.parquet
*.jsonl

# Config examples (user should provide their own)
config/*.example.json

# Claude
.claude/

# OS
.DS_Store
Thumbs.db
EOF
```

**Step 2: 验证文件创建**

```bash
cat /workspace/agent-data-collect/.dockerignore
```

预期: 看到 .dockerignore 内容

**Step 3: 提交**

```bash
cd /workspace/agent-data-collect
git add .dockerignore
git commit -m "chore: add .dockerignore for Docker builds"
```

---

## Task 2: 创建 Dockerfile

**文件:**
- 创建: `Dockerfile`

**目的:** 定义多阶段构建流程，创建优化的 Docker 镜像。

**Step 1: 创建 Dockerfile**

```bash
cat > /workspace/agent-data-collect/Dockerfile << 'EOF'
# ============================================
# Stage 1: Base - 系统依赖
# ============================================
FROM continuumio/miniconda3:latest AS base

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# ============================================
# Stage 2: Dependencies - Python 环境
# ============================================
FROM base AS dependencies

# 复制依赖文件
COPY requirements.txt pyproject.toml ./

# 创建 conda 环境
RUN conda create -n agent-data-collect python=3.10 -y && \
    echo "conda activate agent-data-collect" >> ~/.bashrc

# 设置 shell 为 conda 环境
SHELL ["conda", "run", "-n", "agent-data-collect", "/bin/bash", "-c"]

# 升级 pip 并安装依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -e .

# ============================================
# Stage 3: Final - 最终镜像
# ============================================
FROM base AS final

# 复制 conda 环境
COPY --from=dependencies /opt/conda/envs/agent-data-collect /opt/conda/envs/agent-data-collect

# 设置环境变量
ENV PATH="/opt/conda/envs/agent-data-collect/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=43886 \
    BUFFER_SIZE=100 \
    TIME_WINDOW_MINUTES=30

# 复制项目代码
COPY agent_data_collect/ /app/agent_data_collect/
COPY scripts/ /app/scripts/

# 创建必要的目录
RUN mkdir -p /app/config /app/data /app/logs

# 设置工作目录
WORKDIR /app

# 暴露端口
EXPOSE 43886

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/v1/models || exit 1

# 启动命令
CMD ["python", "/app/scripts/serve.py", \
     "--config", "/app/config/models.json", \
     "--port", "${PORT}", \
     "--buffer-size", "${BUFFER_SIZE}", \
     "--log-file", "/app/logs/http.jsonl"]
EOF
```

**Step 2: 验证 Dockerfile 语法**

```bash
cd /workspace/agent-data-collect
docker build --check -f Dockerfile . 2>&1 | head -20
```

预期: 无语法错误（Docker 版本支持 --check）

**Step 3: 提交**

```bash
git add Dockerfile
git commit -m "feat: add Dockerfile for containerization"
```

---

## Task 3: 创建 docker-compose.yml

**文件:**
- 创建: `docker-compose.yml`

**目的:** 简化容器启动和配置管理。

**Step 1: 创建 docker-compose.yml**

```bash
cat > /workspace/agent-data-collect/docker-compose.yml << 'EOF'
version: '3.8'

services:
  agent-data-collect:
    image: ${DOCKER_USERNAME:-agentdatacollect}/agent-data-collect:${VERSION:-latest}
    container_name: agl-collect
    restart: unless-stopped

    # 端口映射
    ports:
      - "${HOST_PORT:-43886}:${PORT:-43886}"

    # 环境变量
    environment:
      - PORT=${PORT:-43886}
      - BUFFER_SIZE=${BUFFER_SIZE:-1}
      - TIME_WINDOW_MINUTES=${TIME_WINDOW_MINUTES:-30}

    # 挂载卷
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ./logs:/app/logs

    # 健康检查
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:43886/v1/models"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 5s

    # 日志配置
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

    # 资源限制（可选）
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '0.5'
          memory: 1G
EOF
```

**Step 2: 验证 YAML 语法**

```bash
docker-compose config > /dev/null 2>&1 && echo "Valid" || echo "Invalid"
```

预期: 输出 "Valid"

**Step 3: 提交**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose configuration"
```

---

## Task 4: 创建构建脚本

**文件:**
- 创建: `scripts/build-docker.sh`

**目的:** 简化镜像构建流程，自动添加标签。

**Step 1: 创建构建脚本**

```bash
cat > /workspace/agent-data-collect/scripts/build-docker.sh << 'EOF'
#!/bin/bash
set -e

# 获取项目版本
VERSION="${VERSION:-$(grep '^version' pyproject.toml | head -1 | sed 's/version = "\([^"]*\)"/\1/')}"
USERNAME="${DOCKER_USERNAME:-agentdatacollect}"
IMAGE_NAME="${USERNAME}/agent-data-collect"

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
EOF

chmod +x /workspace/agent-data-collect/scripts/build-docker.sh
```

**Step 2: 验证脚本可执行**

```bash
ls -la /workspace/agent-data-collect/scripts/build-docker.sh
```

预期: 文件有执行权限 ( -rwxr-xr-x )

**Step 3: 提交**

```bash
git add scripts/build-docker.sh
git commit -m "feat: add Docker build script"
```

---

## Task 5: 创建推送脚本

**文件:**
- 创建: `scripts/push-docker.sh`

**目的:** 简化镜像推送到 Docker Hub 的流程。

**Step 1: 创建推送脚本**

```bash
cat > /workspace/agent-data-collect/scripts/push-docker.sh << 'EOF'
#!/bin/bash
set -e

# 获取项目版本
VERSION="${VERSION:-$(grep '^version' pyproject.toml | head -1 | sed 's/version = "\([^"]*\)"/\1/')}"
USERNAME="${DOCKER_USERNAME:-agentdatacollect}"
IMAGE_NAME="${USERNAME}/agent-data-collect"

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
EOF

chmod +x /workspace/agent-data-collect/scripts/push-docker.sh
```

**Step 2: 验证脚本可执行**

```bash
ls -la /workspace/agent-data-collect/scripts/push-docker.sh
```

预期: 文件有执行权限

**Step 3: 提交**

```bash
git add scripts/push-docker.sh
git commit -m "feat: add Docker push script"
```

---

## Task 6: 创建 .env.example 文件

**文件:**
- 创建: `.env.example`

**目的:** 提供环境变量配置示例。

**Step 1: 创建 .env.example**

```bash
cat > /workspace/agent-data-collect/.env.example << 'EOF'
# Docker Hub 用户名
DOCKER_USERNAME=your-dockerhub-username

# 镜像版本（默认从 pyproject.toml 读取）
VERSION=v0.1.0

# 容器内服务端口
PORT=43886

# 主机映射端口
HOST_PORT=43886

# 缓冲区大小
BUFFER_SIZE=1

# 分片时间窗口（分钟）
TIME_WINDOW_MINUTES=30
EOF
```

**Step 2: 提交**

```bash
git add .env.example
git commit -m "feat: add environment variables example"
```

---

## Task 7: 更新 README.md

**文件:**
- 修改: `README.md`

**目的:** 添加 Docker 使用说明。

**Step 1: 在 README.md 中添加 Docker 部分**

在 README.md 文件末尾添加：

```bash
cat >> /workspace/agent-data-collect/README.md << 'EOF'

## Docker 部署

### 构建镜像

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑配置（修改 DOCKER_USERNAME）
vim .env

# 构建镜像
./scripts/build-docker.sh
```

### 推送到 Docker Hub

```bash
# 登录 Docker Hub
docker login

# 推送镜像
./scripts/push-docker.sh
```

### 运行容器

#### 使用 docker run

```bash
docker run -d \
  --name agl-collect \
  -p 43886:43886 \
  -v $(pwd)/config:/app/config:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -e BUFFER_SIZE=1 \
  your-dockerhub-username/agent-data-collect:v0.1.0
```

#### 使用 docker-compose

```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `43886` | 容器内服务端口 |
| `BUFFER_SIZE` | `1` | 缓冲区大小 |
| `TIME_WINDOW_MINUTES` | `30` | 分片时间窗口（分钟） |
EOF
```

**Step 2: 提交**

```bash
git add README.md
git commit -m "docs: add Docker deployment instructions"
```

---

## Task 8: 本地测试镜像

**目的:** 验证镜像构建和运行正常。

**Step 1: 构建测试镜像**

```bash
cd /workspace/agent-data-collect
DOCKER_USERNAME=test VERSION=test ./scripts/build-docker.sh
```

预期: 构建成功，显示 "Built successfully"

**Step 2: 测试运行容器**

```bash
# 确保配置文件存在
ls config/models.json

# 运行容器（测试模式，不推送）
docker run --rm -it \
  --name agl-test \
  -p 43886:43886 \
  -v $(pwd)/config:/app/config:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -e BUFFER_SIZE=1 \
  test/agent-data-collect:test
```

预期: 服务启动成功，显示 "代理服务器已启动"

**Step 3: 测试 API 访问**

```bash
# 在另一个终端测试
curl -X POST "http://localhost:43886/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer EMPTY" \
  -d '{"model":"GLM-4.7-Flash-FP8","messages":[{"role":"user","content":"Hi"}],"max_tokens":10}'
```

预期: 返回模型响应

**Step 4: 清理测试容器**

```bash
docker stop agl-test 2>/dev/null || true
```

**Step 5: 提交**

```bash
git commit --allow-empty -m "test: verify Docker image builds and runs correctly"
```

---

## Task 9: 构建并推送生产镜像

**目的:** 创建正式的生产镜像并推送到 Docker Hub。

**Step 1: 设置环境变量**

```bash
export DOCKER_USERNAME=your-actual-dockerhub-username
export VERSION=v0.1.0
```

**Step 2: 构建生产镜像**

```bash
cd /workspace/agent-data-collect
./scripts/build-docker.sh
```

预期: 显示正确的镜像名称

**Step 3: 登录 Docker Hub**

```bash
docker login
```

输入用户名和密码

**Step 4: 推送镜像**

```bash
./scripts/push-docker.sh
```

预期: 显示 "Pushed successfully!"

**Step 5: 验证推送**

```bash
# 查看本地镜像
docker images | grep agent-data-collect

# 尝试拉取验证
docker pull ${DOCKER_USERNAME}/agent-data-collect:v0.1.0
```

**Step 6: 更新文档记录**

```bash
git commit --allow-empty -m "release: Docker image v0.1.0 pushed to Docker Hub"
```

---

## 验证清单

完成以下检查确认实施成功：

- [ ] `.dockerignore` 文件创建并生效
- [ ] `Dockerfile` 构建成功无错误
- [ ] `docker-compose.yml` 语法正确
- [ ] 构建和推送脚本可执行
- [ ] 本地测试容器能正常启动
- [ ] API 请求返回正确响应
- [ ] 镜像成功推送到 Docker Hub
- [ ] README.md 包含 Docker 使用说明
- [ ] 数据和日志目录正确挂载

---

## 故障排查

### 构建失败

```bash
# 查看详细构建日志
docker build --no-cache --progress=plain -t test/agent-data-collect:test .
```

### 容器启动失败

```bash
# 查看容器日志
docker logs agl-collect

# 进入容器调试
docker exec -it agl-collect /bin/bash
```

### 网络问题

```bash
# 检查端口映射
docker port agl-collect

# 测试容器内网络
docker exec agl-collect curl http://localhost:43886/v1/models
```
