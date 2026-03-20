# Copyright (c) 2025 OpenClaw-Tracer
# Base data exporter interface

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openclaw_tracer.types.core import RLRecord, SFTRecord


class DataExporter(ABC):
    """Abstract base class for data exporters.

    An exporter converts stored data to a specific format for training.
    """

    @abstractmethod
    async def export_sft(
        self,
        records: List[SFTRecord],
        output_path: str | Path,
        **kwargs: Any,
    ) -> None:
        """Export SFT records to a file.

        Args:
            records: List of SFT records to export.
            output_path: Path to write the output file.
            **kwargs: Additional format-specific options.
        """
        pass

    @abstractmethod
    async def export_rl(
        self,
        records: List[RLRecord],
        output_path: str | Path,
        **kwargs: Any,
    ) -> None:
        """Export RL records to a file.

        Args:
            records: List of RL records to export.
            output_path: Path to write the output file.
            **kwargs: Additional format-specific options.
        """
        pass

    @abstractmethod
    def get_format_name(self) -> str:
        """Get the name of this export format."""
        pass
