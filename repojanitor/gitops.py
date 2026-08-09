from __future__ import annotations

import re
import subprocess
from pathlib import Path


SAFE_TASK_ID = re.compile(r"[^A-Za-z0-9._-]+")


def run_git(repo: Path, args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def repository_root(path: Path) -> Path:
    result = run_git(path, ["rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()).resolve()


def create_worktree(repo: Path, worktree_base: Path, task_id: str, base_ref: str) -> Path:
    safe_id = SAFE_TASK_ID.sub("-", task_id).strip("-") or "task"
    target = (worktree_base / safe_id).resolve()
    worktree_base_resolved = worktree_base.resolve()
    try:
        target.relative_to(worktree_base_resolved)
    except ValueError as exc:
        raise RuntimeError("Worktree target escaped configured directory") from exc
    if target.exists():
        raise RuntimeError(f"Worktree already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    run_git(repo, ["worktree", "add", "--detach", str(target), base_ref])
    return target


def apply_patch(worktree: Path, patch: str) -> None:
    run_git(worktree, ["apply", "--whitespace=nowarn", "-"], input_text=patch)


def diff_stat(worktree: Path) -> str:
    return run_git(worktree, ["diff", "--stat"]).stdout.strip()

