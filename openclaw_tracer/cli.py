# Copyright (c) 2025 OpenClaw-Tracer
# Command-line interface for OpenClaw-Tracer

import asyncio
import json
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from openclaw_tracer.exporter.hf_format import HFExporter
from openclaw_tracer.exporter.trl_format import TRLExporter
from openclaw_tracer.proxy.llm_proxy import LLMProxy, run_proxy
from openclaw_tracer.storage.parquet_store import ParquetStore

console = Console()


@click.group()
@click.version_option(version="0.1.2")
def cli():
    """OpenClaw-Tracer - LLM data collection for SFT and RL training."""
    pass


@cli.command()
@click.option(
    "--port",
    type=int,
    default=None,
    help="Port to listen on (default: random available port)",
)
@click.option(
    "--host",
    type=str,
    default="0.0.0.0",
    help="Host to bind to (default: 0.0.0.0)",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to model configuration JSON file",
)
@click.option(
    "--output-dir",
    type=str,
    default="data",
    help="Directory for Parquet output (default: data)",
)
@click.option(
    "--buffer-size",
    type=int,
    default=100,
    help="Buffer size before flushing to disk (default: 100)",
)
def serve(port: Optional[int], host: str, config: Optional[str], output_dir: str, buffer_size: int):
    """Start the LiteLLM proxy server for data collection.

    Example:

        openclaw-tracer serve --config models.json --output-dir ./data
    """
    # Load model configuration
    model_list = []
    if config:
        with open(config) as f:
            config_data = json.load(f)
            model_list = config_data.get("model_list", config_data.get("models", []))
    else:
        # Default models from environment
        import os

        if os.getenv("OPENAI_API_KEY"):
            model_list = [
                {
                    "model_name": "gpt-4",
                    "litellm_params": {
                        "model": "openai/gpt-4",
                    },
                }
            ]
        console.print(
            "[yellow]No config provided. Using default models. "
            "Set OPENAI_API_KEY or provide --config.[/yellow]"
        )

    if not model_list:
        console.print("[red]No models configured. Exiting.[/red]")
        return

    # Run the proxy
    console.print(
        Panel.fit(
            f"[bold green]Starting OpenClaw-Tracer proxy[/bold green]\n"
            f"Host: {host}\n"
            f"Models: {len(model_list)}\n"
            f"Output: {output_dir}",
            title="Data Collection Proxy",
        )
    )

    async def run():
        store = ParquetStore(output_dir=output_dir, buffer_size=buffer_size)
        proxy = LLMProxy(port=port, host=host, model_list=model_list, store=store)

        await proxy.start()

        # Show server info
        table = Table(title="Proxy Server Info")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("URL", proxy.url)
        table.add_row("V1 Endpoint", proxy.v1_url)
        table.add_row("Status", "Running")

        for model in model_list:
            name = model.get("model_name", model.get("model", "unknown"))
            table.add_row("Model", name)

        console.print(table)
        console.print("\n[dim]Press Ctrl+C to stop the server[/dim]\n")

        try:
            await proxy.wait()
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
            await proxy.stop()

    asyncio.run(run())


@cli.command()
@click.argument("input_parquet", type=click.Path(exists=True))
@click.argument("output_path", type=click.Path())
@click.option(
    "--format",
    type=click.Choice(["trl", "hf"], case_sensitive=False),
    default="trl",
    help="Export format (default: trl)",
)
@click.option(
    "--type",
    type=click.Choice(["sft", "rl"], case_sensitive=False),
    default="sft",
    help="Data type to export (default: sft)",
)
def export(input_parquet: str, output_path: str, format: str, type: str):
    """Export collected data to training formats.

    Example:

        openclaw-tracer export data/sft_records.parquet output/trl_data --format trl --type sft
    """
    async def do_export():
        # Load records from parquet
        import pandas as pd

        df = pd.read_parquet(input_parquet)
        console.print(f"[green]Loaded {len(df)} records from {input_parquet}[/green]")

        # Convert to records
        from openclaw_tracer.types.core import SFTRecord, RLRecord

        records = []
        for _, row in df.iterrows():
            if type == "sft":
                import json

                records.append(
                    SFTRecord(
                        id=row["id"],
                        prompt=row["prompt"],
                        response=row["response"],
                        thought_chain=row.get("thought_chain"),
                        model=row.get("model"),
                        rollout_id=row.get("rollout_id"),
                        timestamp=row["timestamp"],
                        metadata=json.loads(row.get("metadata", "{}")),
                        prompt_tokens=row.get("prompt_tokens"),
                        completion_tokens=row.get("completion_tokens"),
                        total_tokens=row.get("total_tokens"),
                    )
                )
            else:  # rl
                import json

                trajectory_data = json.loads(row.get("trajectory", "[]"))
                from openclaw_tracer.types.core import Span

                trajectory = [Span(**s) for s in trajectory_data]

                records.append(
                    RLRecord(
                        rollout_id=row["rollout_id"],
                        attempt_id=row["attempt_id"],
                        trajectory=trajectory,
                        reward=row.get("reward"),
                        query=row.get("query"),
                        response=row.get("response"),
                        model=row.get("model"),
                        timestamp=row["timestamp"],
                        metadata=json.loads(row.get("metadata", "{}")),
                    )
                )

        # Export using appropriate exporter
        if format == "trl":
            exporter = TRLExporter()
        else:
            exporter = HFExporter()

        console.print(f"[cyan]Exporting to {exporter.get_format_name()} format...[/cyan]")

        if type == "sft":
            await exporter.export_sft(records, output_path)
        else:
            await exporter.export_rl(records, output_path)

        console.print(f"[green]Exported to {output_path}[/green]")

    asyncio.run(do_export())


@cli.command()
@click.argument("parquet_path", type=click.Path(exists=True))
@click.option(
    "--limit",
    type=int,
    default=10,
    help="Number of records to show (default: 10)",
)
def inspect(parquet_path: str, limit: int):
    """Inspect a Parquet file to see its contents.

    Example:

        openclaw-tracer inspect data/sft_records.parquet --limit 5
    """
    import pandas as pd

    df = pd.read_parquet(parquet_path)

    console.print(f"[cyan]File: {parquet_path}[/cyan]")
    console.print(f"[cyan]Shape: {df.shape}[/cyan]")
    console.print(f"[cyan]Columns: {list(df.columns)}[/cyan]\n")

    table = Table(title=f"First {min(limit, len(df))} Records")
    for col in df.columns:
        table.add_column(col, overflow="fold")

    for _, row in df.head(limit).iterrows():
        table.add_row(*[str(v)[:100] for v in row.values])

    console.print(table)


@cli.command()
@click.option(
    "--output-dir",
    type=str,
    default="data",
    help="Directory to check (default: data)",
)
def stats(output_dir: str):
    """Show statistics about collected data.

    Example:

        openclaw-tracer stats --output-dir ./data
    """
    from pathlib import Path

    data_dir = Path(output_dir)

    table = Table(title="Data Collection Statistics")
    table.add_column("File", style="cyan")
    table.add_column("Records", style="green")
    table.add_column("Size", style="yellow")

    total_records = 0
    total_size = 0

    for parquet_file in data_dir.glob("*.parquet"):
        try:
            import pandas as pd

            df = pd.read_parquet(parquet_file)
            size = parquet_file.stat().st_size
            total_records += len(df)
            total_size += size

            table.add_row(
                parquet_file.name,
                str(len(df)),
                f"{size / 1024:.1f} KB",
            )
        except Exception as e:
            table.add_row(parquet_file.name, f"Error: {e}", "-")

    console.print(table)

    if total_records > 0:
        console.print(
            f"\n[bold]Total:[/bold] {total_records} records, {total_size / 1024:.1f} KB"
        )


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
