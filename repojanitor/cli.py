from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from .config import load_config
from .gitops import repository_root
from .github_actions import (
    CapturedCommand,
    ReproductionResult,
    build_failure_packet,
    capture_command,
    default_task_id,
    parse_command_json,
    parse_multiline,
    reproduce_failure,
    reproduction_payload,
    verify_github_context,
    write_packet,
)
from .orchestrator import RepoJanitor, load_packet
from .provider import FileProvider, create_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repojanitor", description="Policy-first CI failure fixer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check local configuration")
    doctor.add_argument("--config", required=True)

    run = subparsers.add_parser("run", help="Analyze a task and optionally apply its patch")
    run.add_argument("--config", required=True)
    run.add_argument("--packet", required=True)
    run.add_argument("--apply", action="store_true", help="Apply patch in a detached worktree and validate")
    run.add_argument("--mock-response", help="Read a model response from JSON instead of calling the provider")

    ci = subparsers.add_parser(
        "ci",
        help="Run an owner-declared check and diagnose a GitHub Actions failure",
    )
    ci.add_argument("--config", required=True)
    ci.add_argument("--command-json", required=True, help="Command as a JSON string array; no shell")
    ci.add_argument("--title", default="GitHub Actions check failed")
    ci.add_argument("--context-files", required=True, help="Newline-separated repository paths")
    ci.add_argument("--allowed-paths", default="", help="Newline-separated patch allowlist")
    ci.add_argument("--forbidden-paths", default="", help="Newline-separated patch denylist")
    ci.add_argument("--acceptance", default="", help="Newline-separated acceptance criteria")
    ci.add_argument("--task-id")
    ci.add_argument("--max-log-bytes", type=int, default=65_536)
    ci.add_argument("--allow-fork", action="store_true")
    ci.add_argument(
        "--skip-reproduction",
        action="store_true",
        help="Skip the clean-worktree reproduce-before-repair gate",
    )
    ci.add_argument("--apply", action="store_true")
    ci.add_argument("--mock-response", help="Offline response fixture for integration tests")
    return parser


def doctor(config_path: str) -> int:
    config = load_config(config_path)
    checks = {
        "git": shutil.which("git") is not None,
        "repository": False,
        "api_key": bool(os.environ.get(config.provider.api_key_env)),
        "validation_commands": bool(config.validation_commands),
    }
    try:
        repository_root(config.repo_path)
        checks["repository"] = True
    except Exception:
        pass
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'WARN'} {name}")
    print(f"Provider: {config.provider.name} ({config.provider.adapter})")
    print(f"Model: {config.provider.model}")
    print(f"API: {config.provider.base_url}")
    return 0 if checks["git"] and checks["repository"] else 1


def run_task(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    packet = load_packet(args.packet)
    provider = (
        FileProvider(Path(args.mock_response).resolve())
        if args.mock_response
        else create_provider(config)
    )
    result = RepoJanitor(config, provider).run(packet, apply=args.apply)
    print(json.dumps({
        "task_id": result.task_id,
        "status": result.status,
        "report": result.report_path,
        "patch": result.patch_path,
        "worktree": result.worktree_path,
        "estimated_cost_usd": config.provider.pricing.estimate(result.model_result.usage),
    }, indent=2))
    return 0 if result.status not in {"FAILED_VALIDATION", "PATCH_REJECTED"} else 2


def _write_github_output(values: dict[str, str | int | None]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        for name, value in values.items():
            if value is not None:
                handle.write(f"{name}={value}\n")


def _append_github_summary(report_path: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    report = Path(report_path).read_text(encoding="utf-8")
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(report)
        handle.write("\n")


def _reproduction_section(record: dict[str, object]) -> str:
    return f"""## Clean-worktree reproduction

- Status: **{record['status']}**
- Original exit code: {record['original_exit_code']}
- Reproduction exit code: {record['reproduction_exit_code']}
- Failure-signature similarity: {float(record['failure_similarity']):.3f}
- Result: {record['reason']}

The command came from repository-owner configuration and ran without the provider credential.
"""


def _write_reproduction_record(
    run_dir: Path,
    original: CapturedCommand,
    reproduction: ReproductionResult,
) -> dict[str, object]:
    record = reproduction_payload(original, reproduction)
    (run_dir / "reproduction.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    return record


def _write_reproduction_gate_report(
    run_dir: Path,
    task_id: str,
    title: str,
    record: dict[str, object],
) -> Path:
    report_path = run_dir / "report.md"
    report_path.write_text(
        f"""# RepoJanitor report: {task_id}

## Outcome

- Status: **{record['status']}**
- Task: {title}
- Provider called: **no**
- Estimated model cost: $0.000000

{_reproduction_section(record)}

No repair was requested because the verified commit did not reproduce the original failure closely enough.
""",
        encoding="utf-8",
    )
    metadata = {
        "task_id": task_id,
        "status": record["status"],
        "provider_called": False,
        "estimated_cost_usd": 0.0,
        "reproduction": record,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return report_path


def _attach_reproduction_to_model_artifacts(
    report_path: Path,
    record: dict[str, object],
) -> None:
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write(_reproduction_section(record))
    metadata_path = report_path.parent / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["provider_called"] = True
    metadata["reproduction"] = record
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def run_ci(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    repo = repository_root(config.repo_path)
    command = parse_command_json(args.command_json)
    context = verify_github_context(repo, allow_fork=args.allow_fork)
    task_id = args.task_id or default_task_id(context)
    capture_dir = config.artifact_dir / task_id
    capture = capture_command(
        command,
        cwd=repo,
        log_path=capture_dir / "ci.log",
        max_log_bytes=args.max_log_bytes,
        timeout_seconds=config.command_timeout_seconds,
        remove_env=(config.provider.api_key_env,),
    )
    if capture.exit_code == 0:
        _write_github_output({"status": "CI_PASSED", "command-exit-code": 0})
        print(json.dumps({"status": "CI_PASSED", "command_exit_code": 0}, indent=2))
        return 0

    context_files = parse_multiline(args.context_files)
    if not context_files:
        raise ValueError("context-files must contain at least one repository path")
    allowed_paths = parse_multiline(args.allowed_paths) or context_files
    reproduction = None
    reproduction_record = None
    if not getattr(args, "skip_reproduction", False):
        reproduction = reproduce_failure(
            capture,
            repo=repo,
            worktree_base=config.worktree_dir,
            task_id=task_id,
            base_ref=context.sha,
            log_path=capture_dir / "reproduction.log",
            max_log_bytes=args.max_log_bytes,
            timeout_seconds=config.command_timeout_seconds,
            remove_env=(config.provider.api_key_env,),
            similarity_threshold=config.reproduction_similarity_threshold,
        )
        reproduction_record = _write_reproduction_record(
            capture_dir, capture, reproduction
        )
    packet = build_failure_packet(
        capture,
        context,
        title=args.title,
        context_files=context_files,
        allowed_paths=allowed_paths,
        forbidden_paths=parse_multiline(args.forbidden_paths),
        acceptance=parse_multiline(args.acceptance),
        task_id=task_id,
        reproduction=reproduction,
    )
    packet_path = capture_dir / "packet.json"
    write_packet(packet_path, packet)
    if reproduction is not None and not reproduction.reproduced:
        if reproduction_record is None:  # pragma: no cover - guarded by construction
            raise RuntimeError("Missing reproduction evidence")
        report_path = _write_reproduction_gate_report(
            capture_dir,
            task_id,
            args.title,
            reproduction_record,
        )
        values = {
            "status": reproduction.status,
            "command-exit-code": capture.exit_code,
            "report": str(report_path),
            "packet": str(packet_path),
            "run-dir": str(capture_dir),
        }
        _write_github_output(values)
        _append_github_summary(str(report_path))
        print(json.dumps(values, indent=2))
        return 1
    provider = (
        FileProvider(Path(args.mock_response).resolve())
        if args.mock_response
        else create_provider(config)
    )
    result = RepoJanitor(config, provider).run(packet, apply=args.apply)
    if reproduction_record is not None:
        _attach_reproduction_to_model_artifacts(
            Path(result.report_path), reproduction_record
        )
    run_dir = str(Path(result.report_path).parent)
    values = {
        "status": result.status,
        "command-exit-code": capture.exit_code,
        "report": result.report_path,
        "patch": result.patch_path,
        "packet": str(packet_path),
        "run-dir": run_dir,
    }
    _write_github_output(values)
    _append_github_summary(result.report_path)
    print(json.dumps(values, indent=2))
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor(args.config)
        if args.command == "ci":
            return run_ci(args)
        return run_task(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
