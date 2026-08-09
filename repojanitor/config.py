from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ModelPricing


DEFAULT_DENIED_PATHS = (
    ".git/**",
    ".env",
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/*secret*",
    "**/credentials*",
)


@dataclass(frozen=True)
class ProviderConfig:
    adapter: str
    name: str
    model: str
    base_url: str
    api_key_env: str
    structured_output: str = "json_schema"
    request_options: dict[str, Any] = field(default_factory=dict)
    pricing: ModelPricing = field(default_factory=ModelPricing)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ProviderConfig":
        if not value:
            raise ValueError("Configuration requires a provider section")
        required = ["adapter", "name", "model", "base_url", "api_key_env"]
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise ValueError(f"Provider config is missing: {', '.join(missing)}")
        return cls(
            adapter=str(value["adapter"]),
            name=str(value["name"]),
            model=str(value["model"]),
            base_url=str(value["base_url"]),
            api_key_env=str(value["api_key_env"]),
            structured_output=str(value.get("structured_output", "json_schema")),
            request_options=dict(value.get("request_options", {})),
            pricing=ModelPricing.from_dict(value.get("pricing")),
        )


@dataclass(frozen=True)
class RepoConfig:
    repo_path: Path
    artifact_dir: Path
    worktree_dir: Path
    provider: ProviderConfig
    allowed_paths: tuple[str, ...] = ("**",)
    denied_paths: tuple[str, ...] = DEFAULT_DENIED_PATHS
    validation_commands: tuple[tuple[str, ...], ...] = ()
    command_timeout_seconds: int = 600

    @classmethod
    def from_dict(cls, value: dict[str, Any], config_path: Path) -> "RepoConfig":
        base = config_path.parent.resolve()

        def resolve_path(raw: str, default: str) -> Path:
            candidate = Path(raw or default)
            return (base / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()

        commands = tuple(tuple(str(part) for part in command) for command in value.get("validation_commands", []))
        return cls(
            repo_path=resolve_path(str(value.get("repo_path", ".")), "."),
            artifact_dir=resolve_path(str(value.get("artifact_dir", ".repojanitor/runs")), ".repojanitor/runs"),
            worktree_dir=resolve_path(str(value.get("worktree_dir", ".repojanitor/worktrees")), ".repojanitor/worktrees"),
            provider=ProviderConfig.from_dict(value.get("provider")),
            allowed_paths=tuple(value.get("allowed_paths", ["**"])),
            denied_paths=tuple(value.get("denied_paths", DEFAULT_DENIED_PATHS)),
            validation_commands=commands,
            command_timeout_seconds=int(value.get("command_timeout_seconds", 600)),
        )


def load_config(path: str | Path) -> RepoConfig:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        return RepoConfig.from_dict(json.load(handle), config_path)
