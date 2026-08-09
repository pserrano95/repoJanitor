from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import ModelResult, TaskPacket, CommandResult


def write_artifacts(
    artifact_dir: Path,
    packet: TaskPacket,
    model_result: ModelResult,
    estimated_cost_usd: float,
    status: str,
    paths: tuple[str, ...],
    validations: tuple[CommandResult, ...],
    redaction_count: int,
    worktree: Path | None,
    application_error: str | None = None,
) -> tuple[Path, Path, Path]:
    run_dir = artifact_dir / packet.id
    run_dir.mkdir(parents=True, exist_ok=True)
    patch_path = run_dir / "proposed.patch"
    patch_path.write_text(model_result.fix.patch, encoding="utf-8")

    validation_lines = []
    for result in validations:
        label = "PASS" if result.passed else "FAIL"
        validation_lines.append(
            f"- `{label}` `{' '.join(result.command)}` ({result.duration_seconds:.2f}s)"
        )
    if not validation_lines:
        validation_lines.append("- Not executed (analysis-only mode).")

    changed_files = "".join(f"- `{path}`\n" for path in paths)
    risks = "".join(f"- {risk}\n" for risk in model_result.fix.risks) or "- None declared.\n"
    assumptions = (
        "".join(f"- {item}\n" for item in model_result.fix.assumptions)
        or "- None declared.\n"
    )
    application = (
        f"- Rejected before validation: `{application_error}`"
        if application_error
        else "- Applied successfully or not requested."
    )

    report = f"""# RepoJanitor report: {packet.id}

## Outcome

- Status: **{status}**
- Task: {packet.title}
- Confidence: {model_result.fix.confidence:.2f}
- Estimated model cost: ${estimated_cost_usd:.6f}
- Redactions applied before inference: {redaction_count}
- Worktree: `{worktree or 'not created'}`

## Diagnosis

{model_result.fix.diagnosis}

**Proposed root cause:** {model_result.fix.root_cause}

## Proposed change

{model_result.fix.summary}

Files declared by the validated patch:
{changed_files}
## Validation

{application}

{chr(10).join(validation_lines)}

Only commands configured by the repository owner were executed. Commands suggested by the model were ignored.

## Risks

{risks}
## Assumptions

{assumptions}
"""
    report_path = run_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    metadata = {
        "task_id": packet.id,
        "status": status,
        "request_id": model_result.request_id,
        "patch_sha256": hashlib.sha256(model_result.fix.patch.encode("utf-8")).hexdigest(),
        "input_tokens": model_result.usage.input_tokens,
        "cached_input_tokens": model_result.usage.cached_input_tokens,
        "output_tokens": model_result.usage.output_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "redactions": redaction_count,
        "changed_files": list(paths),
        "validation_exit_codes": [result.exit_code for result in validations],
        "application_error": application_error,
    }
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return report_path, patch_path, metadata_path
