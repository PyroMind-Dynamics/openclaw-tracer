# Copyright (c) 2025 OpenClaw-Tracer
# Tests for core data types

import pytest

from openclaw_tracer.types.core import (
    Attributes,
    Event,
    Link,
    Resource,
    Span,
    SpanContext,
    SpanKind,
    StatusCode,
    convert_timestamp,
)


class TestConvertTimestamp:
    """Tests for convert_timestamp function."""

    def test_none_timestamp(self) -> None:
        """Test that None returns None."""
        assert convert_timestamp(None) is None

    def test_zero_timestamp(self) -> None:
        """Test that 0 returns None."""
        assert convert_timestamp(0) is None

    def test_seconds_timestamp(self) -> None:
        """Test timestamp in seconds."""
        # 2024-01-01 00:00:00 UTC in seconds
        timestamp = 1704067200
        result = convert_timestamp(timestamp)
        assert result == 1704067200.0

    def test_nanoseconds_timestamp(self) -> None:
        """Test timestamp in nanoseconds."""
        # 2024-01-01 00:00:00 UTC in nanoseconds
        timestamp = 1704067200_000_000_000
        result = convert_timestamp(timestamp)
        assert result == 1704067200.0

    def test_milliseconds_timestamp(self) -> None:
        """Test timestamp in nanoseconds (the function treats >1e12 as nanoseconds)."""
        # 2024-01-01 00:00:00 UTC in nanoseconds
        timestamp = 1704067200_000_000_000
        result = convert_timestamp(timestamp)
        assert result == 1704067200.0


class TestSpanContext:
    """Tests for SpanContext class."""

    def test_create_span_context(self) -> None:
        """Test creating a SpanContext."""
        ctx = SpanContext(
            trace_id="12345678901234567890123456789012",
            span_id="1234567890123456",
        )
        assert ctx.trace_id == "12345678901234567890123456789012"
        assert ctx.span_id == "1234567890123456"
        assert ctx.trace_state == {}

    def test_span_context_with_trace_state(self) -> None:
        """Test SpanContext with trace state."""
        ctx = SpanContext(
            trace_id="12345678901234567890123456789012",
            span_id="1234567890123456",
            trace_state={"key": "value"},
        )
        assert ctx.trace_state == {"key": "value"}


class TestResource:
    """Tests for Resource class."""

    def test_create_resource(self) -> None:
        """Test creating a Resource."""
        resource = Resource(
            attributes={"service.name": "test-service"}
        )
        assert resource.attributes == {"service.name": "test-service"}

    def test_resource_default_attributes(self) -> None:
        """Test Resource with default empty attributes."""
        resource = Resource()
        assert resource.attributes == {}


class TestEvent:
    """Tests for Event class."""

    def test_create_event(self) -> None:
        """Test creating an Event."""
        event = Event(
            name="test.event",
            timestamp=1234567890.0,
            attributes={"key": "value"},
        )
        assert event.name == "test.event"
        assert event.timestamp == 1234567890.0
        assert event.attributes == {"key": "value"}

    def test_event_default_attributes(self) -> None:
        """Test Event with default empty attributes."""
        event = Event(
            name="test.event",
            timestamp=1234567890.0,
        )
        assert event.attributes == {}


class TestLink:
    """Tests for Link class."""

    def test_create_link(self) -> None:
        """Test creating a Link."""
        ctx = SpanContext(
            trace_id="12345678901234567890123456789012",
            span_id="1234567890123456",
        )
        link = Link(
            context=ctx,
            attributes={"link.type": "parent"},
        )
        assert link.context == ctx
        assert link.attributes == {"link.type": "parent"}


class TestSpan:
    """Tests for Span class."""

    def test_create_minimal_span(self, span_context: SpanContext) -> None:
        """Test creating a minimal Span with required fields."""
        span = Span(
            name="test.span",
            context=span_context,
            start_time=1234567890.0,
        )
        assert span.name == "test.span"
        assert span.context == span_context
        assert span.start_time == 1234567890.0
        assert span.end_time is None
        assert span.kind == SpanKind.INTERNAL
        assert span.status == "UNSET"
        assert span.attributes == {}
        assert span.events == []
        assert span.links == []
        assert span.parent_id is None

    def test_create_full_span(
        self,
        span_context: SpanContext,
        resource: Resource,
    ) -> None:
        """Test creating a Span with all fields."""
        event = Event(
            name="test.event",
            timestamp=1234567892.0,
        )
        span = Span(
            name="llm.completion",
            context=span_context,
            parent_id="parent123",
            start_time=1234567890.0,
            end_time=1234567895.0,
            kind=SpanKind.CLIENT,
            status="OK",
            attributes={"model": "gpt-4"},
            events=[event],
            rollout_id="ro-test123",
            attempt_id="at-test456",
            sequence_id=1,
            resource=resource,
        )
        assert span.name == "llm.completion"
        assert span.parent_id == "parent123"
        assert span.end_time == 1234567895.0
        assert span.kind == SpanKind.CLIENT
        assert span.status == "OK"
        assert span.attributes == {"model": "gpt-4"}
        assert len(span.events) == 1
        assert span.events[0].name == "test.event"
        assert span.rollout_id == "ro-test123"
        assert span.attempt_id == "at-test456"
        assert span.sequence_id == 1
        assert span.resource == resource

    def test_span_duration_with_end_time(self, span_context: SpanContext) -> None:
        """Test duration calculation when end_time is set."""
        span = Span(
            name="test.span",
            context=span_context,
            start_time=1234567890.0,
            end_time=1234567895.0,
        )
        assert span.duration == 5.0

    def test_span_duration_without_end_time(self, span_context: SpanContext) -> None:
        """Test duration calculation when end_time is None."""
        span = Span(
            name="test.span",
            context=span_context,
            start_time=1234567890.0,
        )
        assert span.duration is None

    def test_span_default_rollout_id(self, span_context: SpanContext) -> None:
        """Test that rollout_id gets a default value."""
        span = Span(
            name="test.span",
            context=span_context,
            start_time=1234567890.0,
        )
        assert span.rollout_id.startswith("ro-")
        assert len(span.rollout_id) == 15  # "ro-" + 12 hex chars

    def test_span_default_attempt_id(self, span_context: SpanContext) -> None:
        """Test that attempt_id gets a default value."""
        span = Span(
            name="test.span",
            context=span_context,
            start_time=1234567890.0,
        )
        assert span.attempt_id.startswith("at-")
        assert len(span.attempt_id) == 11  # "at-" + 8 hex chars

    def test_span_kind_enum(self) -> None:
        """Test SpanKind enum values."""
        assert SpanKind.INTERNAL == "INTERNAL"
        assert SpanKind.SERVER == "SERVER"
        assert SpanKind.CLIENT == "CLIENT"
        assert SpanKind.PRODUCER == "PRODUCER"
        assert SpanKind.CONSUMER == "CONSUMER"

    def test_span_status_values(self, span_context: SpanContext) -> None:
        """Test valid status values."""
        for status in ["UNSET", "OK", "ERROR"]:
            span = Span(
                name="test.span",
                context=span_context,
                start_time=1234567890.0,
                status=status,
            )
            assert span.status == status

    def test_span_with_complex_attributes(
        self,
        span_context: SpanContext,
        resource: Resource,
    ) -> None:
        """Test Span with complex attribute types."""
        span = Span(
            name="llm.completion",
            context=span_context,
            start_time=1234567890.0,
            end_time=1234567895.0,
            attributes={
                "string": "value",
                "int": 42,
                "float": 3.14,
                "bool": True,
                "list.str": ["a", "b"],
                "list.int": [1, 2],
            },
            resource=resource,
        )
        assert span.attributes["string"] == "value"
        assert span.attributes["int"] == 42
        assert span.attributes["float"] == 3.14
        assert span.attributes["bool"] is True
        assert span.attributes["list.str"] == ["a", "b"]
        assert span.attributes["list.int"] == [1, 2]
