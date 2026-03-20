# Docker 镜像方案设计

**Date:** 2026-03-04
**Author:** Claude
**Status:** Approved

---

## 一、概述

将 agent-data-collect 项目打包为 Docker 镜像，支持容器化部署和推送到 Docker Hub 私有仓库。

---

## 二、技术选型

| 组件 | 选择 | 理由 |
|------|------|------|
| 基础镜像 | `continuumio/miniconda3:latest` | 与本地 micromamba 环境一致 |
| 标签策略 | 固定版本号 (`v0.1.0`) + `latest` 别名 | 生产环境推荐明确版本 |
| 容器编排 | docker-compose | 简化开发和部署 |

---

## 三、架构设计

```
┌─────────────────────────────────────────────────────────┐
│                    Docker 容器                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Miniconda Base (conda-forge channel)           │   │
│  │  ┌────────────────────────────────────────────┐ │   │
│  │  │  agent-data-collect package               │ │   │
│  │  │  - LiteLLM Proxy Server (port 43886)      │ │   │
│  │  │  - Parquet Storage                        │ │   │
│  │  │  - HTTP Access Logger                     │ │   │
│  │  └────────────────────────────────────────────┘ │   │
│  │                                                     │
│  │  挂载卷:                                             │
│  │  - /app/config  → 主机配置目录                      │
│  │  - /app/data    → 主机数据目录                      │
│  │  - /app/logs    → 主机日志目录                      │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  环境变量:                                               │
│  - PORT: 服务端口 (默认 43886)                           │
│  - BUFFER_SIZE: 缓冲区大小 (默认 100)                    │
│  - TIME_WINDOW_MINUTES: 分片时间窗口 (默认 30)          │
└─────────────────────────────────────────────────────────┘
```

---

## 四、文件结构

```
agent-data-collect/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── scripts/
│   ├── build-docker.sh
│   └── push-docker.sh
└── docs/
    └── plans/
        └── 2026-03-04-docker-design.md
```

---

## 五、Dockerfile 设计

### 多阶段构建

```dockerfile
# Stage 1: Base
FROM continuumio/miniconda3:latest AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Dependencies
FROM base AS dependencies
COPY requirements.txt pyproject.toml ./
RUN conda create -n agent-data-collect python=3.10 -y
SHELL ["conda", "run", "-n", "agent-data-collect", "/bin/bash", "-c"]
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -e .

# Stage 3: Final
FROM base AS final
COPY --from=dependencies /opt/conda/envs/agent-data-collect /opt/conda/envs/agent-data-collect
COPY agent_data_collect/ /app/agent_data_collect/
COPY scripts/ /app/scripts/
RUN mkdir -p /app/config /app/data /app/logs

ENV PATH="/opt/conda/envs/agent-data-collect/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=43886 \
    BUFFER_SIZE=100 \
    TIME_WINDOW_MINUTES=30

EXPOSE 43886
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["python", "/app/scripts/serve.py", \
     "--config", "/app/config/models.json", \
     "--port", "${PORT}", \
     "--buffer-size", "${BUFFER_SIZE}", \
     "--log-file", "/app/logs/http.jsonl"]
```

---

## 六、docker-compose.yml 设计

```yaml
version: '3.8'

services:
  agent-data-collect:
    image: ${DOCKER_USERNAME}/agent-data-collect:${VERSION:-latest}
    container_name: agl-collect
    restart: unless-stopped

    ports:
      - "${HOST_PORT:-43886}:${PORT:-43886}"

    environment:
      - PORT=${PORT:-43886}
      - BUFFER_SIZE=${BUFFER_SIZE:-1}
      - TIME_WINDOW_MINUTES=${TIME_WINDOW_MINUTES:-30}

    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ./logs:/app/logs

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:43886/v1/models"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 5s

    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## 七、使用流程

### 7.1 构建镜像

```bash
export DOCKER_USERNAME=yourname
export VERSION=v0.1.0
bash scripts/build-docker.sh
```

### 7.2 推送到 Docker Hub

```bash
docker login
bash scripts/push-docker.sh
```

### 7.3 运行容器

```bash
# Docker run
docker run -d \
  --name agl-collect \
  -p 43886:43886 \
  -v $(pwd)/config:/app/config:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -e BUFFER_SIZE=1 \
  yourname/agent-data-collect:v0.1.0

# Docker Compose
docker-compose up -d
```

---

## 八、配置说明

### 挂载卷

| 容器路径 | 主机路径 | 说明 |
|----------|----------|------|
| `/app/config` | `./config` | 模型配置文件 (只读) |
| `/app/data` | `./data` | Parquet 数据持久化 |
| `/app/logs` | `./logs` | HTTP 访问日志 |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `43886` | 服务监听端口 |
| `BUFFER_SIZE` | `100` | 缓冲区大小 |
| `TIME_WINDOW_MINUTES` | `30` | 分片时间窗口（分钟） |

---

## 九、安全考虑

1. **配置文件只读挂载**：防止容器内修改配置
2. **非 root 用户运行**：后续可添加 USER 指令
3. **最小化镜像**：清理 apt 缓存、pip 缓存
4. **健康检查**：自动检测服务状态

---

## 十、后续优化

1. 添加 `.dockerignore` 减少构建上下文
2. 考虑使用 BuildKit 优化构建速度
3. 添加多架构支持 (linux/amd64, linux/arm64)
