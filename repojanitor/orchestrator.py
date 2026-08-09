from __future__ import annotations

import json
from pathlib import Path

from .config import RepoConfig
from .gitops import apply_patch, create_worktree, repository_root
from .models import RunResult, TaskPacket
from .policy import validate_patch
from .prompting import build_prompt
from .provider import Provider
from .report import write_artifacts
from .validation import run_validations


def load_packet(path: str | Path) -> TaskPacket:
    with Path(path).open("r", encoding="utf-8") as handle:
        return TaskPacket.from_dict(json.load(handle))


class RepoJanitor:
    def __init__(self, config: RepoConfig, provider: Provider):
        self.config = config
        self.provider = provider

    def run(self, packet: TaskPacket, *, apply: bool = False) -> RunResult:
        repo = repository_root(self.config.repo_path)
        prompt, redaction_count = build_prompt(repo, self.config, packet)
        model_result = self.provider.propose_fix(packet, prompt)
        paths = validate_patch(model_result.fix.patch, self.config, packet)
        declared = tuple(path.replace("\\", "/") for path in model_result.fix.changed_files)
        if declared and set(declared) != set(paths):
            raise RuntimeError(
                "Model changed_files does not match paths present in the patch: "
                f"declared={declared}, patch={paths}"
            )
        estimated_cost = self.config.provider.pricing.estimate(model_result.usage)
        if estimated_cost > packet.limits.max_cost_usd:
            raise RuntimeError(
                f"Estimated model cost ${estimated_cost:.4f} "
                f"exceeds task limit ${packet.limits.max_cost_usd:.4f}"
            )

        worktree = None
        validations = ()
        status = "PROPOSED"
        if apply:
            worktree = create_worktree(
                repo,
                self.config.worktree_dir,
                packet.id,
                packet.base_ref,
            )
            apply_patch(worktree, model_result.fix.patch)
            validations = run_validations(
                worktree,
                self.config.validation_commands,
                self.config.command_timeout_seconds,
            )
            status = "VALIDATED" if validations and all(item.passed for item in validations) else "FAILED_VALIDATION"
            if not self.config.validation_commands:
                status = "PATCH_APPLIED_UNVERIFIED"

        report_path, patch_path, _ = write_artifacts(
            self.config.artifact_dir,
            packet,
            model_result,
            estimated_cost,
            status,
            paths,
            validations,
            redaction_count,
            worktree,
        )
        return RunResult(
            task_id=packet.id,
            status=status,
            report_path=str(report_path),
            patch_path=str(patch_path),
            worktree_path=str(worktree) if worktree else None,
            model_result=model_result,
            validations=validations,
        )
