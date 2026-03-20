# Copyright (c) 2025 OpenClaw-Tracer
# Core data models for LLM data collection

from __future__ import annotations

import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Sequence, Union
from uuid import uuid4

from pydantic import BaseModel, Field


def convert_timestamp(timestamp: Optional[int]) -> Optional[float]:
    """Normalize OpenTelemetry timestamps to seconds.

    Args:
        timestamp: Timestamp expressed either in seconds or nanoseconds.

    Returns:
        Timestamp in seconds when `timestamp` is provided; otherwise `None`.
    """
    if not timestamp:
        return None
    return timestamp / 1_000_000_000 if timestamp > 1e12 else timestamp


# ========== OpenTelemetry-style Types ==========

AttributeValue = Union[
    str,
    bool,
    int,
    float,
    Sequence[str],
    Sequence[bool],
    Sequence[int],
    Sequence[float],
]
"""Possible values for OpenTelemetry attributes."""

Attributes = Dict[str, AttributeValue]
"""Mapping from attribute names to their values."""


StatusCode = Literal["UNSET", "OK", "ERROR"]
"""The status code of the span."""


class SpanKind(str, Enum):
    """The type of span.

    INTERNAL: Span representing an internal operation within a request.
    SERVER: Span representing the server-side handling of a network request.
    CLIENT: Span representing the client-side sending of a network request.
    PRODUCER: Span representing the sending of a message to a broker.
    CONSUMER: Span representing the receiving of a message from a broker.
    """

    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class SpanContext(BaseModel):
    """Span context containing trace and span identifiers."""

    trace_id: str
    """The trace ID of the span (16-byte hex string)."""

    span_id: str
    """The span ID (8-byte hex string)."""

    trace_state: Dict[str, str] = Field(default_factory=dict)
    """Trace state key-value pairs."""


class Link(BaseModel):
    """A link from one span to another span."""

    context: SpanContext
    """The linked span context."""

    attributes: Attributes = Field(default_factory=dict)
    """Attributes associated with the link."""


class Event(BaseModel):
    """A timed event within a span."""

    name: str
    """The name of the event."""

    timestamp: float
    """The timestamp of the event in seconds."""

    attributes: Attributes = Field(default_factory=dict)
    """Attributes associated with the event."""


class Resource(BaseModel):
    """Resource representing the entity producing the span.

    For OpenClaw-Tracer, this includes rollout_id, attempt_id, etc.
    """

    attributes: Attributes = Field(default_factory=dict)
    """Resource attributes identifying the entity."""


class Span(BaseModel):
    """A span representing a single LLM interaction or operation.

    This follows OpenTelemetry span semantics with agent-specific metadata.
    """

    # Identity
    name: str
    """The name of the span (e.g., 'llm.completion', 'tool.call')."""

    context: SpanContext
    """The span context with trace and span IDs."""

    # Parent relationship
    parent_id: Optional[str] = None
    """The span ID of the parent span, if any."""

    # Timing
    start_time: float
    """Start time of the span in seconds since epoch."""

    end_time: Optional[float] = None
    """End time of the span in seconds since epoch."""

    # Classification
    kind: SpanKind = SpanKind.INTERNAL
    """The type/kind of span."""

    # Status
    status: StatusCode = "UNSET"
    """The status of the span."""

    # Data
    attributes: Attributes = Field(default_factory=dict)
    """Attributes containing the actual data (prompts, responses, etc.)."""

    events: List[Event] = Field(default_factory=list)
    """Timed events within the span."""

    links: List[Link] = Field(default_factory=list)
    """Links to other spans."""

    resource: Resource = Field(default_factory=Resource)
    """The resource that produced this span."""

    # Agent-specific metadata
    rollout_id: str = Field(default_factory=lambda: f"ro-{uuid4().hex[:12]}")
    """The rollout ID this span belongs to."""

    attempt_id: str = Field(default_factory=lambda: f"at-{uuid4().hex[:8]}")
    """The attempt ID this span belongs to."""

    sequence_id: int = 0
    """The sequence number within the attempt."""

    @property
    def duration(self) -> Optional[float]:
        """Get the span duration in seconds."""
        if self.end_time is None:
            return None
        return self.end_time - self.start_time
