#!/usr/bin/env python3
"""
分析 OpenClaw-Tracer HTTP 访问日志

解析 JSONL 格式的 HTTP 访问日志，提供统计和分析功能。
"""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


def parse_log_file(log_file: str):
    """Parse log file and yield entries.

    Args:
        log_file: Path to the log file

    Yields:
        Parsed log entries as dictionaries
    """
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse line: {e}")


def analyze_logs(log_file: str, details: bool = False):
    """Analyze HTTP access log and print statistics.

    Args:
        log_file: Path to the log file
        details: Whether to show detailed entry-by-entry output
    """
    if not Path(log_file).exists():
        print(f"Error: Log file not found: {log_file}")
        return

    entries = list(parse_log_file(log_file))

    if not entries:
        print(f"Log file is empty: {log_file}")
        return

    # Count by type
    type_counts = Counter(e.get("type") for e in entries)

    # Count by status code (responses only)
    status_counts = Counter(
        e.get("status_code") for e in entries if e.get("type") == "response"
    )

    # Count by endpoint path
    path_counts = Counter(
        e.get("path", "unknown") for e in entries if e.get("type") == "request"
    )

    # Count errors
    errors = [e for e in entries if e.get("type") == "error" or e.get("error")]
    error_paths = Counter(e.get("path", "unknown") for e in errors)

    # Calculate durations
    durations = [
        e.get("duration_ms")
        for e in entries
        if e.get("type") == "response" and e.get("duration_ms") is not None
    ]
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Time range
    timestamps = [e.get("timestamp") for e in entries if e.get("timestamp")]
    if timestamps:
        start_time = min(timestamps)
        end_time = max(timestamps)
    else:
        start_time = end_time = "N/A"

    print("=" * 60)
    print(f"HTTP Access Log Analysis: {log_file}")
    print("=" * 60)
    print(f"\nTotal entries:       {len(entries)}")
    print(f"Time range:          {start_time} to {end_time}")
    print(f"\nEntry types:")
    for entry_type, count in type_counts.most_common():
        print(f"  {entry_type}:           {count}")

    if status_counts:
        print(f"\nResponse status codes:")
        for status, count in status_counts.most_common():
            print(f"  {status}:               {count}")

    if errors:
        print(f"\nErrors:               {len(errors)}")
        print(f"\nError paths:")
        for path, count in error_paths.most_common(10):
            print(f"  {path}:               {count}")

    print(f"\nTop endpoints:")
    for path, count in path_counts.most_common(10):
        print(f"  {path}:               {count}")

    if durations:
        print(f"\nResponse times:")
        print(f"  Average:             {avg_duration:.2f} ms")
        print(f"  Min:                 {min(durations):.2f} ms")
        print(f"  Max:                 {max(durations):.2f} ms")

    print("\n" + "=" * 60)

    # Show details if requested
    if details:
        print("\nDetailed entries:")
        print("-" * 60)

        for i, entry in enumerate(entries):
            print(f"\n[{i}] {entry.get('type', 'unknown').upper()}")
            print(f"  Timestamp: {entry.get('timestamp', 'N/A')}")
            print(f"  Request ID: {entry.get('request_id', 'N/A')}")

            if entry.get("type") == "request":
                print(f"  Method: {entry.get('method', 'N/A')}")
                print(f"  Path: {entry.get('path', 'N/A')}")
                if entry.get("body"):
                    body = entry["body"]
                    if len(body) > 200:
                        body = body[:200] + "..."
                    print(f"  Body: {body}")

            elif entry.get("type") == "response":
                print(f"  Status: {entry.get('status_code', 'N/A')}")
                print(f"  Duration: {entry.get('duration_ms', 'N/A')} ms")
                if entry.get("error"):
                    print(f"  Error: {entry.get('error')}")
                if entry.get("body"):
                    body = entry["body"]
                    if len(body) > 200:
                        body = body[:200] + "..."
                    print(f"  Body: {body}")

            elif entry.get("type") == "error":
                print(f"  Method: {entry.get('method', 'N/A')}")
                print(f"  Path: {entry.get('path', 'N/A')}")
                print(f"  Error: {entry.get('error', 'N/A')}")


def filter_logs(log_file: str, entry_type: str = None, status: int = None):
    """Filter and print specific log entries.

    Args:
        log_file: Path to the log file
        entry_type: Filter by entry type (request, response, error)
        status: Filter by status code (for responses)
    """
    for entry in parse_log_file(log_file):
        if entry_type and entry.get("type") != entry_type:
            continue
        if status is not None and entry.get("status_code") != status:
            continue
        print(json.dumps(entry, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="分析 OpenClaw-Tracer HTTP 访问日志"
    )
    parser.add_argument("log_file", help="日志文件路径")
    parser.add_argument(
        "--details", "-d", action="store_true", help="显示详细条目"
    )
    parser.add_argument(
        "--filter-type", "-t", choices=["request", "response", "error"],
        help="按类型过滤"
    )
    parser.add_argument(
        "--filter-status", "-s", type=int, help="按状态码过滤"
    )

    args = parser.parse_args()

    if args.filter_type or args.filter_status is not None:
        filter_logs(args.log_file, args.filter_type, args.filter_status)
    else:
        analyze_logs(args.log_file, details=args.details)


if __name__ == "__main__":
    main()
