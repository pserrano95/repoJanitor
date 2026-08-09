# Security policy

## Supported versions

Until the first stable release, security fixes apply to the latest commit on the default branch.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, private repository content, or provider payloads. Contact the maintainers privately through the security-reporting channel configured in the GitHub repository. The public repository should enable GitHub Private Vulnerability Reporting before launch.

Include the affected version, reproduction steps, impact, and any suggested mitigation. Remove all real secrets and customer data.

## Threat model

RepoJanitor assumes all repository contents, CI logs, issue text, model output, and patches are untrusted. Its principal boundaries are:

- explicit context and patch path allowlists;
- traversal and denied-path rejection;
- redaction before provider calls;
- no shell interpretation for validation commands;
- no execution of commands proposed by a model;
- isolated detached worktrees;
- no commits, pushes, pull requests, or merges in the MVP;
- provider retention and telemetry controlled outside the model prompt.

Redaction is defense in depth and does not replace a dedicated secret scanner. Validation commands are trusted repository-owner configuration and should run inside an OS/container sandbox for untrusted repositories.

