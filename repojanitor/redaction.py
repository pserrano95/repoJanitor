from __future__ import annotations

import re


REDACTION_RULES = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\b(?:ghp|github_pat|sk|fw)_[A-Za-z0-9_-]{16,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"), "Bearer [REDACTED]"),
    (
        re.compile(r"(?im)^(\s*(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*)[^\s#]+"),
        r"\1[REDACTED]",
    ),
)


def redact(text: str) -> tuple[str, int]:
    total = 0
    for pattern, replacement in REDACTION_RULES:
        text, count = pattern.subn(replacement, text)
        total += count
    return text, total

