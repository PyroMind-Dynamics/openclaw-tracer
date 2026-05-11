#!/usr/bin/env python3
"""
读取并展示 data/spans 目录下最新的 Parquet 文件中的 LLM 调用记录。

默认按时间取全局 N 条 span。使用 --by-task 时按 rollout_id（Task ID）聚合：
同一任务画在一个外层框内，组内多条 span 用分隔线分开；组内按 start_time 升序。
相邻两条若 `llm.request.system` 整段相同则省略 System；若 `llm.request.messages` 整段相同则省略 Input。
不要求 attempt_id 相同。
"""

import argparse
import json
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
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Input 里 image_url 在终端中的预览长度（超出则加 ...）
IMAGE_URL_DISPLAY_MAX_LEN = 120


def _preview_image_url(url: str) -> str:
    if len(url) <= IMAGE_URL_DISPLAY_MAX_LEN:
        return url
    return url[:IMAGE_URL_DISPLAY_MAX_LEN] + "..."


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


def _parquet_cell(row: "pd.Series", key: str):
    """Return cell value or None if missing / NaN / empty."""
    if key not in row.index:
        return None
    v = row[key]
    try:
        if v is None or pd.isna(v):
            return None
    except (ValueError, TypeError):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def merge_parsed_with_span_row(parsed: dict, row: "pd.Series") -> dict:
    """Merge attributes JSON with top-level Parquet columns (timing, task id, reward)."""
    out = dict(parsed)
    for key in ("start_time", "end_time", "status"):
        v = _parquet_cell(row, key)
        if v is not None:
            out[key] = v
    tid = _parquet_cell(row, "rollout_id")
    if tid is not None:
        out["task_id"] = str(tid)
    aid = _parquet_cell(row, "attempt_id")
    if aid is not None:
        out["attempt_id"] = str(aid)
    pr = _parquet_cell(row, "previous_reward")
    if pr is not None:
        out["previous_reward"] = float(pr)
    fr = _parquet_cell(row, "final_reward")
    if fr is not None:
        out["final_reward"] = float(fr)
    return out


def _format_task_meta_line(call: dict, *, include_task_id: bool = True) -> str | None:
    parts = []
    if include_task_id and call.get("task_id"):
        parts.append(f"Task ID: {call['task_id']}")
    if call.get("attempt_id"):
        parts.append(f"Attempt: {call['attempt_id']}")
    if "previous_reward" in call and call["previous_reward"] is not None:
        parts.append(f"Previous reward: {call['previous_reward']}")
    return " | ".join(parts) if parts else None


def _group_key_rollout(row: "pd.Series") -> str:
    tid = _parquet_cell(row, "rollout_id")
    if tid is None:
        return "__no_task__"
    s = str(tid).strip()
    return s if s else "__no_task__"


def order_task_groups(
    selected: "pd.DataFrame", *, early: bool
) -> list[tuple[str, "pd.DataFrame"]]:
    """Partition rows by rollout_id; order groups by recency (latest) or age (early)."""
    if selected.empty:
        return []
    keys = selected.apply(_group_key_rollout, axis=1)
    selected = selected.copy()
    selected["_task_group"] = keys
    groups: list[tuple[str, pd.DataFrame]] = []
    for gid, gdf in selected.groupby("_task_group", sort=False):
        gdf = gdf.drop(columns=["_task_group"], errors="ignore")
        groups.append((gid, gdf))
    if early:
        groups.sort(key=lambda x: float(x[1]["start_time"].min()))
    else:
        groups.sort(key=lambda x: -float(x[1]["start_time"].max()))
    return groups


def _normalize_prompt_field(val) -> str:
    """Stable string for comparing system / messages between spans."""
    if val is None:
        return ""
    return val if isinstance(val, str) else str(val)


def omit_prompt_blocks(prev_call: dict | None, call: dict) -> tuple[bool, bool]:
    """Returns (omit_system, omit_user_prompt) for consecutive rows in same task group (--by-task).

    Same rollout_id is guaranteed by the caller. ``messages`` are compared as the full stored
    string (e.g. different ``media/images/...`` paths mean a different user prompt). No attempt_id
    match required.
    """
    if prev_call is None:
        return False, False
    sys_same = _normalize_prompt_field(prev_call.get("llm.request.system")) == _normalize_prompt_field(
        call.get("llm.request.system")
    )
    msg_same = _normalize_prompt_field(prev_call.get("llm.request.messages")) == _normalize_prompt_field(
        call.get("llm.request.messages")
    )
    return sys_same, msg_same


def task_group_display_name(group_id: str) -> str:
    return "(no task id)" if group_id == "__no_task__" else group_id


def ensure_final_reward_column(df: "pd.DataFrame") -> "pd.DataFrame":
    """Old Parquet shards may omit ``final_reward``; align so UI can always show a row."""
    if "final_reward" not in df.columns:
        df = df.copy()
        df["final_reward"] = float("nan")
    return df


def final_reward_summary_for_task_group(gdf: "pd.DataFrame") -> str | None:
    """One line for --by-task: numeric if ``/end_task`` wrote a value, else em dash (未上报)."""
    if gdf.empty:
        return None
    if "final_reward" not in gdf.columns:
        return "Final reward: —"
    try:
        valid = gdf["final_reward"].dropna()
    except Exception:
        return "Final reward: —"
    if valid.empty:
        return "Final reward: —"
    return f"Final reward: {float(valid.iloc[0])}"


def format_call_plain(
    call: dict,
    *,
    omit_system: bool = False,
    omit_user_prompt: bool = False,
    inner_section: bool = False,
) -> str:
    """纯文本格式化。inner_section=True 用于嵌在同一 Task 大框内的子段（用 --- 而非 ===）。"""
    lines = []

    # 基本信息
    timestamp = datetime.fromtimestamp(call.get("start_time", 0)).strftime("%Y-%m-%d %H:%M:%S")
    model = call.get("llm.model", "unknown")
    duration = (call.get("end_time", 0) - call.get("start_time", 0)) * 1000

    bar = "-" * 70 if inner_section else "=" * 70
    lines.append(f"\n{bar}")
    lines.append(f"{timestamp} | Model: {model} | Duration: {duration:.0f}ms")
    meta = _format_task_meta_line(call)
    if meta:
        lines.append(meta)
    lines.append(f"{bar}\n")

    # System prompt (如果有)
    if not omit_system:
        system = call.get("llm.request.system", "")
        if system:
            lines.append("System:")
            if len(str(system)) > 300:
                system = str(system)[:300] + "... (truncated)"
            lines.append(f"  {system}\n")

    # 输入消息
    if not omit_user_prompt:
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
                                lines.append(f"    Image: {_preview_image_url(url)}")
                    else:
                        if len(str(content)) > 500:
                            content = str(content)[:500] + "... (truncated)"
                        lines.append(f"  [{role}]: {content}")
            except Exception:
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


def _rich_panel_title(call: dict):
    from rich.text import Text

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
    return header


def _rich_panel_body_parts(
    call: dict,
    *,
    omit_system: bool = False,
    omit_user_prompt: bool = False,
):
    from rich.text import Text

    content_parts = []

    meta_line = _format_task_meta_line(call)
    if meta_line:
        meta_text = Text()
        meta_text.append(meta_line + "\n", style="dim")
        content_parts.append(meta_text)

    if not omit_system:
        system = call.get("llm.request.system", "")
        if system:
            system_text = Text()
            system_text.append("System:\n", style="bold yellow")
            if len(str(system)) > 300:
                system = str(system)[:300] + "... (truncated)"
            system_text.append(f"{system}\n")
            content_parts.append(system_text)

    messages_text = Text()
    if not omit_user_prompt:
        messages_str = call.get("llm.request.messages", "")
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
                                messages_text.append(f"[Image: {_preview_image_url(url)}]\n", style="dim")
                    else:
                        if len(str(content)) > 500:
                            content = str(content)[:500] + "... (truncated)"
                        messages_text.append(f"{content}\n")
            except Exception:
                messages_text.append(str(messages_str)[:500])

        input_label = Text()
        input_label.append("Input:\n", style="bold cyan")
        content_parts.append(input_label)
        content_parts.append(messages_text)

    reasoning = call.get("llm.response.reasoning", "")
    if reasoning:
        reasoning_text = Text()
        reasoning_text.append("\n")
        reasoning_text.append("Reasoning:\n", style="bold magenta")
        if len(str(reasoning)) > 500:
            reasoning = str(reasoning)[:500] + "... (truncated)"
        reasoning_text.append(f"{reasoning}")
        content_parts.append(reasoning_text)

    response_content = call.get("llm.response.content", "")
    response_text = Text()
    response_text.append("\n")
    response_text.append("Response:\n", style="bold green")
    if response_content:
        if len(str(response_content)) > 1000:
            response_content = str(response_content)[:1000] + "... (truncated)"
        response_text.append(f"{response_content}")
    else:
        response_text.append("(empty response)", style="dim")

    content_parts.append(response_text)
    return content_parts


def _rich_tokens_footer(call: dict):
    from rich.text import Text

    footer = Text()
    if call.get("llm.usage.total_tokens"):
        footer.append("Tokens: ", style="dim")
        footer.append(f"{call.get('llm.usage.prompt_tokens', 0)} + ", style="yellow")
        footer.append(f"{call.get('llm.usage.completion_tokens', 0)} = ", style="yellow")
        footer.append(f"{call.get('llm.usage.total_tokens', 0)} total", style="green bold")
    return footer


def format_call_rich(
    call: dict,
    console: Console,
    *,
    omit_system: bool = False,
    omit_user_prompt: bool = False,
) -> None:
    """单条 span：独立 Panel（扁平模式）。"""
    from rich.panel import Panel
    from rich.text import Text

    header = _rich_panel_title(call)
    content_parts = _rich_panel_body_parts(call, omit_system=omit_system, omit_user_prompt=omit_user_prompt)
    footer = _rich_tokens_footer(call)

    console.print(Panel(
        Text.assemble(*content_parts),
        title=header,
        title_align="left",
        border_style="bright_blue",
        padding=(0, 1),
    ))
    if str(footer):
        console.print(footer)


def format_task_group_rich(
    console: Console,
    task_label: str,
    span_count: int,
    truncated_note: str | None,
    entries: list[tuple[dict, bool, bool]],
    *,
    final_reward_summary: str | None = None,
) -> None:
    """同一 Task 下所有 span 画在一个 Panel 内。"""
    from rich.console import Group
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.text import Text

    title = Text()
    title.append("Task: ", style="bold")
    title.append(task_label, style="cyan")
    title.append(f" | spans: {span_count}", style="dim")

    subtitle: Text | None = None
    if final_reward_summary:
        subtitle = Text()
        if final_reward_summary.endswith("—"):
            subtitle.append(final_reward_summary, style="dim italic")
        else:
            subtitle.append(final_reward_summary, style="bold green")

    parts: list = []
    if truncated_note:
        parts.append(Text(truncated_note + "\n", style="dim italic"))

    for i, (call, os, ou) in enumerate(entries):
        if i > 0:
            parts.append(Rule(style="dim"))
        parts.append(_rich_panel_title(call))
        parts.append(Text("\n"))
        parts.append(Text.assemble(*_rich_panel_body_parts(call, omit_system=os, omit_user_prompt=ou)))
        ft = _rich_tokens_footer(call)
        if str(ft):
            parts.append(Text("\n"))
            parts.append(ft)
        parts.append(Text("\n"))

    console.print(Panel(
        Group(*parts),
        title=title,
        title_align="left",
        subtitle=subtitle,
        subtitle_align="left",
        border_style="bright_blue",
        padding=(0, 1),
    ))


def format_task_group_plain(
    task_label: str,
    span_count: int,
    truncated_note: str | None,
    entries: list[tuple[dict, bool, bool]],
    *,
    final_reward_summary: str | None = None,
) -> str:
    """同一 Task 外层一个大框，子 span 用 --- 分隔。"""
    parts: list[str] = ["\n" + "=" * 70, f"Task: {task_label} | spans: {span_count}"]
    if final_reward_summary:
        parts.append(final_reward_summary)
    if truncated_note:
        parts.append(truncated_note)
    parts.append("=" * 70)
    for i, (call, os, ou) in enumerate(entries):
        chunk = format_call_plain(call, omit_system=os, omit_user_prompt=ou, inner_section=True)
        if i == 0:
            chunk = chunk.lstrip("\n")
        parts.append(chunk)
    parts.append("=" * 70)
    return "\n".join(parts)


def iter_calls_with_prompt_dedup(rows):
    """Yield (call, omit_system, omit_user_prompt) with consecutive prompt dedup within a task group."""
    prev_call: dict | None = None
    for _, row in rows:
        call = merge_parsed_with_span_row(row["parsed"], row)
        os, ou = omit_prompt_blocks(prev_call, call)
        yield call, os, ou
        prev_call = call


def main():
    parser = argparse.ArgumentParser(
        description=(
            "读取并展示 data/spans 下最新 Parquet 中的 LLM 调用。"
            "可用 --by-task：同一 Task 单框展示，组内时间升序并省略相邻重复 prompt。"
        ),
    )
    parser.add_argument(
        "--num", "-n",
        type=int,
        default=5,
        help="默认：全局 span 条数。使用 --by-task 时表示展示的任务（唯一 rollout_id）数量 (默认: 5)",
    )
    parser.add_argument(
        "--by-task",
        action="store_true",
        help="按 Task ID（rollout_id）聚合；组内时间升序；相邻 span 的 system / messages 整段字符串分别相同则省略对应块（图片路径不同即 messages 不同）",
    )
    parser.add_argument(
        "--max-spans-per-task",
        type=int,
        default=None,
        metavar="K",
        help="仅 --by-task：每组最多展示 K 条 span（省略超出部分并提示）；不设则不限制",
    )
    parser.add_argument(
        "--early", "-e",
        action="store_true",
        help="全局模式：最早的 N 条 span；--by-task：按每组最早 start_time 升序选取 N 个任务",
    )
    parser.add_argument(
        "--latest", "-l",
        action="store_true",
        default=True,
        help="全局模式：最晚的 N 条 span（默认）；--by-task：按每组最晚 start_time 降序选取 N 个任务",
    )
    parser.add_argument(
        "--spans-dir",
        default="data/spans",
        help="Spans Parquet 文件目录 (默认: data/spans)",
    )
    parser.add_argument(
        "--no-rich",
        action="store_true",
        help="不使用 Rich 彩色输出",
    )

    args = parser.parse_args()

    if args.max_spans_per_task is not None and args.max_spans_per_task < 1:
        print("Error: --max-spans-per-task must be >= 1 when set.", file=sys.stderr)
        sys.exit(2)

    # 获取最新的 Parquet 文件
    parquet_file = get_latest_parquet_file(args.spans_dir)

    if not parquet_file:
        print(f"Error: No Parquet files found in {args.spans_dir}")
        print(f"Please run the proxy server first to collect some data.")
        sys.exit(1)

    print(f"Reading: {parquet_file}")

    # 读取 Parquet 文件
    df = pd.read_parquet(parquet_file)
    df = ensure_final_reward_column(df)

    # 筛选出 LLM 调用记录 (有 llm.request.messages 的记录)
    llm_calls = df[df["attributes"].str.contains("llm.request.messages", na=False)].copy()

    if llm_calls.empty:
        print("No LLM calls found in the file.")
        sys.exit(0)

    # 解析 attributes
    llm_calls["parsed"] = llm_calls["attributes"].apply(parse_attributes)

    use_rich = RICH_AVAILABLE and not args.no_rich
    console = Console() if use_rich else None

    if args.by_task:
        all_groups = order_task_groups(llm_calls, early=args.early)
        groups = all_groups[: args.num]
        print(
            f"Found {len(llm_calls)} LLM call records across {len(all_groups)} task(s); "
            f"showing {len(groups)} task group(s) (--by-task), spans ascending by time within each task.\n"
        )
        for gid, gdf in groups:
            gdf = gdf.sort_values("start_time", ascending=True)
            total_in_group = len(gdf)
            truncated_note: str | None = None
            if args.max_spans_per_task is not None:
                if total_in_group > args.max_spans_per_task:
                    truncated_note = (
                        f"{total_in_group - args.max_spans_per_task} more span(s) omitted "
                        f"(limit {args.max_spans_per_task}; increase --max-spans-per-task)"
                    )
                gdf = gdf.head(args.max_spans_per_task)

            label = task_group_display_name(gid)
            shown = len(gdf)
            entries = list(iter_calls_with_prompt_dedup(gdf.iterrows()))
            fr_summary = final_reward_summary_for_task_group(gdf)
            if use_rich and console:
                format_task_group_rich(
                    console, label, shown, truncated_note, entries, final_reward_summary=fr_summary
                )
            else:
                print(
                    format_task_group_plain(
                        label, shown, truncated_note, entries, final_reward_summary=fr_summary
                    )
                )
                print()
    else:
        llm_sorted = llm_calls.sort_values("start_time", ascending=args.early)
        selected = llm_sorted.head(args.num)
        print(
            f"Found {len(llm_calls)} LLM call records, showing {len(selected)} "
            f"{('earliest' if args.early else 'latest')} span(s)...\n"
        )
        if use_rich and console:
            for _, row in selected.iterrows():
                call = merge_parsed_with_span_row(row["parsed"], row)
                format_call_rich(call, console)
        else:
            for _, row in selected.iterrows():
                call = merge_parsed_with_span_row(row["parsed"], row)
                print(format_call_plain(call))
                print()


if __name__ == "__main__":
    main()
