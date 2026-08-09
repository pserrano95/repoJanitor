from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Any

from .gitops import create_worktree
from .models import TaskLimits, TaskPacket
from .redaction import redact


SUPPORTED_EVENTS = {"merge_group", "pull_request", "push", "workflow_dispatch"}
SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SIGNATURE_TOKEN = re.compile(r"[a-z_][a-z0-9_.:/-]{2,}")


@dataclass(frozen=True)
class CapturedCommand:
    command: tuple[str, ...]
    exit_code: int
    log_path: Path
    redactions: int
    duration_seconds: float


@dataclass(frozen=True)
class GitHubContext:
    event_name: str
    repository: str
    sha: str
    workflow: str
    job: str
    run_id: str
    run_attempt: str
    run_url: str


@dataclass(frozen=True)
class ReproductionResult:
    status: str
    capture: CapturedCommand
    worktree: Path
    similarity: float
    reason: str

    @property
    def reproduced(self) -> bool:
        return self.status == "REPRODUCED"


def parse_command_json(raw: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("command-json must be a JSON array of strings") from exc
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(part, str) or not part for part in value)
    ):
        raise ValueError("command-json must be a non-empty JSON array of non-empty strings")
    if value[0].startswith("-"):
        raise ValueError("command executable cannot start with '-'")
    return tuple(value)


def parse_multiline(raw: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in raw.splitlines() if line.strip())


def _append_bounded(buffer: bytearray, chunk: str, limit: int) -> None:
    buffer.extend(chunk.encode("utf-8", errors="replace"))
    if len(buffer) > limit:
        del buffer[: len(buffer) - limit]


def capture_command(
    command: Sequence[str],
    *,
    cwd: Path,
    log_path: Path,
    max_log_bytes: int = 65_536,
    timeout_seconds: int = 600,
    remove_env: Sequence[str] = (),
) -> CapturedCommand:
    if not command:
        raise ValueError("Capture command cannot be empty")
    if not 1_024 <= max_log_bytes <= 10_000_000:
        raise ValueError("max_log_bytes must be between 1024 and 10000000")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    started = time.monotonic()
    child_env = dict(os.environ)
    for name in remove_env:
        child_env.pop(name, None)
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=0,
        shell=False,
        env=child_env,
    )
    if process.stdout is None:  # pragma: no cover - guaranteed by PIPE
        raise RuntimeError("Unable to capture command output")

    chunks: queue.Queue[str | None] = queue.Queue(maxsize=128)

    def pump() -> None:
        try:
            while True:
                chunk = process.stdout.read(4_096)
                if not chunk:
                    break
                chunks.put(chunk)
        finally:
            chunks.put(None)

    reader = threading.Thread(target=pump, name="repojanitor-log-reader", daemon=True)
    reader.start()
    bounded = bytearray()
    timed_out = False
    finished_reading = False
    deadline = started + timeout_seconds
    while not finished_reading:
        remaining = deadline - time.monotonic()
        if remaining <= 0 and process.poll() is None:
            timed_out = True
            process.kill()
        try:
            chunk = chunks.get(timeout=0.1)
        except queue.Empty:
            continue
        if chunk is None:
            finished_reading = True
            continue
        _append_bounded(bounded, chunk, max_log_bytes)

    process.wait()
    reader.join(timeout=1)
    process.stdout.close()
    exit_code = 124 if timed_out else int(process.returncode)
    if timed_out:
        marker = f"\n[RepoJanitor terminated the command after {timeout_seconds}s]\n"
        sys.stdout.write(marker)
        _append_bounded(bounded, marker, max_log_bytes)

    raw_tail = bounded.decode("utf-8", errors="replace")
    clean_tail, redactions = redact(raw_tail)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(clean_tail, encoding="utf-8")
    if clean_tail:
        sys.stdout.write(clean_tail)
        if not clean_tail.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    return CapturedCommand(
        command=tuple(command),
        exit_code=exit_code,
        log_path=log_path,
        redactions=redactions,
        duration_seconds=time.monotonic() - started,
    )


def failure_similarity(left: str, right: str) -> float:
    def signature(value: str) -> set[str]:
        clean = ANSI_ESCAPE.sub("", value.lower())
        clean = re.sub(r"(?:[a-z]:)?[\\/][^\s]+", "<path>", clean)
        clean = re.sub(r"\b(?:0x)?[a-f0-9]{8,}\b", "<id>", clean)
        clean = re.sub(r"\b\d+(?:\.\d+)?\b", "<number>", clean)
        return set(SIGNATURE_TOKEN.findall(clean))

    left_tokens = signature(left)
    right_tokens = signature(right)
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def reproduce_failure(
    original: CapturedCommand,
    *,
    repo: Path,
    worktree_base: Path,
    task_id: str,
    base_ref: str,
    log_path: Path,
    max_log_bytes: int,
    timeout_seconds: int,
    remove_env: Sequence[str] = (),
    similarity_threshold: float = 0.5,
) -> ReproductionResult:
    worktree = create_worktree(
        repo,
        worktree_base,
        f"{task_id}-reproduction",
        base_ref,
    )
    capture = capture_command(
        original.command,
        cwd=worktree,
        log_path=log_path,
        max_log_bytes=max_log_bytes,
        timeout_seconds=timeout_seconds,
        remove_env=remove_env,
    )
    original_log = original.log_path.read_text(encoding="utf-8", errors="replace")
    reproduction_log = capture.log_path.read_text(encoding="utf-8", errors="replace")
    similarity = failure_similarity(original_log, reproduction_log)

    if capture.exit_code == 0:
        status = "NOT_REPRODUCIBLE"
        reason = "The owner-declared command passed in the clean worktree."
    elif capture.exit_code == 124:
        status = "REPRODUCTION_TIMEOUT"
        reason = "The clean-worktree reproduction timed out."
    elif capture.exit_code != original.exit_code:
        status = "REPRODUCTION_MISMATCH"
        reason = (
            "The clean-worktree exit code did not match the original failure "
            f"({original.exit_code} != {capture.exit_code})."
        )
    elif similarity < similarity_threshold:
        status = "REPRODUCTION_MISMATCH"
        reason = (
            "The clean-worktree failure signature did not meet the configured "
            f"similarity threshold ({similarity:.3f} < {similarity_threshold:.3f})."
        )
    else:
        status = "REPRODUCED"
        reason = "The failure reproduced from the verified commit in a clean worktree."

    return ReproductionResult(
        status=status,
        capture=capture,
        worktree=worktree,
        similarity=similarity,
        reason=reason,
    )


def reproduction_payload(
    original: CapturedCommand,
    result: ReproductionResult,
) -> dict[str, Any]:
    return {
        "status": result.status,
        "reason": result.reason,
        "original_exit_code": original.exit_code,
        "reproduction_exit_code": result.capture.exit_code,
        "original_duration_seconds": original.duration_seconds,
        "reproduction_duration_seconds": result.capture.duration_seconds,
        "failure_similarity": result.similarity,
        "worktree": str(result.worktree),
    }


def _load_event(env: Mapping[str, str]) -> dict[str, Any]:
    event_path = env.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        raise RuntimeError("GITHUB_EVENT_PATH is required")
    with Path(event_path).open("r", encoding="utf-8") as handle:
        event = json.load(handle)
    if not isinstance(event, dict):
        raise RuntimeError("GitHub event payload must be a JSON object")
    return event


def verify_github_context(
    repo: Path,
    *,
    env: Mapping[str, str] | None = None,
    allow_fork: bool = False,
) -> GitHubContext:
    values = os.environ if env is None else env
    if values.get("GITHUB_ACTIONS", "").lower() != "true":
        raise RuntimeError("This command only accepts an authenticated GitHub Actions context")

    event_name = values.get("GITHUB_EVENT_NAME", "")
    if event_name == "pull_request_target":
        raise RuntimeError("pull_request_target is not trusted for model inference")
    if event_name not in SUPPORTED_EVENTS:
        raise RuntimeError(f"Unsupported GitHub event for inference: {event_name or 'missing'}")

    event = _load_event(values)
    repository = values.get("GITHUB_REPOSITORY", "")
    event_repository = str(event.get("repository", {}).get("full_name", ""))
    if not repository or event_repository != repository:
        raise RuntimeError("GitHub event repository does not match GITHUB_REPOSITORY")

    pull_request = event.get("pull_request")
    if isinstance(pull_request, dict):
        head_repo = str(pull_request.get("head", {}).get("repo", {}).get("full_name", ""))
        base_repo = str(pull_request.get("base", {}).get("repo", {}).get("full_name", ""))
        if head_repo and base_repo and head_repo != base_repo and not allow_fork:
            raise RuntimeError("Fork pull requests are disabled for model inference")

    sha = values.get("GITHUB_SHA", "")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if head.returncode != 0:
        raise RuntimeError(f"Unable to verify checkout provenance: {head.stderr.strip()}")
    if not sha or head.stdout.strip().lower() != sha.lower():
        raise RuntimeError("Checked-out HEAD does not match GITHUB_SHA")

    server = values.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    run_id = values.get("GITHUB_RUN_ID", "")
    return GitHubContext(
        event_name=event_name,
        repository=repository,
        sha=sha,
        workflow=values.get("GITHUB_WORKFLOW", ""),
        job=values.get("GITHUB_JOB", ""),
        run_id=run_id,
        run_attempt=values.get("GITHUB_RUN_ATTEMPT", "1"),
        run_url=f"{server}/{repository}/actions/runs/{run_id}" if run_id else "",
    )


def default_task_id(context: GitHubContext) -> str:
    raw = f"gh-{context.run_id}-{context.run_attempt}-{context.job}".strip("-")
    safe = SAFE_ID.sub("-", raw).strip("-")
    return (safe or "github-ci-failure")[:128]


def build_failure_packet(
    capture: CapturedCommand,
    context: GitHubContext,
    *,
    title: str,
    context_files: Sequence[str],
    allowed_paths: Sequence[str],
    forbidden_paths: Sequence[str] = (),
    acceptance: Sequence[str] = (),
    task_id: str | None = None,
    limits: TaskLimits | None = None,
    reproduction: ReproductionResult | None = None,
) -> TaskPacket:
    log_tail = capture.log_path.read_text(encoding="utf-8", errors="replace")
    evidence_items = [
        f"GitHub event: {context.event_name}",
        f"Repository: {context.repository}",
        f"Workflow/job: {context.workflow} / {context.job}",
        f"Run: {context.run_url} (attempt {context.run_attempt})",
        f"Commit: {context.sha}",
        f"Owner-declared command: {json.dumps(capture.command)}",
        f"Exit code: {capture.exit_code}; duration: {capture.duration_seconds:.2f}s",
        "Bounded, redacted original CI log tail:\n" + log_tail,
    ]
    if reproduction is not None:
        reproduction_log = reproduction.capture.log_path.read_text(
            encoding="utf-8", errors="replace"
        )
        evidence_items.extend(
            [
                f"Clean-worktree reproduction status: {reproduction.status}",
                f"Failure signature similarity: {reproduction.similarity:.3f}",
                "Bounded, redacted clean-worktree reproduction log tail:\n"
                + reproduction_log,
            ]
        )
    return TaskPacket(
        id=task_id or default_task_id(context),
        kind="github_actions_failure",
        title=title,
        base_ref=context.sha,
        evidence=tuple(evidence_items),
        acceptance=tuple(acceptance),
        context_files=tuple(context_files),
        allowed_paths=tuple(allowed_paths),
        forbidden_paths=tuple(forbidden_paths),
        limits=limits or TaskLimits(),
    )


def write_packet(path: Path, packet: TaskPacket) -> None:
    payload = {
        "id": packet.id,
        "kind": packet.kind,
        "title": packet.title,
        "base_ref": packet.base_ref,
        "evidence": list(packet.evidence),
        "acceptance": list(packet.acceptance),
        "context_files": list(packet.context_files),
        "allowed_paths": list(packet.allowed_paths),
        "forbidden_paths": list(packet.forbidden_paths),
        "limits": {
            "max_changed_files": packet.limits.max_changed_files,
            "max_diff_lines": packet.limits.max_diff_lines,
            "max_context_bytes": packet.limits.max_context_bytes,
            "max_output_tokens": packet.limits.max_output_tokens,
            "max_cost_usd": packet.limits.max_cost_usd,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
