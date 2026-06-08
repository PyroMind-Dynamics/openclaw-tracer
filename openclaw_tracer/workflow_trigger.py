# Copyright (c) 2025 OpenClaw-Tracer
# Async, non-blocking workflow trigger script execution after buffer flush.

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_WORKFLOW_TRIGGER_SCRIPT = Path("/app/trigger/test.sh")

_warned_missing_lock = threading.Lock()
_warned_missing_paths: set[str] = set()


def resolve_workflow_script_path(explicit: str | Path | None) -> Path:
    """Resolve script path: explicit argument, then WORKFLOW_TRIGGER_SCRIPT, then default."""
    if explicit is not None:
        return Path(os.path.expanduser(str(explicit)))
    env = os.getenv("WORKFLOW_TRIGGER_SCRIPT")
    if env and env.strip():
        return Path(os.path.expanduser(env.strip()))
    return DEFAULT_WORKFLOW_TRIGGER_SCRIPT


def schedule_workflow_trigger(script: Path) -> None:
    """Run the workflow script in the background without blocking callers.

    Safe to call from async code after persistence: uses ``create_task`` only.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "No running event loop; skipping workflow trigger for %s",
            script,
        )
        return

    resolved = Path(script)

    async def _task() -> None:
        try:
            await run_workflow_trigger(resolved)
        except Exception:
            logger.exception("Workflow trigger task failed for %s", resolved)

    loop.create_task(_task())


async def run_workflow_trigger(script: Path) -> None:
    """Execute trigger script asynchronously; logs errors, does not raise to callers."""
    path = Path(os.path.expanduser(str(script)))

    try:
        if not path.is_file():
            with _warned_missing_lock:
                key = os.path.abspath(str(path))
                if key not in _warned_missing_paths:
                    _warned_missing_paths.add(key)
                    logger.warning(
                        "Workflow trigger script not found or not a file: %s",
                        path,
                    )
            return

        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout_unused, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_text = (stderr.decode(errors="replace") if stderr else "").strip()
            tail = err_text[-2000:] if len(err_text) > 2000 else err_text
            logger.error(
                "Workflow trigger script %s exited with code %s: %s",
                path,
                proc.returncode,
                tail or "(no stderr)",
            )
        else:
            logger.info("Workflow trigger script %s exited with code %s", path, proc.returncode)
    except Exception:
        logger.exception("Workflow trigger failed for %s", path)
