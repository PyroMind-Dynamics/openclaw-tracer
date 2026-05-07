# Task ID 和 Reward 追踪功能设计文档

**日期**: 2026-05-07
**作者**: Claude & 用户协作
**状态**: 设计阶段

## 1. 概述

为 OpenClaw-Tracer 添加 task 追踪和奖励信号捕获功能，支持 RL 训练数据收集。

### 1.1 目标

- 支持客户端通过 HTTP 请求头传递 `task-id` 和 `previous_reward`
- `task-id` 作为 `rollout_id`，用于关联同一任务的多次 LLM 调用
- `previous_reward` 作为独立列存储，用于 RL 训练的奖励信号
- 自动管理 task 会话（递增 attempt_id、超时清理）
- 提供 API 探测端点

## 2. 需求

### 2.1 功能需求

1. **Task-ID 追踪**
   - 通过 `X-Task-ID` 请求头传递
   - 作为 Span 的 `rollout_id` 存储
   - 相同 task-id 每次请求时，`attempt_id` 自动递增
   - 可选字段，未传递时回退到自动生成行为

2. **Reward 追踪**
   - 通过 `X-Previous-Reward` 请求头传递
   - 作为 Parquet 表的独立列存储
   - 任意浮点数，无范围限制
   - 可选字段

3. **会话管理**
   - 客户端可通过 API 主动结束 task
   - 超时自动清理（默认 10 分钟，可配置）
   - 简单内存计数，重启后重置

4. **探测端点**
   - `GET /tracer-version` - 返回 tracer 版本信息，无需认证

### 2.2 非功能需求

- 向后兼容：不传递新字段时，系统行为与之前完全一致
- 性能：会话管理不应显著影响请求处理性能
- 可配置：超时时间通过环境变量配置

## 3. 架构设计

### 3.1 架构图

```
HTTP 请求 → AuthMiddleware → TaskMiddleware → LiteLLM → SpanLogger
                ↓                    ↓
          验证 API Key        TaskManager
                                    ↓
                          提取/创建 attempt_id
                          更新最后访问时间
                                    ↓
                          存储到 request.state
                                    ↓
                          SpanLogger 读取并创建 Span
```

### 3.2 组件说明

#### 3.2.1 TaskManager

负责管理活跃 task 的会话状态。

**职责：**
- 维护 task 状态字典（task_id → TaskState）
- 为每个 task 递增 attempt_id
- 定期清理超时 task
- 处理 task 结束请求

**接口：**
```python
class TaskManager:
    async def get_or_create_attempt(self, task_id: Optional[str]) -> str:
        """获取或创建 attempt_id。"""

    async def end_task(self, task_id: str) -> Optional[TaskStats]:
        """结束 task，返回统计信息。"""

    async def start_cleanup_task(self):
        """启动清理任务。"""

    async def stop(self):
        """停止管理器。"""
```

**数据结构：**
```python
@dataclass
class TaskState:
    task_id: str
    attempt_count: int
    created_at: float
    last_access: float
    total_requests: int
```

#### 3.2.2 TaskMiddleware

从请求头提取 task 信息，与 TaskManager 交互。

**处理的请求头：**
- `X-Task-ID`: 任务标识符
- `X-Previous-Reward`: 上一步奖励值

**存储位置：**
- `request.state['task_id']`
- `request.state['attempt_id']`
- `request.state['previous_reward']`

#### 3.2.3 Span 数据模型

添加新字段：
```python
class Span(BaseModel):
    # ... 现有字段 ...
    previous_reward: Optional[float] = None
```

#### 3.2.4 SpanLogger

修改 `async_log_success_event` 和 `async_log_failure_event`：
1. 从请求上下文读取 `task_id`、`attempt_id`、`previous_reward`
2. 使用 `task_id` 作为 `rollout_id`
3. 使用 `attempt_id` 而非自动生成
4. 设置 `previous_reward` 字段

## 4. API 设计

### 4.1 新增请求头

| 请求头 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `X-Task-ID` | string | 否 | 任务标识符 |
| `X-Previous-Reward` | float | 否 | 上一步奖励 |

### 4.2 新增端点

#### GET /tracer-version

探测端点，返回 tracer 信息。

**请求：**
```http
GET /tracer-version
```

**响应：**
```json
{
  "name": "openclaw-tracer",
  "version": "0.1.0",
  "features": ["task-tracking", "reward-tracking"]
}
```

#### POST /end_task

结束指定 task。

**请求：**
```http
POST /end_task
Authorization: Bearer <proxy-api-key>
Content-Type: application/json

{
  "task_id": "task-abc-123"
}
```

**响应（成功）：**
```json
{
  "task_id": "task-abc-123",
  "attempt_count": 5,
  "total_requests": 10,
  "duration_seconds": 300
}
```

**响应（task 不存在）：**
```json
{
  "error": "Task not found",
  "task_id": "task-abc-123"
}
```

## 5. 数据存储

### 5.1 Parquet 表结构

**新增列：**
- `previous_reward` (float, nullable)

**现有列（保持不变）：**
- `name`, `start_time`, `end_time`, `attributes`
- `rollout_id`, `attempt_id`, `sequence_id`

### 5.2 数据流

1. 客户端发送请求，携带 `X-Task-ID` 和 `X-Previous-Reward`
2. TaskMiddleware 提取请求头，调用 TaskManager 获取 attempt_id
3. SpanLogger 创建 Span，设置 rollout_id 和 previous_reward
4. ParquetStore 将 Span 写入 Parquet 文件

## 6. 配置

### 6.1 环境变量

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `TASK_TIMEOUT_MINUTES` | 10 | task 超时时间（分钟） |

### 6.2 现有变量（保持不变）

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `PROXY_API_KEY` | 必填 | 代理认证密钥 |
| `PORT` | 43886 | 代理端口 |
| `BUFFER_SIZE` | 1 | 缓冲大小 |

## 7. 错误处理

| 场景 | 处理方式 |
|------|----------|
| 无效的 `previous_reward` 格式 | 记录警告，忽略该值 |
| TaskManager 清理异常 | 记录错误，继续运行 |
| `/end_task` 请求不存在的 task | 返回 404 |
| 中间件异常 | 记录错误，不影响请求处理 |

## 8. 测试计划

### 8.1 单元测试

**TaskManager 测试：**
- 测试创建新 task
- 测试递增 attempt_id
- 测试超时清理
- 测试结束 task

**TaskMiddleware 测试：**
- 测试请求头提取
- 测试上下文存储
- 测试无请求头时的回退行为

### 8.2 集成测试

- 完整请求流程：验证 Parquet 中的 rollout_id 和 previous_reward
- 超时清理：验证过期 task 被清理
- `/end_task` API：验证任务结束和统计返回
- `/tracer-version` API：验证版本信息返回

### 8.3 向后兼容性测试

- 不传递新请求头时，系统行为与之前一致
- 现有测试用例全部通过

## 9. 实现计划

详细的实现步骤将在下一步创建。

## 10. 风险与限制

### 10.1 风险

- **内存使用**: 大量活跃 task 可能占用较多内存
- **状态丢失**: 代理重启后，task 状态丢失

### 10.2 限制

- 当前实现为内存存储，不支持分布式部署
- 重启后 attempt_id 计数重置

### 10.3 未来改进

- 支持持久化状态存储（Redis、PostgreSQL）
- 支持 task 统计信息查询 API
- 支持 task 元数据（用户 ID、任务类型等）
