# Contributing to RepoJanitor

RepoJanitor welcomes focused contributions that preserve its policy-first security model.

## Development setup

```bash
python -m venv .venv
python -m pip install -e ".[openai]"
python -m unittest discover -s tests -v
```

## Pull requests

1. Open an issue for substantial behavior or public-interface changes.
2. Keep each pull request limited to one concern.
3. Add tests for changed behavior, especially policy enforcement and path handling.
4. Do not weaken a security boundary to improve provider compatibility.
5. Update documentation and examples with public configuration changes.
6. Never add real API keys, repository contents, prompts, or model responses to fixtures.

## Provider adapters

External packages can expose an adapter without changing RepoJanitor core. Publish an entry point in the adapter package:

```toml
[project.entry-points."repojanitor.providers"]
anthropic_messages = "repojanitor_anthropic:create_provider"
```

The factory receives a `ProviderConfig` and returns an object implementing:

```python
def propose_fix(packet: TaskPacket, prompt: str) -> ModelResult:
    ...
```

Adapters must return the normalized `ProposedFix` contract. They must not execute model-suggested commands or apply patches themselves.

## Security-sensitive changes

Changes to path normalization, worktree creation, patch parsing, redaction, process execution, provider payload retention, or secret handling require explicit regression tests. See `SECURITY.md` for private reporting.
