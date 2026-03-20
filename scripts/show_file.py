#!/usr/bin/env python3
"""
检查 Parquet 文件内容

替代命令: openclaw-tracer inspect PARQUET_PATH --limit N
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
from rich.console import Console
from rich.table import Table


def main(parquet_path: str, limit: int = 10):
    """检查 Parquet 文件

    Args:
        parquet_path: Parquet 文件路径
        limit: 显示的记录数量
    """
    path = Path(parquet_path)

    if not path.exists():
        print(f"✗ 文件不存在: {parquet_path}")
        return

    console = Console()

    # 读取数据
    df = pd.read_parquet(path)

    console.print(f"[cyan]文件:[/cyan] {parquet_path}")
    console.print(f"[cyan]形状:[/cyan] {df.shape[0]} 行 × {df.shape[1]} 列")
    console.print(f"[cyan]列名:[/cyan] {list(df.columns)}\n")

    # 显示数据表格
    table = Table(title=f"前 {min(limit, len(df))} 条记录")
    for col in df.columns:
        table.add_column(col, overflow="fold")

    for _, row in df.head(limit).iterrows():
        table.add_row(*[str(v)[:100] for v in row.values])

    console.print(table)

    # 显示基本统计
    if "prompt_tokens" in df.columns and "completion_tokens" in df.columns:
        console.print("\n[bold]Token 统计:[/bold]")
        console.print(f"  总 Prompt Tokens:  {df['prompt_tokens'].sum():,}")
        console.print(f"  总 Completion Tokens: {df['completion_tokens'].sum():,}")
        console.print(f"  总 Tokens: {df['total_tokens'].sum():,}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="检查 Parquet 文件内容")
    parser.add_argument("parquet_path", help="Parquet 文件路径")
    parser.add_argument("--limit", "-l", type=int, default=10, help="显示的记录数量")

    args = parser.parse_args()

    main(parquet_path=args.parquet_path, limit=args.limit)
