# Copyright (c) 2025 OpenClaw-Tracer
# Pytest configuration and fixtures

import asyncio
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest

from openclaw_tracer.storage.parquet_store import ParquetStore
from openclaw_tracer.types.core import (
    Attributes,
    Resource,
    Span,
    SpanContext,
    SpanKind,
)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def span_context() -> SpanContext:
    """Create a test SpanContext."""
    return SpanContext(
        trace_id="12345678901234567890123456789012",
        span_id="1234567890123456",
    )


@pytest.fixture
def resource() -> Resource:
    """Create a test Resource."""
    return Resource(
        attributes={
            "service.name": "openclaw-tracer",
            "service.version": "0.1.2",
        }
    )


@pytest.fixture
def sample_span(span_context: SpanContext, resource: Resource) -> Span:
    """Create a sample Span for testing."""
    return Span(
        name="llm.completion",
        context=span_context,
        start_time=1234567890.0,
        end_time=1234567895.0,
        kind=SpanKind.CLIENT,
        status="OK",
        attributes={
            "llm.model": "gpt-4",
            "llm.request.messages": "[{\"role\": \"user\", \"content\": \"Hello\"}]",
            "llm.response.content": "Hi there!",
            "llm.usage.prompt_tokens": 10,
            "llm.usage.completion_tokens": 5,
            "llm.usage.total_tokens": 15,
        },
        rollout_id="ro-test123456789",
        attempt_id="at-test123",
        sequence_id=0,
        resource=resource,
    )


@pytest.fixture
def parquet_store(temp_dir: Path) -> ParquetStore:
    """Create a ParquetStore for testing."""
    return ParquetStore(
        output_dir=temp_dir / "data",
        buffer_size=10,
        auto_flush=True,
        time_window_minutes=5,
    )


@pytest.fixture
async def async_parquet_store(temp_dir: Path) -> AsyncGenerator[ParquetStore, None]:
    """Create an async ParquetStore that is properly closed."""
    store = ParquetStore(
        output_dir=temp_dir / "data",
        buffer_size=10,
        auto_flush=True,
        time_window_minutes=5,
    )
    yield store
    await store.close()


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
