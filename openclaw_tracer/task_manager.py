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
