# Roadmap

## 0.1 — Safe local engine

- [x] Provider- and model-neutral core contracts.
- [x] OpenAI-compatible Chat Completions adapter.
- [x] External provider adapter entry points.
- [x] Context allowlists and secret redaction.
- [x] Patch scope, size, traversal, symlink, binary, and submodule gates.
- [x] Detached worktree patch application.
- [x] Owner-defined validation commands without shell parsing.
- [x] Local report, patch, usage, and cost metadata.
- [x] Offline mock provider and cross-platform unit tests.

## 0.2 — GitHub Actions failure ingestion

- [x] Composite Action for an owner-declared CI command.
- [x] Normalize bounded, redacted logs into a task packet.
- [x] Verify event, repository, commit provenance, and fork trust before inference.
- [x] Remove provider credentials from the child check environment.
- [x] Publish a read-only job summary and downloadable repair artifact.
- [x] Preserve the original failing CI conclusion.
- [ ] Ingest completed or historical workflow runs through the GitHub API.
- [ ] Deduplicate repeated failures.
- [ ] Add bounded retry and backoff.

## 0.3 — Sandboxed repair loop

- [ ] Container and Windows sandbox runners.
- [ ] Gitleaks pre-inference scan.
- [x] Reproduce-before-repair contract with a clean detached worktree and failure-signature gate.
- [ ] Bounded iterative fixes after failed validation.
- [ ] Independent reviewer adapter and confidence policy.

## 0.4 — Draft pull requests

- [ ] Explicit opt-in publisher permissions.
- [ ] Draft PR creation without auto-merge.
- [ ] Evidence-rich PR template and provenance labels.
- [ ] Per-repository budgets, concurrency, and quiet hours.
- [ ] Human feedback capture without provider payload retention.

## 1.0 — Community release

- [ ] Stable task, provider, policy, and publisher plugin APIs.
- [ ] GitHub, GitLab, and Buildkite source plugins.
- [ ] Multiple provider adapter packages maintained by the community.
- [ ] Security audit and documented threat model.
- [ ] Evaluation corpus with provider-neutral quality metrics.
