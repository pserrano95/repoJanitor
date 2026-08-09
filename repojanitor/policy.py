from __future__ import annotations

import fnmatch
import re
from pathlib import Path, PurePosixPath

from .config import RepoConfig
from .models import TaskPacket


DIFF_PATH_RE = re.compile(r"^(?:---|\+\+\+)\s+(?:a/|b/)?(.+)$")


class PolicyViolation(RuntimeError):
    pass


def normalize_relative_path(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise PolicyViolation(f"Unsafe path: {path}")
    return normalized.as_posix()


def matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    folded = path.casefold()
    return any(fnmatch.fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


def ensure_path_allowed(path: str, config: RepoConfig, packet: TaskPacket) -> str:
    normalized = normalize_relative_path(path)
    if not matches_any(normalized, config.allowed_paths):
        raise PolicyViolation(f"Path is outside repository allowlist: {normalized}")
    if not matches_any(normalized, packet.allowed_paths):
        raise PolicyViolation(f"Path is outside task allowlist: {normalized}")
    denied = config.denied_paths + packet.forbidden_paths
    if matches_any(normalized, denied):
        raise PolicyViolation(f"Path is denied by policy: {normalized}")
    return normalized


def resolve_repo_file(repo: Path, path: str, config: RepoConfig, packet: TaskPacket) -> Path:
    normalized = ensure_path_allowed(path, config, packet)
    resolved = (repo / normalized).resolve()
    try:
        resolved.relative_to(repo.resolve())
    except ValueError as exc:
        raise PolicyViolation(f"Path escapes repository: {path}") from exc
    return resolved


def patch_paths(patch: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in patch.splitlines():
        match = DIFF_PATH_RE.match(line)
        if not match:
            continue
        raw = match.group(1).strip()
        if raw == "/dev/null":
            continue
        normalized = normalize_relative_path(raw)
        if normalized not in paths:
            paths.append(normalized)
    return tuple(paths)


def validate_patch(patch: str, config: RepoConfig, packet: TaskPacket) -> tuple[str, ...]:
    unsupported = {
        "GIT binary patch": "binary patches",
        "new file mode 120000": "symbolic links",
        "new file mode 160000": "gitlinks/submodules",
    }
    for marker, label in unsupported.items():
        if marker in patch:
            raise PolicyViolation(f"Patch contains unsupported {label}")
    paths = patch_paths(patch)
    if not paths:
        raise PolicyViolation("Patch contains no recognizable file paths")
    for path in paths:
        ensure_path_allowed(path, config, packet)
    if len(paths) > packet.limits.max_changed_files:
        raise PolicyViolation(
            f"Patch changes {len(paths)} files; limit is {packet.limits.max_changed_files}"
        )
    changed_lines = sum(
        1
        for line in patch.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++")
        and not line.startswith("---")
    )
    if changed_lines > packet.limits.max_diff_lines:
        raise PolicyViolation(
            f"Patch changes {changed_lines} lines; limit is {packet.limits.max_diff_lines}"
        )
    return paths
