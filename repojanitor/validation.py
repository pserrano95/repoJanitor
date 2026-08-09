from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .models import CommandResult


def run_validations(
    worktree: Path,
    commands: tuple[tuple[str, ...], ...],
    timeout_seconds: int,
) -> tuple[CommandResult, ...]:
    results: list[CommandResult] = []
    for command in commands:
        if not command:
            continue
        started = time.monotonic()
        try:
            process = subprocess.run(
                list(command),
                cwd=worktree,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            result = CommandResult(
                command=command,
                exit_code=process.returncode,
                stdout=process.stdout[-20_000:],
                stderr=process.stderr[-20_000:],
                duration_seconds=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(
                command=command,
                exit_code=124,
                stdout=(exc.stdout or "")[-20_000:] if isinstance(exc.stdout, str) else "",
                stderr="Validation timed out",
                duration_seconds=time.monotonic() - started,
            )
        results.append(result)
        if not result.passed:
            break
    return tuple(results)

