# Copyright (c) 2025 OpenClaw-Tracer
# TRL format exporter

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from openclaw_tracer.exporter.base import DataExporter
from openclaw_tracer.types.core import RLRecord, SFTRecord


class TRLExporter(DataExporter):
    """Export data in TRL (Transformer Reinforcement Learning) compatible format.

    TRL expects data in specific formats depending on the task:
    - SFT: For SFTTrainer, typically "text" column or prompt/response columns
    - RL: For PPOTrainer, query/response pairs
    - Reward: For reward models, prompt/chosen/rejected columns

    This exporter supports these formats.
    """

    def __init__(self, sft_format: str = "conversational"):
        """Initialize the TRL exporter.

        Args:
            sft_format: Format for SFT data. Options:
                - "conversational": Format with "messages" column
                - "instruction": Format with "instruction", "input", "output" columns
                - "text": Format with combined "text" column
        """
        self.sft_format = sft_format

    async def export_sft(
        self,
        records: List[SFTRecord],
        output_path: str | Path,
        **kwargs: Any,
    ) -> None:
        """Export SFT records in TRL-compatible format.

        Args:
            records: List of SFT records to export.
            output_path: Path to write the Parquet file.
            **kwargs: Additional options (format, columns, etc.)
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert records to dataframe based on format
        format_type = kwargs.get("format", self.sft_format)

        if format_type == "conversational":
            # TRL conversational format with messages column
            data = [
                {
                    "messages": [
                        {"role": "user", "content": record.prompt},
                        {"role": "assistant", "content": record.response},
                    ],
                    "id": record.id,
                    "model": record.model,
                    "timestamp": record.timestamp,
                }
                for record in records
            ]
        elif format_type == "instruction":
            # Instruction tuning format
            data = [
                {
                    "instruction": record.prompt,
                    "input": "",
                    "output": record.response,
                    "id": record.id,
                    "model": record.model,
                }
                for record in records
            ]
        elif format_type == "text":
            # Simple text format
            data = [
                {
                    "text": f"User: {record.prompt}\nAssistant: {record.response}",
                    "id": record.id,
                    "model": record.model,
                }
                for record in records
            ]
        else:
            raise ValueError(f"Unknown SFT format: {format_type}")

        df = pd.DataFrame(data)
        df.to_parquet(output_path, index=False)

    async def export_rl(
        self,
        records: List[RLRecord],
        output_path: str | Path,
        **kwargs: Any,
    ) -> None:
        """Export RL records in TRL-compatible format.

        For RL training (PPO), TRL typically expects:
        - query: The input prompt
        - response: The generated response
        - Optional: reward, ref_response, etc.

        Args:
            records: List of RL records to export.
            output_path: Path to write the Parquet file.
            **kwargs: Additional options.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = []
        for record in records:
            # Get query and response from the trajectory
            query = record.query
            if not query and record.trajectory:
                # Try to extract query from first span
                first_span = record.trajectory[0]
                query = first_span.attributes.get("llm.messages", "")

            response = record.response
            if not response and record.trajectory:
                # Try to get response from last span
                last_span = record.trajectory[-1]
                response = last_span.attributes.get("llm.response.content", "")

            row = {
                "query": query or "",
                "response": response or "",
                "rollout_id": record.rollout_id,
                "attempt_id": record.attempt_id,
                "model": record.model,
            }

            # Add reward if available
            if record.reward is not None:
                row["reward"] = record.reward

            data.append(row)

        df = pd.DataFrame(data)
        df.to_parquet(output_path, index=False)

    async def export_reward(
        self,
        records: List[Dict[str, Any]],
        output_path: str | Path,
        **kwargs: Any,
    ) -> None:
        """Export data for reward model training.

        Reward models typically expect:
        - prompt: The input prompt
        - chosen: The better response
        - rejected: The worse response

        Args:
            records: List of records with prompt/chosen/rejected.
            output_path: Path to write the Parquet file.
            **kwargs: Additional options.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df = pd.DataFrame(records)
        df.to_parquet(output_path, index=False)

    def get_format_name(self) -> str:
        """Get the format name."""
        return "TRL"
