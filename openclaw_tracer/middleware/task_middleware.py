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
