#!/usr/bin/env python3
"""
导出收集的数据为训练格式

替代命令: openclaw-tracer export INPUT_PARQUET OUTPUT_PATH --format FORMAT --type TYPE
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import openclaw_tracer as agl


async def main(
    input_parquet: str,
    output_path: str,
    format: str = "trl",
    type: str = "sft",
):
    """导出数据

    Args:
        input_parquet: 输入的 Parquet 文件路径
        output_path: 输出路径
        format: 导出格式 (trl, hf)
        type: 数据类型 (sft, rl)
    """
    import pandas as pd

    input_path = Path(input_parquet)

    if not input_path.exists():
        print(f"✗ 文件不存在: {input_parquet}")
        return

    # 加载数据
    print(f"加载文件: {input_parquet}")
    df = pd.read_parquet(input_parquet)
    print(f"✓ 加载了 {len(df)} 条记录")

    # 转换为记录对象
    records = []
    from openclaw_tracer.types.core import SFTRecord, RLRecord, Span

    for _, row in df.iterrows():
        if type == "sft":
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
            trajectory_data = json.loads(row.get("trajectory", "[]"))
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

    # 导出
    if format == "trl":
        exporter = agl.TRLExporter()
    else:
        exporter = agl.HFExporter()

    print(f"导出格式: {exporter.get_format_name()}")

    if type == "sft":
        await exporter.export_sft(records, output_path)
    else:
        await exporter.export_rl(records, output_path)

    print(f"✓ 导出完成: {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="导出收集的数据")
    parser.add_argument("input_parquet", help="输入的 Parquet 文件")
    parser.add_argument("output_path", help="输出路径")
    parser.add_argument("--format", "-f", choices=["trl", "hf"], default="trl", help="导出格式")
    parser.add_argument("--type", "-t", choices=["sft", "rl"], default="sft", help="数据类型")

    args = parser.parse_args()

    asyncio.run(main(
        input_parquet=args.input_parquet,
        output_path=args.output_path,
        format=args.format,
        type=args.type,
    ))
