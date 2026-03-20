#!/usr/bin/env python3
"""
显示数据收集统计信息

替代命令: openclaw-tracer stats --output-dir DIR
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
from rich.console import Console
from rich.table import Table


def main(output_dir: str = "data"):
    """显示统计信息

    Args:
        output_dir: 数据目录路径
    """
    console = Console()
    data_dir = Path(output_dir)

    if not data_dir.exists():
        console.print(f"[yellow]目录不存在: {output_dir}[/yellow]")
        return

    table = Table(title=f"数据统计 - {output_dir}")
    table.add_column("文件", style="cyan")
    table.add_column("记录数", style="green")
    table.add_column("文件大小", style="yellow")

    total_records = 0
    total_size = 0

    parquet_files = list(data_dir.glob("*.parquet"))

    if not parquet_files:
        console.print(f"[yellow]在 {output_dir} 中没有找到 Parquet 文件[/yellow]")
        console.print("\n提示: 先启动代理服务器收集数据")
        return

    for parquet_file in parquet_files:
        try:
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
            table.add_row(
                parquet_file.name,
                f"Error: {e}",
                "-",
            )

    console.print(table)

    if total_records > 0:
        console.print(
            f"\n[bold]总计:[/bold] {total_records} 条记录, {total_size / 1024:.1f} KB"
        )

    # 显示每个文件的列信息
    console.print("\n[bold]文件详情:[/bold]")
    for parquet_file in parquet_files:
        try:
            df = pd.read_parquet(parquet_file)
            console.print(f"\n[cyan]{parquet_file.name}[/cyan]:")
            console.print(f"  列: {list(df.columns)}")
            if len(df) > 0:
                console.print(f"  示例数据:")
                for col in df.columns[:3]:  # 只显示前3列
                    val = df[col].iloc[0]
                    val_str = str(val)[:50] + "..." if len(str(val)) > 50 else str(val)
                    console.print(f"    {col}: {val_str}")
        except Exception as e:
            console.print(f"\n[cyan]{parquet_file.name}[/cyan]: Error - {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="显示数据收集统计")
    parser.add_argument("--output-dir", "-o", default="data", help="数据目录路径")

    args = parser.parse_args()

    main(output_dir=args.output_dir)
