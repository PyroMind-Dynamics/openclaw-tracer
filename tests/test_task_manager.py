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
        assert stats.final_reward is None

    @pytest.mark.asyncio
    async def test_end_task_with_final_reward(self, manager):
        """Test ending a task can attach an episode final reward."""
        await manager.get_or_create_attempt("test-task-reward")
        stats = await manager.end_task("test-task-reward", final_reward=0.75)
        assert stats is not None
        assert stats.final_reward == 0.75

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
        from time import time
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
