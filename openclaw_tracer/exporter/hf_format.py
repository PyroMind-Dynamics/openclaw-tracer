# Copyright (c) 2025 OpenClaw-Tracer
# HuggingFace Dataset format exporter

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from datasets import Dataset as HFDataset
from datasets import DatasetDict

from openclaw_tracer.exporter.base import DataExporter
from openclaw_tracer.types.core import RLRecord, SFTRecord


class HFExporter(DataExporter):
    """Export data in HuggingFace Dataset format.

    This exporter creates datasets compatible with HuggingFace Datasets library,
    which can be directly loaded with `load_from_parquet()` or used with
    `datasets.Dataset.from_dict()`.
    """

    def __init__(self, split_train_test: bool = False, test_size: float = 0.1):
        """Initialize the HF exporter.

        Args:
            split_train_test: Whether to split data into train/test sets.
            test_size: Fraction of data to use for test set (if splitting).
        """
        self.split_train_test = split_train_test
        self.test_size = test_size

    async def export_sft(
        self,
        records: List[SFTRecord],
        output_path: str | Path,
        **kwargs: Any,
    ) -> None:
        """Export SFT records as HuggingFace Dataset.

        Args:
            records: List of SFT records to export.
            output_path: Path to write the dataset (directory for HF format).
            **kwargs: Additional options.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert records to dict format
        data = {
            "id": [r.id for r in records],
            "prompt": [r.prompt for r in records],
            "response": [r.response for r in records],
            "model": [r.model or "unknown" for r in records],
            "timestamp": [r.timestamp for r in records],
        }

        # Optional fields
        if any(r.thought_chain for r in records):
            data["thought_chain"] = [r.thought_chain or "" for r in records]

        if any(r.prompt_tokens for r in records):
            data["prompt_tokens"] = [r.prompt_tokens or 0 for r in records]
            data["completion_tokens"] = [r.completion_tokens or 0 for r in records]
            data["total_tokens"] = [r.total_tokens or 0 for r in records]

        # Create dataset
        dataset = HFDataset.from_dict(data)

        # Split if requested
        if self.split_train_test and len(records) > 1:
            split_dataset = dataset.train_test_split(test_size=self.test_size)
            dataset_dict = DatasetDict(train=split_dataset["train"], test=split_dataset["test"])

            # Save as dataset directory (HF format)
            dataset_dict.save_to_disk(str(output_path))
        else:
            # Save single file
            # If output_path ends with .parquet, save as parquet
            if output_path.suffix == ".parquet":
                dataset.to_parquet(str(output_path))
            else:
                # Otherwise save as HF dataset directory
                dataset.save_to_disk(str(output_path))

    async def export_rl(
        self,
        records: List[RLRecord],
        output_path: str | Path,
        **kwargs: Any,
    ) -> None:
        """Export RL records as HuggingFace Dataset.

        Args:
            records: List of RL records to export.
            output_path: Path to write the dataset.
            **kwargs: Additional options.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Extract trajectory data
        data = {
            "rollout_id": [r.rollout_id for r in records],
            "attempt_id": [r.attempt_id for r in records],
            "query": [r.query or "" for r in records],
            "response": [r.response or "" for r in records],
            "reward": [r.reward or 0.0 for r in records],
            "model": [r.model or "unknown" for r in records],
            "timestamp": [r.timestamp for r in records],
            # Store trajectory as JSON string
            "trajectory": [rtrajectory_to_json(r.trajectory) for r in records],
        }

        dataset = HFDataset.from_dict(data)

        if output_path.suffix == ".parquet":
            dataset.to_parquet(str(output_path))
        else:
            dataset.save_to_disk(str(output_path))

    def get_format_name(self) -> str:
        """Get the format name."""
        return "HuggingFace"


def rtrajectory_to_json(trajectory: List) -> str:
    """Convert trajectory list to JSON string."""
    import json

    # Handle Span objects
    if trajectory and hasattr(trajectory[0], "model_dump"):
        return json.dumps([t.model_dump() for t in trajectory])
    return json.dumps(trajectory)
