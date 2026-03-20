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
RUN conda create -n openclaw-tracer python=3.10 -y && \
    echo "conda activate openclaw-tracer" >> ~/.bashrc

# 设置 shell 为 conda 环境
SHELL ["conda", "run", "-n", "openclaw-tracer", "/bin/bash", "-c"]

# 升级 pip 并安装依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage 3: Final - 最终镜像
# ============================================
FROM dependencies AS final

# 设置环境变量
ENV PATH="/opt/conda/envs/openclaw-tracer/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=43886 \
    BUFFER_SIZE=100 \
    TIME_WINDOW_MINUTES=30

# 复制项目代码
COPY openclaw_tracer/ /app/openclaw_tracer/
COPY scripts/ /app/scripts/

# 创建必要的目录
RUN mkdir -p /app/config /app/data /app/logs

# 设置工作目录
WORKDIR /app

# 暴露端口
EXPOSE 43886

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:43886/v1/models || exit 1

# 启动命令（使用shell格式以支持环境变量替换）
CMD python /app/scripts/serve.py \
    --config /app/config/models.json \
    --output-dir /app/data \
    --port ${PORT} \
    --buffer-size ${BUFFER_SIZE} \
    --log-file /app/logs/http.jsonl
