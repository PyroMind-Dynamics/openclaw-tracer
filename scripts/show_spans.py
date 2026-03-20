#!/usr/bin/env python3
"""
读取并展示 data/spans 目录下最新的 Parquet 文件中的 LLM 调用记录
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def get_latest_parquet_file(spans_dir: str) -> str | None:
    """获取最新的 Parquet 文件"""
    spans_path = Path(spans_dir)
    if not spans_path.exists():
        return None

    files = list(spans_path.glob("spans_*.parquet"))
    if not files:
        return None

    # 按修改时间排序，返回最新的
    return max(files, key=lambda f: f.stat().st_mtime)


def parse_attributes(attrs_str: str) -> dict:
    """解析 attributes JSON 字符串"""
    try:
        return json.loads(attrs_str) if isinstance(attrs_str, str) else {}
    except json.JSONDecodeError:
        return {}


def format_call_plain(call: dict) -> str:
    """纯文本格式化"""
    lines = []

    # 基本信息
    timestamp = datetime.fromtimestamp(call.get("start_time", 0)).strftime("%Y-%m-%d %H:%M:%S")
    model = call.get("llm.model", "unknown")
    duration = (call.get("end_time", 0) - call.get("start_time", 0)) * 1000

    lines.append(f"\n{'='*70}")
    lines.append(f"{timestamp} | Model: {model} | Duration: {duration:.0f}ms")
    lines.append(f"{'='*70}\n")

    # System prompt (如果有)
    system = call.get("llm.request.system", "")
    if system:
        lines.append("System:")
        if len(str(system)) > 300:
            system = str(system)[:300] + "... (truncated)"
        lines.append(f"  {system}\n")

    # 输入消息
    messages_str = call.get("llm.request.messages", "")
    if messages_str:
        lines.append("Input Messages:")
        try:
            messages = json.loads(messages_str) if isinstance(messages_str, str) else messages_str
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")

                if isinstance(content, list):
                    lines.append(f"  [{role}]:")
                    for item in content:
                        if item.get("type") == "text":
                            lines.append(f"    Text: {item.get('text', '')}")
                        elif item.get("type") == "image_url":
                            url = item.get("image_url", {}).get("url", "")
                            lines.append(f"    Image: {url[:60]}...")
                else:
                    if len(str(content)) > 500:
                        content = str(content)[:500] + "... (truncated)"
                    lines.append(f"  [{role}]: {content}")
        except:
            lines.append(f"  {messages_str[:500]}")

    # 思考过程 (如果有)
    reasoning = call.get("llm.response.reasoning", "")
    if reasoning:
        lines.append(f"\nReasoning:")
        if len(str(reasoning)) > 500:
            reasoning = str(reasoning)[:500] + "... (truncated)"
        lines.append(f"  {reasoning}")

    # 输出响应
    response_content = call.get("llm.response.content", "")
    lines.append(f"\nResponse:")
    if response_content:
        if len(str(response_content)) > 1000:
            response_content = str(response_content)[:1000] + "... (truncated)"
        lines.append(f"  {response_content}")
    else:
        lines.append("  (empty response)")

    # Token 使用
    if call.get("llm.usage.total_tokens"):
        lines.append(f"\nTokens: {call.get('llm.usage.prompt_tokens', 0)} prompt + "
                   f"{call.get('llm.usage.completion_tokens', 0)} completion = "
                   f"{call.get('llm.usage.total_tokens', 0)} total")

    return "\n".join(lines)


def format_call_rich(call: dict, console: Console) -> None:
    """使用 Rich 格式化"""
    from rich import box
    from rich.panel import Panel
    from rich.text import Text

    # 基本信息
    start_time = call.get("start_time", 0)
    timestamp = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S")
    model = call.get("llm.model", "unknown")
    duration = (call.get("end_time", 0) - start_time) * 1000
    status = call.get("status", "UNKNOWN")

    status_color = "green" if status == "OK" else "red"

    header = Text()
    header.append(f"{timestamp} | ", style="dim")
    header.append(f"Model: {model} | ", style="bold cyan")
    header.append(f"Duration: {duration:.0f}ms | ", style="dim")
    header.append(f"Status: [{status}]", style=status_color)

    # 构建内容文本
    content_parts = []

    # System prompt
    system = call.get("llm.request.system", "")
    if system:
        system_text = Text()
        system_text.append("[bold yellow]System:[/bold yellow]\n", style="yellow")
        if len(str(system)) > 300:
            system = str(system)[:300] + "... (truncated)"
        system_text.append(f"{system}\n")
        content_parts.append(system_text)

    # 解析消息
    messages_str = call.get("llm.request.messages", "")
    messages_text = Text()
    if messages_str:
        try:
            messages = json.loads(messages_str) if isinstance(messages_str, str) else messages_str
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")

                messages_text.append(f"  [{role}]: ", style="yellow")

                if isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            messages_text.append(f"{item.get('text', '')}\n")
                        elif item.get("type") == "image_url":
                            url = item.get("image_url", {}).get("url", "")
                            messages_text.append(f"[Image: {url[:60]}...]\n", style="dim")
                else:
                    if len(str(content)) > 500:
                        content = str(content)[:500] + "... (truncated)"
                    messages_text.append(f"{content}\n")
        except:
            messages_text.append(str(messages_str)[:500])

    content_parts.append(Text("[bold cyan]Input:[/bold cyan]\n", style="cyan"))
    content_parts.append(messages_text)

    # 思考过程 (如果有)
    reasoning = call.get("llm.response.reasoning", "")
    if reasoning:
        reasoning_text = Text()
        reasoning_text.append("\n[bold magenta]Reasoning:[/bold magenta]\n", style="magenta")
        if len(str(reasoning)) > 500:
            reasoning = str(reasoning)[:500] + "... (truncated)"
        reasoning_text.append(f"{reasoning}")
        content_parts.append(reasoning_text)

    # 响应内容
    response_content = call.get("llm.response.content", "")
    response_text = Text()
    response_text.append("\n[bold green]Response:[/bold green]\n", style="green")
    if response_content:
        if len(str(response_content)) > 1000:
            response_content = str(response_content)[:1000] + "... (truncated)"
        response_text.append(f"{response_content}")
    else:
        response_text.append("(empty response)", style="dim")

    content_parts.append(response_text)

    # Token 使用
    footer = Text()
    if call.get("llm.usage.total_tokens"):
        footer.append(f"Tokens: ", style="dim")
        footer.append(f"{call.get('llm.usage.prompt_tokens', 0)} + ", style="yellow")
        footer.append(f"{call.get('llm.usage.completion_tokens', 0)} = ", style="yellow")
        footer.append(f"{call.get('llm.usage.total_tokens', 0)} total", style="green bold")

    # 打印面板
    console.print(Panel(
        Text.assemble(*content_parts),
        title=header,
        title_align="left",
        border_style="bright_blue",
        padding=(0, 1),
    ))
    if str(footer):
        console.print(footer)


def main():
    parser = argparse.ArgumentParser(
        description="读取并展示 data/spans 目录下最新的 Parquet 文件中的 LLM 调用记录"
    )
    parser.add_argument(
        "--num", "-n",
        type=int,
        default=5,
        help="展示的记录数量 (默认: 5)"
    )
    parser.add_argument(
        "--early", "-e",
        action="store_true",
        help="显示最早的 N 条记录"
    )
    parser.add_argument(
        "--latest", "-l",
        action="store_true",
        default=True,
        help="显示最晚的 N 条记录 (默认)"
    )
    parser.add_argument(
        "--spans-dir",
        default="data/spans",
        help="Spans Parquet 文件目录 (默认: data/spans)"
    )
    parser.add_argument(
        "--no-rich",
        action="store_true",
        help="不使用 Rich 彩色输出"
    )

    args = parser.parse_args()

    # 获取最新的 Parquet 文件
    parquet_file = get_latest_parquet_file(args.spans_dir)

    if not parquet_file:
        print(f"Error: No Parquet files found in {args.spans_dir}")
        print(f"Please run the proxy server first to collect some data.")
        sys.exit(1)

    print(f"Reading: {parquet_file}")

    # 读取 Parquet 文件
    df = pd.read_parquet(parquet_file)

    # 筛选出 LLM 调用记录 (有 llm.request.messages 的记录)
    llm_calls = df[df["attributes"].str.contains("llm.request.messages", na=False)].copy()

    if llm_calls.empty:
        print("No LLM calls found in the file.")
        sys.exit(0)

    print(f"Found {len(llm_calls)} LLM call records, showing {args.num} {('earliest' if args.early else 'latest')}...\n")

    # 解析 attributes
    llm_calls["parsed"] = llm_calls["attributes"].apply(parse_attributes)

    # 排序
    llm_calls = llm_calls.sort_values("start_time", ascending=args.early)

    # 选择 N 条
    selected = llm_calls.head(args.num)

    # 展示
    use_rich = RICH_AVAILABLE and not args.no_rich

    if use_rich:
        console = Console()
        for _, row in selected.iterrows():
            format_call_rich(row["parsed"], console)
    else:
        for _, row in selected.iterrows():
            print(format_call_plain(row["parsed"]))
            print()


if __name__ == "__main__":
    main()
