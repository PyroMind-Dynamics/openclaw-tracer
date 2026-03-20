# Copyright (c) 2025 OpenClaw-Tracer
# Storage backends for collected data

from openclaw_tracer.storage.base import StorageBackend
from openclaw_tracer.storage.parquet_store import ParquetStore

__all__ = [
    "StorageBackend",
    "ParquetStore",
]
