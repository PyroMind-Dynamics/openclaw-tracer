# Copyright (c) 2025 OpenClaw-Tracer
# Abstract storage backend for collected LLM data

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from openclaw_tracer.types.core import Span


class StorageBackend(ABC):
    """Abstract base class for storage backends.

    A storage backend is responsible for persisting collected data (spans)
    to some destination (file system, database, etc.).
    """

    @abstractmethod
    async def add_span(self, span: Span) -> None:
        """Add a single span to storage.

        Args:
            span: The span to store.
        """
        pass

    @abstractmethod
    async def add_spans(self, spans: List[Span]) -> None:
        """Add multiple spans to storage.

        Args:
            spans: The list of spans to store.
        """
        pass

    @abstractmethod
    async def query_spans(
        self,
        rollout_id: Optional[str] = None,
        attempt_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Span]:
        """Query stored spans.

        Args:
            rollout_id: Filter by rollout ID.
            attempt_id: Filter by attempt ID.
            limit: Maximum number of spans to return.

        Returns:
            List of matching spans.
        """
        pass

    @abstractmethod
    async def flush(self) -> None:
        """Flush any buffered data to storage."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the storage backend and release resources."""
        pass

    @property
    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        """Get storage statistics.

        Returns:
            Dictionary with storage statistics.
        """
        pass
