from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class TaskLimits:
    max_changed_files: int = 6
    max_diff_lines: int = 300
    max_context_bytes: int = 2_000_000
    max_output_tokens: int = 32_000
    max_cost_usd: float = 0.30

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "TaskLimits":
        return cls(**(value or {}))


@dataclass(frozen=True)
class TaskPacket:
    id: str
    kind: str
    title: str
    base_ref: str = "HEAD"
    evidence: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()
    context_files: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ("**",)
    forbidden_paths: tuple[str, ...] = ()
    limits: TaskLimits = field(default_factory=TaskLimits)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.id):
            raise ValueError("Task id must be a safe 1-128 character identifier")
        if (
            not self.base_ref
            or self.base_ref.startswith("-")
            or ".." in self.base_ref
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", self.base_ref)
        ):
            raise ValueError("base_ref contains unsafe characters")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskPacket":
        required = ["id", "kind", "title"]
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise ValueError(f"Task packet is missing required fields: {', '.join(missing)}")
        return cls(
            id=str(value["id"]),
            kind=str(value["kind"]),
            title=str(value["title"]),
            base_ref=str(value.get("base_ref", "HEAD")),
            evidence=tuple(value.get("evidence", [])),
            acceptance=tuple(value.get("acceptance", [])),
            context_files=tuple(value.get("context_files", [])),
            allowed_paths=tuple(value.get("allowed_paths", ["**"])),
            forbidden_paths=tuple(value.get("forbidden_paths", [])),
            limits=TaskLimits.from_dict(value.get("limits")),
        )


@dataclass(frozen=True)
class ProposedFix:
    diagnosis: str
    root_cause: str
    confidence: float
    summary: str
    patch: str
    changed_files: tuple[str, ...]
    suggested_commands: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProposedFix":
        diagnosis = value.get("diagnosis", {})
        change = value.get("proposed_change", {})
        verification = value.get("verification", {})
        confidence = float(diagnosis.get("confidence", 0.0))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        patch = str(change.get("patch", ""))
        if not patch.strip():
            raise ValueError("Model response does not contain a patch")
        return cls(
            diagnosis=str(diagnosis.get("summary", "")),
            root_cause=str(diagnosis.get("root_cause", "")),
            confidence=confidence,
            summary=str(change.get("summary", "")),
            patch=patch,
            changed_files=tuple(change.get("changed_files", [])),
            suggested_commands=tuple(verification.get("commands", [])),
            risks=tuple(verification.get("risks", [])),
            assumptions=tuple(verification.get("assumptions", [])),
        )


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0



@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float = 0.0
    cached_input_per_million: float = 0.0
    output_per_million: float = 0.0

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ModelPricing":
        return cls(**(value or {}))

    def estimate(self, usage: Usage) -> float:
        uncached = max(0, usage.input_tokens - usage.cached_input_tokens)
        return (
            uncached * self.input_per_million
            + usage.cached_input_tokens * self.cached_input_per_million
            + usage.output_tokens * self.output_per_million
        ) / 1_000_000


@dataclass(frozen=True)
class ModelResult:
    fix: ProposedFix
    usage: Usage = field(default_factory=Usage)
    request_id: str | None = None


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class RunResult:
    task_id: str
    status: str
    report_path: str
    patch_path: str
    worktree_path: str | None
    model_result: ModelResult
    validations: tuple[CommandResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
