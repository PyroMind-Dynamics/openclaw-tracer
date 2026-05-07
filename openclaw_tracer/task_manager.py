"""Task session management for tracking rollouts and attempts."""

import asyncio
import logging
from dataclasses import dataclass, field
from time import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


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
