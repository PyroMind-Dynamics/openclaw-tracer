# Python 脚本使用方式

使用 `micromamba run -n OpenClaw-Tracer python scripts/XXX.py` 替代 `OpenClaw-Tracer` 命令。

---

## 脚本对照表

| OpenClaw-Tracer 命令 | Python 脚本 |
|------------------|-------------|
| `OpenClaw-Tracer serve` | `python scripts/serve.py` |
| `OpenClaw-Tracer export` | `python scripts/export.py` |
| `OpenClaw-Tracer inspect` | `python scripts/show_file.py` |
| `OpenClaw-Tracer stats` | `python scripts/show_stats.py` |

---

## 1. 启动代理服务器

**CLI 命令:**
```bash
OpenClaw-Tracer serve --config config/models.json --output-dir ./data
```

**Python 脚本:**
```bash
micromamba run -n OpenClaw-Tracer python scripts/serve.py \
    --config config/models.json \
    --output-dir ./data
```

**直接运行:**
```bash
cd /workspace/OpenClaw-Tracer
micromamba run -n OpenClaw-Tracer python scripts/serve.py --config config/models.json
```

**参数:**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--config`, `-c` | 配置文件路径 | 无 |
| `--output-dir`, `-o` | 输出目录 | `data` |
| `--port`, `-p` | 监听端口 | 自动选择 |
| `--host` | 监听地址 | `0.0.0.0` |
| `--buffer-size` | 缓冲区大小 | `100` |

---

## 2. 导出数据

**CLI 命令:**
```bash
OpenClaw-Tracer export data/sft_records.parquet output/trl_data --format trl --type sft
```

**Python 脚本:**
```bash
micromamba run -n OpenClaw-Tracer python scripts/export.py \
    data/sft_records.parquet \
    output/trl_data \
    --format trl \
    --type sft
```

**参数:**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `input_parquet` | 输入 Parquet 文件 | 必填 |
| `output_path` | 输出路径 | 必填 |
| `--format`, `-f` | 导出格式 (trl, hf) | `trl` |
| `--type`, `-t` | 数据类型 (sft, rl) | `sft` |

---

## 3. 检查数据文件

**CLI 命令:**
```bash
OpenClaw-Tracer inspect data/sft_records.parquet --limit 5
```

**Python 脚本:**
```bash
micromamba run -n OpenClaw-Tracer python scripts/inspect.py \
    data/sft_records.parquet \
    --limit 5
```

**参数:**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `parquet_path` | Parquet 文件路径 | 必填 |
| `--limit`, `-l` | 显示记录数 | `10` |

---

## 4. 查看统计信息

**CLI 命令:**
```bash
OpenClaw-Tracer stats --output-dir ./data
```

**Python 脚本:**
```bash
micromamba run -n OpenClaw-Tracer python scripts/stats.py \
    --output-dir ./data
```

**参数:**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--output-dir`, `-o` | 数据目录 | `data` |

---

## 完整使用示例

### 场景1: 启动代理并收集数据

```bash
# 终端1: 启动代理
micromamba run -n OpenClaw-Tracer python scripts/serve.py \
    --config config/models.json \
    --output-dir ./data

# 终端2: 发送请求
curl http://localhost:43886/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello!"}]}'

# 终端3: 查看统计
micromamba run -n OpenClaw-Tracer python scripts/stats.py
```

### 场景2: 导出并训练

```bash
# 1. 查看收集的数据
micromamba run -n OpenClaw-Tracer python scripts/stats.py

# 2. 检查文件内容
micromamba run -n OpenClaw-Tracer python scripts/inspect.py \
    data/sft_records.parquet \
    --limit 3

# 3. 导出为 TRL 格式
micromamba run -n OpenClaw-Tracer python scripts/export.py \
    data/sft_records.parquet \
    output/trl_train.parquet \
    --format trl

# 4. 使用导出的数据训练
# (在 Python 中)
from datasets import load_dataset
dataset = load_dataset("parquet", data_files="output/trl_train.parquet")
```

---

## 脚本文件列表

```
scripts/
├── serve.py      # 启动代理服务器
├── export.py     # 导出数据
├── inspect.py    # 检查文件内容
└── stats.py      # 显示统计信息
```
