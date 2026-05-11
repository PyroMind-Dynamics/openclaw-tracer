# Copyright (c) 2025 OpenClaw-Tracer
# Workflow trigger hook after ParquetStore buffer-full flush.

import asyncio
import logging
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from openclaw_tracer.storage.parquet_store import ParquetStore
from openclaw_tracer.types.core import Span
import openclaw_tracer.workflow_trigger as workflow_trigger
from openclaw_tracer.workflow_trigger import (
    DEFAULT_WORKFLOW_TRIGGER_SCRIPT,
    resolve_workflow_script_path,
    schedule_workflow_trigger,
)


@pytest.fixture(autouse=True)
def clear_workflow_warn_cache() -> None:
    workflow_trigger._warned_missing_paths.clear()
    yield


def _span_with_seq(template: Span, sequence_id: int) -> Span:
    return Span(
        name=template.name,
        context=template.context,
        parent_id=template.parent_id,
        start_time=template.start_time + sequence_id,
        end_time=template.end_time + sequence_id,
        kind=template.kind,
        status=template.status,
        attributes=dict(template.attributes),
        rollout_id=template.rollout_id,
        attempt_id=template.attempt_id,
        sequence_id=sequence_id,
        resource=template.resource,
    )


@pytest.mark.asyncio
async def test_buffer_full_invokes_trigger_script(
    tmp_path: Path,
    sample_span: Span,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_WORKFLOW_TRIGGER", "1")
    marker = tmp_path / "triggered"
    script = tmp_path / "start_trigger.sh"
    script.write_text(f'#!/bin/bash\ntouch "{marker}"\n')
    script.chmod(0o755)
    store = ParquetStore(
        output_dir=tmp_path / "data",
        buffer_size=2,
        workflow_trigger_script=script,
        enable_workflow_trigger=True,
        time_window_minutes=9999,
    )
    await store.add_span(sample_span)
    await asyncio.sleep(0.05)
    assert not marker.exists()
    await store.add_span(_span_with_seq(sample_span, 1))
    await asyncio.sleep(0.5)
    assert marker.exists(), "background trigger should touch marker after buffer flush"
    await store.close()


@pytest.mark.asyncio
async def test_trigger_spawn_not_awaited_on_hot_path(
    tmp_path: Path,
    sample_span: Span,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_WORKFLOW_TRIGGER", "1")
    marker = tmp_path / "started"
    script = tmp_path / "slow.sh"
    script.write_text(
        f"""#!/bin/bash
touch "{marker}"
sleep 2
exit 0
"""
    )
    script.chmod(0o755)
    store = ParquetStore(
        output_dir=tmp_path / "data",
        buffer_size=2,
        workflow_trigger_script=script,
        enable_workflow_trigger=True,
        time_window_minutes=9999,
    )
    t0 = time.monotonic()
    await store.add_span(sample_span)
    await store.add_span(_span_with_seq(sample_span, 1))
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if marker.exists():
            break
        await asyncio.sleep(0.05)
    assert marker.exists()
    await store.close()


@pytest.mark.asyncio
async def test_missing_script_warns_once_per_path(
    tmp_path: Path,
    sample_span: Span,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_WORKFLOW_TRIGGER", "1")
    caplog.set_level(logging.WARNING)
    missing = tmp_path / "ghost.sh"
    assert not missing.exists()
    store = ParquetStore(
        output_dir=tmp_path / "data",
        buffer_size=2,
        workflow_trigger_script=missing,
        enable_workflow_trigger=True,
        time_window_minutes=9999,
    )
    await store.add_span(sample_span)
    await store.add_span(_span_with_seq(sample_span, 1))
    await asyncio.sleep(0.1)
    await store.add_span(_span_with_seq(sample_span, 2))
    await store.add_span(_span_with_seq(sample_span, 3))
    await asyncio.sleep(0.1)
    warns = [
        r.message
        for r in caplog.records
        if r.levelno >= logging.WARNING
        and "not found or not a file" in r.message
    ]
    assert len(warns) == 1
    await store.close()


@pytest.mark.asyncio
async def test_time_window_flush_does_not_schedule_workflow(
    tmp_path: Path,
    sample_span: Span,
) -> None:
    state = {"n": 0}

    def next_window(*args: object, **kwargs: object) -> str:
        n = state["n"]
        state["n"] += 1
        return "W0" if n == 0 else "W1"

    with patch("openclaw_tracer.workflow_trigger.schedule_workflow_trigger") as mock_sched:
        with patch(
            "openclaw_tracer.storage.parquet_store._get_time_window",
            side_effect=next_window,
        ):
            store = ParquetStore(
                output_dir=tmp_path / "data",
                buffer_size=50,
                auto_flush=True,
                enable_workflow_trigger=True,
                time_window_minutes=5,
                workflow_trigger_script=tmp_path / "any.sh",
            )
            await store.add_span(sample_span)
            await asyncio.sleep(0.05)
            mock_sched.assert_not_called()
            await store.close()


@pytest.mark.asyncio
async def test_trigger_exit_nonzero_logged(
    tmp_path: Path,
    sample_span: Span,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_WORKFLOW_TRIGGER", "1")
    caplog.set_level(logging.ERROR)
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/bash\necho oops >&2\nexit 8\n")
    script.chmod(0o755)
    store = ParquetStore(
        output_dir=tmp_path / "data",
        buffer_size=2,
        workflow_trigger_script=script,
        enable_workflow_trigger=True,
        time_window_minutes=9999,
    )
    await store.add_span(sample_span)
    await store.add_span(_span_with_seq(sample_span, 1))
    await asyncio.sleep(0.5)
    errs = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("exited with code 8" in m for m in errs)
    assert store.stats["spans_flushed"] >= 2
    await store.close()


@pytest.mark.asyncio
async def test_enable_false_skips_scheduler(
    tmp_path: Path,
    sample_span: Span,
) -> None:
    with patch("openclaw_tracer.workflow_trigger.schedule_workflow_trigger") as mock_sched:
        store = ParquetStore(
            output_dir=tmp_path / "data",
            buffer_size=2,
            enable_workflow_trigger=False,
            time_window_minutes=9999,
        )
        await store.add_span(sample_span)
        await store.add_span(_span_with_seq(sample_span, 1))
        await asyncio.sleep(0.05)
        mock_sched.assert_not_called()
        await store.close()


def test_resolve_workflow_script_explicit_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKFLOW_TRIGGER_SCRIPT", raising=False)
    assert resolve_workflow_script_path(None) == DEFAULT_WORKFLOW_TRIGGER_SCRIPT
    custom = Path("/tmp/x.sh")
    assert resolve_workflow_script_path(custom) == custom
    monkeypatch.setenv("WORKFLOW_TRIGGER_SCRIPT", "/env/path.sh")
    assert resolve_workflow_script_path(None) == Path("/env/path.sh")


def test_schedule_without_event_loop_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        schedule_workflow_trigger(Path("/ignored.sh"))
    warns = [
        r for r in caplog.records if "No running event loop" in r.message
    ]
    assert len(warns) >= 1
