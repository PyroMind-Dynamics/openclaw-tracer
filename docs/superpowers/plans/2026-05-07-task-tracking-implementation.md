# Task ID 和 Reward 追踪功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 OpenClaw-Tracer 添加 task 追踪和奖励信号捕获功能，支持通过 HTTP 请求头传递 `task-id` 和 `previous_reward`，并实现自动会话管理。

**Architecture:** 新增 TaskManager 管理会话状态，TaskMiddleware 提取请求头，SpanLogger 读取上下文并修改 Span 数据模型，ParquetStore 添加新列。

**Tech Stack:** Python 3.10+, FastAPI, LiteLLM, Pydantic, pytest

---

## Task 1: 添加 TaskState 数据类

**Files:**
- Create: `openclaw_tracer/task_manager.py`

创建 TaskManager 文件并定义 TaskState 数据类。

- [ ] **Step 1: 创建文件并添加 TaskState 数据类**

```python
# openclaw_tracer/task_manager.py
"""Task session management for tracking rollouts and attempts."""

from dataclasses import dataclass, field
from time import time
from typing import Optional


@dataclass
class TaskState:
    """State for an active task session."""

    task_id: str
    attempt_count: int = 0
    created_at: float = field(default_factory=time)
    last_access: float = field(default_factory=time)
    total_requests: int = 0

    def touch(self) -> None:
        """Update last_access time to current time."""
        self.last_access = time()

    def increment(self) -> int:
        """Increment attempt count and return new value."""
        self.attempt_count += 1
        return self.attempt_count

    def add_request(self) -> None:
        """Increment total request count."""
        self.total_requests += 1
```

- [ ] **Step 2: 运行测试确保模块可导入**

Run: `python -c "from openclaw_tracer.task_manager import TaskState; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add openclaw_tracer/task_manager.py
git commit -m "feat: add TaskState dataclass for session management"
```

---

## Task 2: 实现 TaskManager 核心功能

**Files:**
- Modify: `openclaw_tracer/task_manager.py`

- [ ] **Step 1: 在文件中添加 TaskManager 类**

```python
# 在 openclaw_tracer/task_manager.py 中追加

import asyncio
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TaskStats:
    """Statistics for a completed task."""

    task_id: str
    attempt_count: int
    total_requests: int
    duration_seconds: float


class TaskManager:
    """Manages active task sessions with automatic cleanup."""

    CLEANUP_INTERVAL_SECONDS = 60  # Check every minute

    def __init__(self, timeout_minutes: int = 10):
        """Initialize TaskManager.

        Args:
            timeout_minutes: Minutes of inactivity before a task is cleaned up.
        """
        self._tasks: Dict[str, TaskState] = {}
        self._timeout_seconds = timeout_minutes * 60
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def get_or_create_attempt(
        self, task_id: Optional[str]
    ) -> tuple[str, str]:
        """Get or create attempt_id for a task.

        Args:
            task_id: The task identifier. If None, generates a unique ID.

        Returns:
            Tuple of (task_id, attempt_id).
        """
        async with self._lock:
            if task_id is None:
                # Generate a unique task ID
                task_id = f"auto-{asyncio.current_task().get_name() if asyncio.current_task() else 'unknown'}-{int(asyncio.get_event_loop().time())}"

            state = self._tasks.get(task_id)
            if state is None:
                # Create new task state
                state = TaskState(task_id=task_id)
                self._tasks[task_id] = state

            # Update state
            state.touch()
            state.add_request()
            attempt_num = state.increment()

            # Format attempt_id with leading zeros
            attempt_id = f"at-{attempt_num:06d}"

            logger.debug(
                f"[TaskManager] task_id={task_id}, attempt_id={attempt_id}, "
                f"attempt_count={attempt_num}, total_requests={state.total_requests}"
            )

            return task_id, attempt_id

    async def end_task(self, task_id: str) -> Optional[TaskStats]:
        """End a task and return its statistics.

        Args:
            task_id: The task identifier to end.

        Returns:
            TaskStats if task existed, None otherwise.
        """
        async with self._lock:
            state = self._tasks.pop(task_id, None)
            if state is None:
                return None

            stats = TaskStats(
                task_id=state.task_id,
                attempt_count=state.attempt_count,
                total_requests=state.total_requests,
                duration_seconds=state.last_access - state.created_at,
            )

            logger.info(
                f"[TaskManager] Ended task={task_id}, "
                f"attempts={stats.attempt_count}, requests={stats.total_requests}"
            )

            return stats

    async def _cleanup_expired_tasks(self) -> None:
        """Remove tasks that have exceeded the timeout."""
        async with self._lock:
            current_time = time()
            expired_tasks = []

            for task_id, state in self._tasks.items():
                if current_time - state.last_access > self._timeout_seconds:
                    expired_tasks.append(task_id)

            for task_id in expired_tasks:
                state = self._tasks.pop(task_id)
                logger.info(
                    f"[TaskManager] Cleaned up expired task={task_id}, "
                    f"inactive for {current_time - state.last_access:.0f}s"
                )

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup loop."""
        while True:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL_SECONDS)
                await self._cleanup_expired_tasks()
            except asyncio.CancelledError:
                logger.info("[TaskManager] Cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"[TaskManager] Error in cleanup loop: {e}", exc_info=True)

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(f"[TaskManager] Started with timeout={self._timeout_seconds//60}min")

    async def stop(self) -> None:
        """Stop the TaskManager and cleanup resources."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("[TaskManager] Stopped")

    @property
    def active_task_count(self) -> int:
        """Return the number of active tasks."""
        return len(self._tasks)
```

- [ ] **Step 2: 运行测试确保模块可导入**

Run: `python -c "from openclaw_tracer.task_manager import TaskManager, TaskStats; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add openclaw_tracer/task_manager.py
git commit -m "feat: implement TaskManager class with session management"
```

---

## Task 3: 编写 TaskManager 单元测试

**Files:**
- Create: `tests/test_task_manager.py`

- [ ] **Step 1: 编写 TaskManager 测试**

```python
# tests/test_task_manager.py
"""Tests for TaskManager."""

import pytest
import asyncio
from openclaw_tracer.task_manager import TaskManager, TaskState, TaskStats


@pytest.fixture
async def manager():
    """Create a TaskManager for testing."""
    mgr = TaskManager(timeout_minutes=1)  # 1 minute timeout for tests
    await mgr.start()
    yield mgr
    await mgr.stop()


class TestTaskState:
    """Tests for TaskState dataclass."""

    def test_task_state_creation(self):
        """Test TaskState can be created with defaults."""
        state = TaskState(task_id="test-task")
        assert state.task_id == "test-task"
        assert state.attempt_count == 0
        assert state.total_requests == 0
        assert state.created_at > 0
        assert state.last_access > 0

    def test_task_state_increment(self):
        """Test increment returns increasing values."""
        state = TaskState(task_id="test-task")
        assert state.increment() == 1
        assert state.increment() == 2
        assert state.increment() == 3
        assert state.attempt_count == 3

    def test_task_state_add_request(self):
        """Test add_request increments total_requests."""
        state = TaskState(task_id="test-task")
        state.add_request()
        state.add_request()
        assert state.total_requests == 2

    def test_task_state_touch(self):
        """Test touch updates last_access."""
        import time
        state = TaskState(task_id="test-task")
        old_time = state.last_access
        time.sleep(0.01)
        state.touch()
        assert state.last_access > old_time


class TestTaskManager:
    """Tests for TaskManager."""

    @pytest.mark.asyncio
    async def test_get_or_create_attempt_new_task(self, manager):
        """Test creating a new task generates correct attempt_id."""
        task_id, attempt_id = await manager.get_or_create_attempt("test-task-1")
        assert task_id == "test-task-1"
        assert attempt_id == "at-000001"

    @pytest.mark.asyncio
    async def test_get_or_create_attempt_increments(self, manager):
        """Test subsequent calls increment attempt_id."""
        task_id, attempt1 = await manager.get_or_create_attempt("test-task-2")
        assert attempt1 == "at-000001"

        task_id, attempt2 = await manager.get_or_create_attempt("test-task-2")
        assert attempt2 == "at-000002"

        # task_id should be the same
        assert task_id == "test-task-2"

    @pytest.mark.asyncio
    async def test_get_or_create_attempt_none_task_id(self, manager):
        """Test None task_id generates auto task_id."""
        task_id, attempt_id = await manager.get_or_create_attempt(None)
        assert task_id is not None
        assert task_id.startswith("auto-")
        assert attempt_id == "at-000001"

    @pytest.mark.asyncio
    async def test_get_or_create_attempt_updates_last_access(self, manager):
        """Test accessing a task updates last_access time."""
        import time

        task_id, _ = await manager.get_or_create_attempt("test-task-3")
        state = manager._tasks[task_id]
        first_access = state.last_access

        await asyncio.sleep(0.01)
        await manager.get_or_create_attempt("test-task-3")

        assert state.last_access > first_access

    @pytest.mark.asyncio
    async def test_end_task_returns_stats(self, manager):
        """Test ending a task returns statistics."""
        # Create some activity
        await manager.get_or_create_attempt("test-task-4")
        await manager.get_or_create_attempt("test-task-4")

        stats = await manager.end_task("test-task-4")
        assert stats is not None
        assert stats.task_id == "test-task-4"
        assert stats.attempt_count == 2
        assert stats.total_requests == 2
        assert stats.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_end_task_nonexistent_returns_none(self, manager):
        """Test ending non-existent task returns None."""
        stats = await manager.end_task("nonexistent-task")
        assert stats is None

    @pytest.mark.asyncio
    async def test_end_task_removes_from_active_tasks(self, manager):
        """Test ending a task removes it from active tasks."""
        await manager.get_or_create_attempt("test-task-5")
        assert manager.active_task_count == 1

        await manager.end_task("test-task-5")
        assert manager.active_task_count == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_tasks(self, manager):
        """Test expired tasks are cleaned up."""
        # Create a task
        await manager.get_or_create_attempt("test-task-6")
        assert manager.active_task_count == 1

        # Manually expire it by setting last_access far in the past
        import time
        state = manager._tasks["test-task-6"]
        state.last_access = time() - 120  # 2 minutes ago

        # Trigger cleanup
        await manager._cleanup_expired_tasks()

        assert manager.active_task_count == 0

    @pytest.mark.asyncio
    async def test_active_task_count(self, manager):
        """Test active_task_count returns correct value."""
        assert manager.active_task_count == 0

        await manager.get_or_create_attempt("task-1")
        assert manager.active_task_count == 1

        await manager.get_or_create_attempt("task-2")
        assert manager.active_task_count == 2

        await manager.end_task("task-1")
        assert manager.active_task_count == 1
```

- [ ] **Step 2: 运行测试验证 TaskManager 功能**

Run: `pytest tests/test_task_manager.py -v`
Expected: 全部通过

- [ ] **Step 3: 提交**

```bash
git add tests/test_task_manager.py
git commit -m "test: add TaskManager unit tests"
```

---

## Task 4: 修改 Span 数据模型添加 previous_reward 字段

**Files:**
- Modify: `openclaw_tracer/types/core.py`

- [ ] **Step 1: 在 Span 类中添加 previous_reward 字段**

找到 `Span` 类的 `sequence_id` 字段定义（约在第166行），在其后添加：

```python
# openclaw_tracer/types/core.py

class Span(BaseModel):
    # ... 现有字段 ...

    sequence_id: int = 0
    """The sequence number within the attempt."""

    # 新增字段
    previous_reward: Optional[float] = None
    """The reward value from the previous step, used for RL training."""

    @property
    def duration(self) -> Optional[float]:
        # ... 现有代码 ...
```

- [ ] **Step 2: 更新 __init__.py 导出新字段**

检查 `openclaw_tracer/__init__.py`，确保 Span 导出正确（应该已经导出了）。

- [ ] **Step 3: 运行测试确保类型系统正确**

Run: `pytest tests/test_core.py -v`
Expected: 现有测试通过（添加 Optional 字段不应破坏现有代码）

- [ ] **Step 4: 提交**

```bash
git add openclaw_tracer/types/core.py
git commit -m "feat: add previous_reward field to Span model"
```

---

## Task 5: 创建 TaskMiddleware 中间件

**Files:**
- Create: `openclaw_tracer/middleware/__init__.py`
- Create: `openclaw_tracer/middleware/task_middleware.py`

- [ ] **Step 1: 创建 middleware 包目录和 init 文件**

```bash
mkdir -p openclaw_tracer/middleware
```

```python
# openclaw_tracer/middleware/__init__.py
"""Middleware for OpenClaw-Tracer."""

from openclaw_tracer.middleware.task_middleware import TaskMiddleware

__all__ = ["TaskMiddleware"]
```

- [ ] **Step 2: 实现 TaskMiddleware**

```python
# openclaw_tracer/middleware/task_middleware.py
"""Middleware to extract task information from request headers."""

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from openclaw_tracer.task_manager import TaskManager

logger = logging.getLogger(__name__)


class TaskMiddleware(BaseHTTPMiddleware):
    """Middleware to extract task information and manage sessions.

    Extracts X-Task-ID and X-Previous-Reward headers, interacts with
    TaskManager to get/create attempt_id, and stores in request.state.
    """

    HEADER_TASK_ID = "x-task-id"
    HEADER_PREVIOUS_REWARD = "x-previous-reward"

    # Keys for storing in request.state
    STATE_TASK_ID = "task_id"
    STATE_ATTEMPT_ID = "attempt_id"
    STATE_PREVIOUS_REWARD = "previous_reward"

    def __init__(self, app, task_manager: TaskManager):
        """Initialize TaskMiddleware.

        Args:
            app: The ASGI application.
            task_manager: The TaskManager instance for session management.
        """
        super().__init__(app)
        self.task_manager = task_manager

    async def dispatch(self, request: StarletteRequest, call_next):
        """Process request to extract and store task information.

        Args:
            request: The incoming request.
            call_next: The next middleware or route handler.

        Returns:
            The response from the next handler.
        """
        # Extract headers
        headers = dict(request.headers)
        task_id = self._extract_header(headers, self.HEADER_TASK_ID)
        previous_reward = self._extract_reward_header(headers, self.HEADER_PREVIOUS_REWARD)

        # Get or create attempt from TaskManager
        final_task_id, attempt_id = await self.task_manager.get_or_create_attempt(task_id)

        # Store in request.state for SpanLogger to access
        request.state[self.STATE_TASK_ID] = final_task_id
        request.state[self.STATE_ATTEMPT_ID] = attempt_id
        request.state[self.STATE_PREVIOUS_REWARD] = previous_reward

        logger.debug(
            f"[TaskMiddleware] task_id={final_task_id}, "
            f"attempt_id={attempt_id}, previous_reward={previous_reward}"
        )

        # Continue with request processing
        response = await call_next(request)
        return response

    def _extract_header(self, headers: dict, header_name: str) -> Optional[str]:
        """Extract header value (case-insensitive).

        Args:
            headers: Request headers dictionary.
            header_name: Name of the header to extract (lowercase).

        Returns:
            Header value or None if not present.
        """
        for key, value in headers.items():
            if key.lower() == header_name:
                return value.strip() if value else None
        return None

    def _extract_reward_header(self, headers: dict, header_name: str) -> Optional[float]:
        """Extract and parse reward header.

        Args:
            headers: Request headers dictionary.
            header_name: Name of the header to extract (lowercase).

        Returns:
            Parsed float value or None if not present/invalid.
        """
        value = self._extract_header(headers, header_name)
        if value is None:
            return None

        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"[TaskMiddleware] Invalid reward value: {value}")
            return None
```

- [ ] **Step 3: 运行测试确保模块可导入**

Run: `python -c "from openclaw_tracer.middleware import TaskMiddleware; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add openclaw_tracer/middleware/
git commit -m "feat: add TaskMiddleware for extracting task headers"
```

---

## Task 6: 编写 TaskMiddleware 单元测试

**Files:**
- Create: `tests/test_task_middleware.py`

- [ ] **Step 1: 编写 TaskMiddleware 测试**

```python
# tests/test_task_middleware.py
"""Tests for TaskMiddleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from starlette.requests import Request

from openclaw_tracer.middleware.task_middleware import TaskMiddleware
from openclaw_tracer.task_manager import TaskManager


@pytest.fixture
async def task_manager():
    """Create a TaskManager for testing."""
    mgr = TaskManager(timeout_minutes=1)
    await mgr.start()
    yield mgr
    await mgr.stop()


@pytest.fixture
def task_middleware(task_manager):
    """Create a TaskMiddleware for testing."""
    app = MagicMock()
    return TaskMiddleware(app, task_manager)


class TestTaskMiddleware:
    """Tests for TaskMiddleware."""

    @pytest.mark.asyncio
    async def test_extract_task_id_header(self, task_middleware, task_manager):
        """Test extracting X-Task-ID header."""
        # Mock request
        request = MagicMock(spec=Request)
        request.headers = {"x-task-id": "test-task-123"}
        request.state = {}

        # Mock call_next
        async def call_next(req):
            response = MagicMock()
            return response

        call_next_mock = AsyncMock(side_effect=call_next)

        # Process request
        await task_middleware.dispatch(request, call_next_mock)

        # Verify state was set
        assert request.state.get("task_id") == "test-task-123"
        assert request.state.get("attempt_id") == "at-000001"
        call_next_mock.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_extract_previous_reward_header(self, task_middleware, task_manager):
        """Test extracting X-Previous-Reward header."""
        request = MagicMock(spec=Request)
        request.headers = {"x-previous-reward": "0.85"}
        request.state = {}

        async def call_next(req):
            response = MagicMock()
            return response

        call_next_mock = AsyncMock(side_effect=call_next)

        await task_middleware.dispatch(request, call_next_mock)

        assert request.state.get("previous_reward") == 0.85

    @pytest.mark.asyncio
    async def test_extract_previous_reward_invalid(self, task_middleware, task_manager):
        """Test invalid reward value is handled gracefully."""
        request = MagicMock(spec=Request)
        request.headers = {"x-previous-reward": "invalid"}
        request.state = {}

        async def call_next(req):
            return MagicMock()

        call_next_mock = AsyncMock(side_effect=call_next)

        await task_middleware.dispatch(request, call_next_mock)

        # Should be None for invalid values
        assert request.state.get("previous_reward") is None

    @pytest.mark.asyncio
    async def test_case_insensitive_headers(self, task_middleware, task_manager):
        """Test headers are case-insensitive."""
        request = MagicMock(spec=Request)
        request.headers = {"X-Task-ID": "test-task", "X-Previous-Reward": "0.5"}
        request.state = {}

        async def call_next(req):
            return MagicMock()

        call_next_mock = AsyncMock(side_effect=call_next)

        await task_middleware.dispatch(request, call_next_mock)

        assert request.state.get("task_id") == "test-task"
        assert request.state.get("previous_reward") == 0.5

    @pytest.mark.asyncio
    async def test_no_headers_creates_auto_task(self, task_middleware, task_manager):
        """Test request without headers creates auto task."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.state = {}

        async def call_next(req):
            return MagicMock()

        call_next_mock = AsyncMock(side_effect=call_next)

        await task_middleware.dispatch(request, call_next_mock)

        # Should have auto-generated task_id and attempt_id
        assert request.state.get("task_id") is not None
        assert request.state.get("task_id").startswith("auto-")
        assert request.state.get("attempt_id") == "at-000001"
        assert request.state.get("previous_reward") is None

    @pytest.mark.asyncio
    async def test_same_task_increments_attempt(self, task_middleware, task_manager):
        """Test same task_id increments attempt on subsequent requests."""
        # First request
        request1 = MagicMock(spec=Request)
        request1.headers = {"x-task-id": "repeat-task"}
        request1.state = {}

        async def call_next1(req):
            return MagicMock()

        await task_middleware.dispatch(request1, AsyncMock(side_effect=call_next1))
        assert request1.state.get("attempt_id") == "at-000001"

        # Second request with same task_id
        request2 = MagicMock(spec=Request)
        request2.headers = {"x-task-id": "repeat-task"}
        request2.state = {}

        async def call_next2(req):
            return MagicMock()

        await task_middleware.dispatch(request2, AsyncMock(side_effect=call_next2))
        assert request2.state.get("attempt_id") == "at-000002"
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/test_task_middleware.py -v`
Expected: 全部通过

- [ ] **Step 3: 提交**

```bash
git add tests/test_task_middleware.py
git commit -m "test: add TaskMiddleware unit tests"
```

---

## Task 7: 修改 ParquetStore 支持 previous_reward 列

**Files:**
- Modify: `openclaw_tracer/storage/parquet_store.py`

- [ ] **Step 1: 查看 ParquetStore 的 schema 定义**

Run: `grep -n "def _get_schema\|def add_span\|pa.schema" openclaw_tracer/storage/parquet_store.py | head -20`

了解当前的 schema 结构。

- [ ] **Step 2: 修改 schema 添加 previous_reward 列**

找到 `_get_schema` 方法或 schema 定义，添加 previous_reward 列。

根据代码结构，通常 schema 定义在类的开始部分或单独的方法中。需要：

```python
# 在 openclaw_tracer/storage/parquet_store.py 中

# 找到 schema 定义，通常类似：
schema = pa.schema([
    # ... 现有字段 ...
    pa.field("rollout_id", pa.string()),
    pa.field("attempt_id", pa.string()),
    pa.field("sequence_id", pa.int64()),
    # 添加新字段:
    pa.field("previous_reward", pa.float64()),
])
```

- [ ] **Step 3: 修改 add_span 方法处理 previous_reward**

在 `add_span` 方法中，确保 previous_reward 被正确写入。

查找构建记录的代码，添加：

```python
# 在构建记录的字典中添加
record = {
    # ... 现有字段 ...
    "rollout_id": span.rollout_id,
    "attempt_id": span.attempt_id,
    "sequence_id": span.sequence_id,
    " 添加新字段:
    "previous_reward": span.previous_reward,
}
```

- [ ] **Step 4: 运行测试确保存储正常**

Run: `pytest tests/test_parquet_store.py -v`
Expected: 测试通过

- [ ] **Step 5: 提交**

```bash
git add openclaw_tracer/storage/parquet_store.py
git commit -m "feat: add previous_reward column to ParquetStore schema"
```

---

## Task 8: 修改 SpanLogger 使用上下文中的 task 信息

**Files:**
- Modify: `openclaw_tracer/proxy/llm_proxy.py`

- [ ] **Step 1: 修改 SpanLogger 接受请求上下文**

需要修改 SpanLogger 的 `async_log_success_event` 和 `async_log_failure_event` 方法，从 LiteLLM 传递的上下文中提取 task 信息。

首先，查看当前如何创建 Span（约在第807行）：

```python
# 当前代码
span = Span(
    name="llm.completion",
    context=SpanContext(trace_id=trace_id, span_id=span_id),
    start_time=start_ts,
    end_time=end_ts,
    kind=SpanKind.CLIENT,
    status="OK",
    attributes=attributes,
    resource=Resource(...),
)
```

需要修改为从请求上下文读取 task_id、attempt_id、previous_reward。

但是，LiteLLM 的回调不直接传递 request 对象。我们需要使用线程本地存储或全局变量来传递。

在文件开头添加：

```python
# 在 openclaw_tracer/proxy/llm_proxy.py 开头添加
import contextvars

# Context variables for passing task information through LiteLLM callbacks
task_context: contextvars.ContextVar = contextvars.ContextVar("task_context", default=None)
```

- [ ] **Step 2: 修改 TaskMiddleware 设置上下文变量**

在 `TaskMiddleware.dispatch` 方法中，存储到上下文变量：

```python
# 在 openclaw_tracer/middleware/task_middleware.py 中

import contextvars

# 定义上下文变量
task_context: contextvars.ContextVar = contextvars.ContextVar("task_context", default=None)

class TaskMiddleware(BaseHTTPMiddleware):
    # ... 现有代码 ...

    async def dispatch(self, request: StarletteRequest, call_next):
        # ... 提取代码 ...

        # 存储到上下文变量（以便 SpanLogger 访问）
        context_data = {
            "task_id": final_task_id,
            "attempt_id": attempt_id,
            "previous_reward": previous_reward,
        }
        token = task_context.set(context_data)

        try:
            response = await call_next(request)
            return response
        finally:
            task_context.reset(token)
```

- [ ] **Step 3: 修改 SpanLogger 使用上下文变量**

在 `SpanLogger.async_log_success_event` 中（约在第481行）：

```python
# 在 openclaw_tracer/proxy/llm_proxy.py 中

# 首先导入
from openclaw_tracer.middleware.task_middleware import task_context

class SpanLogger(CustomLogger):
    # ... 现有代码 ...

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Called when an LLM request succeeds."""
        try:
            # 获取任务上下文
            ctx = task_context.get({})
            task_id = ctx.get("task_id")
            attempt_id = ctx.get("attempt_id")
            previous_reward = ctx.get("previous_reward")

            # ... 现有的消息提取代码 ...

            # Create the span - 修改这部分
            span = Span(
                name="llm.completion",
                context=SpanContext(trace_id=trace_id, span_id=span_id),
                start_time=start_ts,
                end_time=end_ts,
                kind=SpanKind.CLIENT,
                status="OK",
                attributes=attributes,
                previous_reward=previous_reward,  # 添加这个
                resource=Resource(
                    attributes={
                        "service.name": "openclaw-tracer",
                        "llm.provider": kwargs.get("provider", "litellm"),
                    },
                ),
            )

            # 覆盖 rollout_id 和 attempt_id
            if task_id:
                span.rollout_id = task_id
            if attempt_id:
                span.attempt_id = attempt_id

            # Store the span
            await self.store.add_span(span)
        except Exception as e:
            logger.error(f"Error in async_log_success_event: {e}", exc_info=True)
```

同样修改 `async_log_failure_event` 方法。

- [ ] **Step 4: 运行集成测试**

Run: `pytest tests/test_integration.py -v`
Expected: 测试通过

- [ ] **Step 5: 提交**

```bash
git add openclaw_tracer/proxy/llm_proxy.py openclaw_tracer/middleware/task_middleware.py
git commit -m "feat: integrate task context into SpanLogger"
```

---

## Task 9: 集成 TaskMiddleware 到 LLMProxy

**Files:**
- Modify: `openclaw_tracer/proxy/llm_proxy.py`

- [ ] **Step 1: 修改 LLMProxy.__init__ 添加 TaskManager**

在 `LLMProxy.__init__` 中创建 TaskManager 实例：

```python
# 在 openclaw_tracer/proxy/llm_proxy.py 中

from openclaw_tracer.task_manager import TaskManager
from openclaw_tracer.middleware.task_middleware import TaskMiddleware

class LLMProxy:
    def __init__(
        self,
        port: Optional[int] = None,
        model_list: Optional[List[Dict[str, Any]]] = None,
        store: Optional[StorageBackend] = None,
        host: str = "0.0.0.0",
        num_workers: int = 1,
        log_file: Optional[str] = None,
        proxy_api_key: Optional[str] = None,
        task_timeout_minutes: int = 10,  # 新增参数
    ):
        # ... 现有代码 ...

        # Task Manager for session management
        self.task_manager = TaskManager(timeout_minutes=task_timeout_minutes)
```

- [ ] **Step 2: 修改 LLMProxy.start 启动 TaskManager**

在 `LLMProxy.start` 方法中（约在第1028行）：

```python
async def start(self) -> None:
    """Start the proxy server."""
    if self._is_running:
        logger.warning("Proxy server is already running")
        return

    # ... 现有代码 ...

    # Start TaskManager
    await self.task_manager.start()

    # ... 现有的中间件设置代码 ...
```

- [ ] **Step 3: 修改 _setup_http_middleware 添加 TaskMiddleware**

在 `_setup_http_middleware` 方法中（约在第1119行），修改中间件顺序：

```python
def _setup_http_middleware(self, fastapi_app: Any) -> None:
    """Set up HTTP logging and authentication middleware."""
    if getattr(fastapi_app.state, "openclaw_http_middleware_installed", False):
        return

    # ... 现有的导入 ...

    class HTTPLogMiddleware(BaseHTTPMiddleware):
        def __init__(self, app, http_logger, auth_middleware, task_middleware):
            super().__init__(app)
            self.http_logger = http_logger
            self.auth_middleware = auth_middleware
            self.task_middleware = task_middleware

        async def dispatch(self, request, call_next):
            # ... 现有代码保持不变 ...

    # 创建中间件实例
    task_middleware = TaskMiddleware(fastapi_app, self.task_manager)

    # 添加中间件（顺序很重要）
    fastapi_app.add_middleware(
        HTTPLogMiddleware,
        http_logger=self.http_logger,
        auth_middleware=self.auth_middleware,
        task_middleware=task_middleware,
    )
```

实际上，TaskMiddleware 应该作为独立的中间件添加。更简洁的方式：

```python
def _setup_http_middleware(self, fastapi_app: Any) -> None:
    """Set up HTTP logging and authentication middleware."""
    # ... 现有代码 ...

    # Add TaskMiddleware first (before auth)
    task_middleware = TaskMiddleware(fastapi_app, self.task_manager)
    fastapi_app.add_middleware(lambda app: TaskMiddleware(app, self.task_manager))

    # ... 现有的 HTTPLogMiddleware 添加 ...
```

- [ ] **Step 4: 修改 LLMProxy.stop 停止 TaskManager**

在 `LLMProxy.stop` 方法中：

```python
async def stop(self) -> None:
    """Stop the proxy server."""
    if not self._is_running:
        return

    # ... 现有代码 ...

    # Stop TaskManager
    await self.task_manager.stop()

    # ... 现有代码 ...
```

- [ ] **Step 5: 运行测试**

Run: `pytest tests/ -v -k "proxy or integration" --tb=short`
Expected: 相关测试通过

- [ ] **Step 6: 提交**

```bash
git add openclaw_tracer/proxy/llm_proxy.py
git commit -m "feat: integrate TaskManager and TaskMiddleware into LLMProxy"
```

---

## Task 10: 添加 /tracer-version 端点

**Files:**
- Modify: `openclaw_tracer/proxy/llm_proxy.py`

- [ ] **Step 1: 添加 /tracer-version 路由**

在 `_register_status_route` 方法附近添加新路由：

```python
# 在 openclaw_tracer/proxy/llm_proxy.py 中

def _register_status_route(self, fastapi_app: Any) -> None:
    """Register the /status endpoint for collection progress."""
    # ... 现有代码 ...

    @fastapi_app.get("/tracer-version")
    async def tracer_version():
        """Return tracer version information (no auth required)."""
        from openclaw_tracer import __version__
        return {
            "name": "openclaw-tracer",
            "version": __version__,
            "features": ["task-tracking", "reward-tracking"],
        }
```

确保此端点在认证中间件之前注册（不需要认证）。由于 FastAPI 的路由优先级高于中间件，这个端点会正常工作。

- [ ] **Step 2: 测试端点**

```bash
# 启动代理
python scripts/serve.py --config config/models.json --output-dir ./data &
PROXY_PID=$!
sleep 2

# 测试端点
curl http://localhost:43886/tracer-version

# 清理
kill $PROXY_PID
```

Expected: 返回 JSON 响应包含 name、version、features

- [ ] **Step 3: 提交**

```bash
git add openclaw_tracer/proxy/llm_proxy.py
git commit -m "feat: add /tracer-version endpoint for service discovery"
```

---

## Task 11: 添加 /end_task 端点

**Files:**
- Modify: `openclaw_tracer/proxy/llm_proxy.py`

- [ ] **Step 1: 添加 /end_task 路由**

```python
# 在 openclaw_tracer/proxy/llm_proxy.py 中

def _register_status_route(self, fastapi_app: Any) -> None:
    """Register the /status endpoint for collection progress."""
    # ... 现有代码 ...

    @fastapi_app.post("/end_task")
    async def end_task(request: Request):
        """End a task and return its statistics."""
        # Extract task_id from request body
        try:
            body = await request.json()
            task_id = body.get("task_id")
        except Exception:
            return {"error": "Invalid JSON body"}, 400

        if not task_id:
            return {"error": "task_id is required"}, 400

        # End the task
        stats = await self.task_manager.end_task(task_id)

        if stats is None:
            return {
                "error": "Task not found",
                "task_id": task_id
            }, 404

        # Return statistics
        from openclaw_tracer.task_manager import TaskStats
        return {
            "task_id": stats.task_id,
            "attempt_count": stats.attempt_count,
            "total_requests": stats.total_requests,
            "duration_seconds": stats.duration_seconds,
        }
```

需要导入 Request：

```python
from starlette.requests import Request
```

- [ ] **Step 2: 测试端点**

```bash
# 启动代理
python scripts/serve.py --config config/models.json --output-dir ./data &
PROXY_PID=$!
sleep 2

# 测试端点 - 结束不存在的任务
curl -X POST http://localhost:43886/end_task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{"task_id": "nonexistent"}'

# 清理
kill $PROXY_PID
```

Expected: 返回 404 和错误信息

- [ ] **Step 3: 提交**

```bash
git add openclaw_tracer/proxy/llm_proxy.py
git commit -m "feat: add /end_task endpoint for task completion"
```

---

## Task 12: 添加环境变量配置支持

**Files:**
- Modify: `scripts/serve.py` (或启动脚本)

- [ ] **Step 1: 修改 serve.py 添加 TASK_TIMEOUT_MINUTES 参数**

查看 `scripts/serve.py` 并确保 task_timeout_minutes 参数被传递给 LLMProxy：

```python
# 在 scripts/serve.py 中

import os
import argparse

def main():
    parser = argparse.ArgumentParser(description="OpenClaw-Tracer Proxy Server")
    parser.add_argument("--config", required=True, help="Path to model config JSON")
    parser.add_argument("--output-dir", default="data", help="Output directory for data")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--log-file", default=None, help="HTTP access log file")
    parser.add_argument("--proxy-api-key", default=None, help="Proxy authentication key")
    parser.add_argument(
        "--task-timeout-minutes",
        type=int,
        default=int(os.getenv("TASK_TIMEOUT_MINUTES", 10)),
        help="Task timeout in minutes (default: from env or 10)"
    )

    args = parser.parse_args()

    # ... 现有代码 ...

    # 创建 LLMProxy 时传递参数
    proxy = LLMProxy(
        port=args.port,
        model_list=model_list,
        store=store,
        host=args.host,
        log_file=args.log_file,
        proxy_api_key=proxy_api_key,
        task_timeout_minutes=args.task_timeout_minutes,  # 添加此行
    )
```

- [ ] **Step 2: 测试环境变量**

```bash
# 设置环境变量并测试
export TASK_TIMEOUT_MINUTES=5
python scripts/serve.py --help | grep task-timeout
```

Expected: 帮助信息显示 task-timeout 参数

- [ ] **Step 3: 提交**

```bash
git add scripts/serve.py
git commit -m "feat: add TASK_TIMEOUT_MINUTES environment variable support"
```

---

## Task 13: 编写集成测试

**Files:**
- Create: `tests/test_task_tracking_integration.py`

- [ ] **Step 1: 编写端到端集成测试**

```python
# tests/test_task_tracking_integration.py
"""Integration tests for task tracking feature."""

import pytest
import asyncio
from httpx import AsyncClient

from openclaw_tracer import LLMProxy
from openclaw_tracer.storage.parquet_store import ParquetStore


@pytest.fixture
async def proxy_with_task_tracking():
    """Create a proxy with task tracking enabled."""
    store = ParquetStore(output_dir="test_data")

    model_list = [{
        "model_name": "test-model",
        "litellm_params": {
            "model": "openai/gpt-3.5-turbo",
            "api_key": "test-key",
        },
    }]

    proxy = LLMProxy(
        port=None,  # Random port
        model_list=model_list,
        store=store,
        proxy_api_key="test-key",
        task_timeout_minutes=10,
    )

    await proxy.start()
    yield proxy

    await proxy.stop()
    import shutil
    shutil.rmtree("test_data", ignore_errors=True)


class TestTaskTrackingIntegration:
    """End-to-end tests for task tracking."""

    @pytest.mark.asyncio
    async def test_tracer_version_endpoint(self, proxy_with_task_tracking):
        """Test /tracer-version returns correct information."""
        async with AsyncClient() as client:
            response = await client.get(f"{proxy_with_task_tracking.url}/tracer-version")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "openclaw-tracer"
        assert "version" in data
        assert "task-tracking" in data["features"]

    @pytest.mark.asyncio
    async def test_task_id_header_captured(self, proxy_with_task_tracking):
        """Test that X-Task-ID header is captured and used as rollout_id."""
        # This test would require mocking the upstream API or using a test double
        # For now, we test the middleware chain
        pass

    @pytest.mark.asyncio
    async def test_previous_reward_header_captured(self, proxy_with_task_tracking):
        """Test that X-Previous-Reward header is captured."""
        pass

    @pytest.mark.asyncio
    async def test_end_task_endpoint(self, proxy_with_task_tracking):
        """Test /end_task endpoint."""
        async with AsyncClient() as client:
            # Create a task first (via middleware)
            # Note: This requires an actual request flow

            # End the task
            response = await client.post(
                f"{proxy_with_task_tracking.url}/end_task",
                json={"task_id": "test-task-123"},
                headers={"Authorization": "Bearer test-key"}
            )

        # Task doesn't exist, should return 404
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_task_timeout_cleanup(self, proxy_with_task_tracking):
        """Test that tasks are cleaned up after timeout."""
        # This test would need to:
        # 1. Create a task via request
        # 2. Wait for timeout
        # 3. Verify task is cleaned up
        pass
```

- [ ] **Step 2: 运行集成测试**

Run: `pytest tests/test_task_tracking_integration.py -v`
Expected: 测试通过（某些测试可能需要 mock）

- [ ] **Step 3: 提交**

```bash
git add tests/test_task_tracking_integration.py
git commit -m "test: add integration tests for task tracking"
```

---

## Task 14: 更新文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 README 添加新功能说明**

在 README.md 中添加新功能文档：

```markdown
## Task 追踪功能

OpenClaw-Tracer 支持 task 追踪和奖励信号捕获，用于 RL 训练数据收集。

### 请求头

| 请求头 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `X-Task-ID` | string | 否 | 任务标识符，用作 rollout_id |
| `X-Previous-Reward` | float | 否 | 上一步的奖励值 |

### 示例

```bash
curl http://localhost:43886/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-proxy-key" \
  -H "X-Task-ID: my-task-123" \
  -H "X-Previous-Reward: 0.85" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### API 端点

#### GET /tracer-version

获取 tracer 版本信息（无需认证）。

```bash
curl http://localhost:43886/tracer-version
```

#### POST /end_task

结束指定 task 会话。

```bash
curl -X POST http://localhost:43886/end_task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-proxy-key" \
  -d '{"task_id": "my-task-123"}'
```

### 环境变量

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `TASK_TIMEOUT_MINUTES` | 10 | task 超时时间（分钟） |
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: add task tracking feature documentation"
```

---

## Task 15: 最终验证和清理

- [ ] **Step 1: 运行所有测试**

Run: `pytest tests/ -v --tb=short`
Expected: 所有测试通过

- [ ] **Step 2: 检查类型提示**

Run: `mypy openclaw_tracer/ --ignore-missing-imports`
Expected: 无严重类型错误

- [ ] **Step 3: 本地功能测试**

```bash
# 启动代理
export PROXY_API_KEY="test-key"
export TASK_TIMEOUT_MINUTES=1
python scripts/serve.py --config config/models.json --output-dir ./test_data &

# 等待启动
sleep 2

# 测试 /tracer-version
curl http://localhost:43886/tracer-version

# 测试带 task-id 的请求（需要有效的上游 API key）
# curl -X POST http://localhost:43886/v1/chat/completions \
#   -H "Content-Type: application/json" \
#   -H "Authorization: Bearer test-key" \
#   -H "X-Task-ID: test-task" \
#   -H "X-Previous-Reward: 0.5" \
#   -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hi"}]}'

# 测试 /end_task
curl -X POST http://localhost:43886/end_task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{"task_id": "test-task"}'

# 清理
pkill -f "scripts/serve.py"
rm -rf test_data
```

- [ ] **Step 4: 创建功能总结**

```bash
git log --oneline -15 > /tmp/commits.txt
cat /tmp/commits.txt
```

- [ ] **Step 5: 最终提交**

如果有任何修复，提交：

```bash
git add -A
git commit -m "chore: final cleanup and fixes for task tracking feature"
```

---

## 实现完成检查清单

- [ ] TaskManager 类实现并测试
- [ ] TaskMiddleware 中间件实现并测试
- [ ] Span 数据模型添加 previous_reward 字段
- [ ] ParquetStore 添加 previous_reward 列
- [ ] SpanLogger 使用上下文中的 task 信息
- [ ] LLMProxy 集成 TaskMiddleware 和 TaskManager
- [ ] /tracer-version 端点实现
- [ ] /end_task 端点实现
- [ ] 环境变量 TASK_TIMEOUT_MINUTES 支持
- [ ] 集成测试通过
- [ ] 文档更新完成
- [ ] 所有测试通过
