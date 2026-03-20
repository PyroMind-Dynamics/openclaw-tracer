# Copyright (c) 2025 OpenClaw-Tracer
# Parquet file storage backend with time-based sharding

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

from openclaw_tracer.storage.base import StorageBackend
from openclaw_tracer.types.core import Span

logger = logging.getLogger(__name__)


def _get_time_window(interval_minutes: int = 30) -> str:
    """Get the current time window identifier.

    Args:
        interval_minutes: Minutes per time window (default: 30)

    Returns:
        Time window string like "20260303_143000" representing the window start
    """
    now = datetime.now(timezone.utc)
    window_seconds = (now.hour * 3600 + now.minute * 60 + now.second) // (interval_minutes * 60) * (interval_minutes * 60)
    window_hour = window_seconds // 3600
    window_minute = (window_seconds % 3600) // 60
    return now.strftime(f"%Y%m%d_{window_hour:02d}{window_minute:02d}00")


class ParquetStore(StorageBackend):
    """Parquet file storage backend with time-based sharding.

    This backend stores span data in Parquet format:
    - Raw spans: spans/spans_YYYYMMDD_HHMMSS.parquet

    Flushing behavior:
    1. Auto-flush when buffer reaches buffer_size (default: 1 for immediate write)
    2. Creates a new file every time_window_minutes (default: 5)
    3. Manual flush via flush() method

    Args:
        output_dir: Directory to write Parquet files.
        buffer_size: Number of records to buffer before auto-flushing (default: 1).
        auto_flush: Whether to automatically flush when buffer is full.
        time_window_minutes: Minutes per time shard (default: 5).
    """

    # File prefix for span files
    SPAN_PREFIX = "spans_"

    def __init__(
        self,
        output_dir: str | Path = "data",
        buffer_size: int = 1,
        auto_flush: bool = True,
        time_window_minutes: int = 5,
        trajectory_buffer_size: int = 0,
        flush_interval_seconds: int = 1800,
    ):
        """Initialize the Parquet store.

        Args:
            output_dir: Directory to write Parquet files.
            buffer_size: Number of records to buffer before auto-flushing (default: 1).
            auto_flush: Whether to automatically flush when buffer is full.
            time_window_minutes: Minutes per time shard (default: 5).
            trajectory_buffer_size: Total records to retain (rolling window). 0 = disabled.
            flush_interval_seconds: Periodic flush interval in seconds (default: 1800 = 30min).
                                    0 = disabled.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.buffer_size = buffer_size
        self.auto_flush = auto_flush
        self.time_window_minutes = time_window_minutes
        self.trajectory_buffer_size = trajectory_buffer_size

        # Batch mode: enabled when trajectory_buffer_size > 0
        self._batch_mode = trajectory_buffer_size > 0
        self._current_batch_index: int = 0
        self._current_batch_collected: int = 0

        # Create spans directory (with batch subdirectory if needed)
        spans_dir = self.output_dir / "spans"
        spans_dir.mkdir(exist_ok=True)

        if self._batch_mode:
            self._restore_batch_state(spans_dir)
        else:
            # Non-batch mode: spans written directly to data/spans/
            pass

        # Current time window for spans
        self._current_span_window = _get_time_window(time_window_minutes)

        # Span buffer
        self._span_buffer: List[Dict[str, Any]] = []

        # Periodic flush
        self.flush_interval_seconds = flush_interval_seconds
        self._flush_task: Optional[asyncio.Task] = None

        # Statistics
        self._stats = {
            "spans_added": 0,
            "spans_flushed": 0,
            "span_files_created": 0,
        }

    def _restore_batch_state(self, spans_dir: Path) -> None:
        """Restore batch index and collected count from existing directories on restart."""
        existing_batches = sorted(
            (int(d.name) for d in spans_dir.iterdir() if d.is_dir() and d.name.isdigit()),
        )

        if existing_batches:
            self._current_batch_index = existing_batches[-1]
            # Count rows in the current batch directory
            batch_dir = spans_dir / str(self._current_batch_index)
            row_count = 0
            for pf in batch_dir.glob("*.parquet"):
                try:
                    table = pq.read_table(pf)
                    row_count += table.num_rows
                except Exception:
                    continue
            self._current_batch_collected = row_count

            # If current batch is already full, keep it as-is.
            # The advance will happen when the next add_span is called.

            logger.info(
                f"Restored batch state: batch_index={self._current_batch_index}, "
                f"batch_collected={self._current_batch_collected}"
            )
        else:
            self._current_batch_index = 0
            self._current_batch_collected = 0

        # Ensure current batch directory exists
        (spans_dir / str(self._current_batch_index)).mkdir(exist_ok=True)

    async def add_span(self, span: Span) -> None:
        """Add a single span to storage."""
        # In batch mode, advance to next batch BEFORE adding new data
        # This ensures deletion happens when a new record arrives, not when
        # the previous batch fills — keeping max_batches complete + 1 in-progress
        if self._batch_mode and self._current_batch_collected >= self.buffer_size:
            self._advance_batch()

        span_dict = self._span_to_dict(span)
        self._span_buffer.append(span_dict)
        self._stats["spans_added"] += 1

        if self._batch_mode:
            self._current_batch_collected += 1

        # Check if we need to flush (buffer full or time window changed)
        current_window = _get_time_window(self.time_window_minutes)
        should_flush = (
            self.auto_flush and len(self._span_buffer) >= self.buffer_size
        ) or current_window != self._current_span_window

        if should_flush:
            await self._flush_spans(new_window=current_window != self._current_span_window)

    async def add_spans(self, spans: List[Span]) -> None:
        """Add multiple spans to storage."""
        for span in spans:
            span_dict = self._span_to_dict(span)
            self._span_buffer.append(span_dict)
            self._stats["spans_added"] += 1

        # Check if we need to flush
        current_window = _get_time_window(self.time_window_minutes)
        should_flush = (
            self.auto_flush and len(self._span_buffer) >= self.buffer_size
        ) or current_window != self._current_span_window

        if should_flush:
            await self._flush_spans(new_window=current_window != self._current_span_window)

    async def query_spans(
        self,
        rollout_id: Optional[str] = None,
        attempt_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Span]:
        """Query stored spans from all Parquet shard files.

        Args:
            rollout_id: Filter by rollout ID.
            attempt_id: Filter by attempt ID.
            limit: Maximum number of spans to return.

        Returns:
            List of Span objects matching the filters.
        """
        spans_dir = self.output_dir / "spans"
        if not spans_dir.exists():
            return []

        # Read all span shard files
        all_spans = []
        for shard_file in sorted(spans_dir.glob("*.parquet")):
            try:
                df = pq.read_table(shard_file).to_pandas()
                all_spans.append(df)
            except Exception as e:
                # Skip corrupted files
                continue

        if not all_spans:
            return []

        # Combine all shards
        combined_df = pd.concat(all_spans, ignore_index=True)

        # Apply filters
        if rollout_id is not None:
            combined_df = combined_df[combined_df["rollout_id"] == rollout_id]
        if attempt_id is not None:
            combined_df = combined_df[combined_df["attempt_id"] == attempt_id]

        # Limit results
        combined_df = combined_df.head(limit)

        # Convert back to Span objects
        spans = []
        for _, row in combined_df.iterrows():
            spans.append(self._dict_to_span(row.to_dict()))

        return spans

    def start_periodic_flush(self) -> None:
        """Start the background periodic flush task.

        Must be called from within a running event loop (e.g. after server starts).
        Safe to call multiple times — only one task will be created.
        """
        if self.flush_interval_seconds <= 0:
            return
        if self._flush_task is not None and not self._flush_task.done():
            return
        self._flush_task = asyncio.create_task(self._periodic_flush_loop())
        logger.info(f"Periodic flush started (interval={self.flush_interval_seconds}s)")

    async def _periodic_flush_loop(self) -> None:
        """Background loop that flushes the buffer at fixed intervals."""
        while True:
            await asyncio.sleep(self.flush_interval_seconds)
            if self._span_buffer:
                logger.info(f"Periodic flush: {len(self._span_buffer)} spans in buffer")
                await self.flush()

    async def flush(self) -> None:
        """Flush all buffered data to storage."""
        current_window = _get_time_window(self.time_window_minutes)
        await self._flush_spans(new_window=current_window != self._current_span_window)

    async def close(self) -> None:
        """Close the storage backend."""
        # Stop periodic flush task
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self.flush()

    async def merge_spans(self, output_path: Optional[str | Path] = None) -> Path:
        """Merge all span shards into a single Parquet file.

        Args:
            output_path: Output file path. If None, uses spans_merged.parquet in output_dir.

        Returns:
            Path to the merged file.
        """
        if output_path is None:
            output_path = self.output_dir / "spans_merged.parquet"
        else:
            output_path = Path(output_path)

        spans_dir = self.output_dir / "spans"
        if not spans_dir.exists():
            return output_path

        # Read and combine all shards
        all_dfs = []
        for shard_file in sorted(spans_dir.glob("*.parquet")):
            try:
                df = pq.read_table(shard_file).to_pandas()
                all_dfs.append(df)
            except Exception:
                continue

        if all_dfs:
            combined_df = pd.concat(all_dfs, ignore_index=True)
            combined_df.to_parquet(output_path, index=False)

        return output_path

    @property
    def stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        spans_dir = self.output_dir / "spans"
        span_files = list(spans_dir.glob("*.parquet")) if spans_dir.exists() else []

        return {
            **self._stats,
            "output_dir": str(self.output_dir),
            "span_buffer_size": len(self._span_buffer),
            "span_shard_files": len(span_files),
            "current_time_window": _get_time_window(self.time_window_minutes),
            "time_window_minutes": self.time_window_minutes,
        }

    # ========== Private Helper Methods ==========

    async def _flush_spans(self, new_window: bool = False) -> None:
        """Flush buffered spans to Parquet file.

        Args:
            new_window: Whether the time window has changed (creates new file).
        """
        if not self._span_buffer:
            return

        # Update time window if changed
        current_window = _get_time_window(self.time_window_minutes)
        if new_window or current_window != self._current_span_window:
            self._current_span_window = current_window

        # Determine target directory
        if self._batch_mode:
            target_dir = self.output_dir / "spans" / str(self._current_batch_index)
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            target_dir = self.output_dir / "spans"

        # Write to time-sharded file
        spans_path = target_dir / f"{self.SPAN_PREFIX}{self._current_span_window}.parquet"
        df = pd.DataFrame(self._span_buffer)

        # If file exists, append to it (same time window)
        if spans_path.exists():
            existing_df = pq.read_table(spans_path).to_pandas()
            df = pd.concat([existing_df, df], ignore_index=True)

        df.to_parquet(spans_path, index=False)
        self._stats["spans_flushed"] += len(self._span_buffer)
        if new_window or not spans_path.exists():
            self._stats["span_files_created"] += 1
        self._span_buffer.clear()

    def _advance_batch(self) -> None:
        """Advance to the next batch directory and delete old batches if needed.

        Retains max_batches complete batches + the current in-progress batch.
        For BUFFER_SIZE=2, TRAJECTORY_BUFFER_SIZE=4 (max_batches=2):
          batch 2 advance → batch 3: delete 3-2-1=0 → delete batch 0
          batch 3 advance → batch 4: delete 4-2-1=1 → delete batch 1
        """
        # Flush any remaining data before advancing
        # (handled by caller or auto-flush, but ensure buffer is clean)

        self._current_batch_index += 1
        self._current_batch_collected = 0

        # Create new batch directory
        new_batch_dir = self.output_dir / "spans" / str(self._current_batch_index)
        new_batch_dir.mkdir(parents=True, exist_ok=True)

        # Rolling deletion: keep max_batches complete batches + current in-progress
        max_batches = self.trajectory_buffer_size // self.buffer_size
        old_batch = self._current_batch_index - max_batches - 1
        if old_batch >= 0:
            old_batch_dir = self.output_dir / "spans" / str(old_batch)
            if old_batch_dir.exists():
                shutil.rmtree(old_batch_dir)
                logger.info(f"Deleted old batch directory: {old_batch_dir}")

        # Reset time window for the new batch
        self._current_span_window = _get_time_window(self.time_window_minutes)

        logger.info(f"Advanced to batch {self._current_batch_index}")

    def get_collection_status(self) -> Dict[str, Any]:
        """Return collection progress status."""
        total = self._current_batch_index * self.buffer_size + self._current_batch_collected
        if self._batch_mode:
            total_data_size = min(total, self.trajectory_buffer_size)
        else:
            total_data_size = total
        return {
            "collected_data_size": self._current_batch_collected,
            "total_data_size": total_data_size,
        }

    def _span_to_dict(self, span: Span) -> Dict[str, Any]:
        """Convert a Span object to a dictionary for Parquet storage."""
        return {
            "name": span.name,
            "trace_id": span.context.trace_id,
            "span_id": span.context.span_id,
            "parent_id": span.parent_id,
            "start_time": span.start_time,
            "end_time": span.end_time,
            "kind": span.kind.value,
            "status": span.status,
            "attributes": json.dumps(span.attributes),
            "rollout_id": span.rollout_id,
            "attempt_id": span.attempt_id,
            "sequence_id": span.sequence_id,
            "resource_attributes": json.dumps(span.resource.attributes),
        }

    def _dict_to_span(self, d: Dict[str, Any]) -> Span:
        """Convert a dictionary back to a Span object."""
        from openclaw_tracer.types.core import (
            Attributes,
            Resource,
            SpanContext,
            SpanKind,
        )

        return Span(
            name=d["name"],
            context=SpanContext(
                trace_id=d["trace_id"],
                span_id=d["span_id"],
            ),
            parent_id=d.get("parent_id"),
            start_time=d["start_time"],
            end_time=d.get("end_time"),
            kind=SpanKind(d.get("kind", "INTERNAL")),
            status=d.get("status", "UNSET"),
            attributes=json.loads(d.get("attributes", "{}")),
            rollout_id=d["rollout_id"],
            attempt_id=d["attempt_id"],
            sequence_id=d.get("sequence_id", 0),
            resource=Resource(attributes=json.loads(d.get("resource_attributes", "{}"))),
        )
