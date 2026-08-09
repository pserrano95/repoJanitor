# RepoJanitor MVP

RepoJanitor is a provider- and model-agnostic, policy-first CI failure fixer. It reads only explicitly approved repository files, removes common credentials, asks a configured model for a structured diagnosis and unified diff, validates the diff against repository policy, and can apply it in a detached Git worktree before running owner-defined checks.

This MVP never commits, pushes, opens a pull request, merges, or executes commands proposed by the model.

The built-in adapter works with OpenAI-compatible Chat Completions APIs. Fireworks AI with DeepSeek V4 Flash is the included example preset, not a core dependency. Other API shapes can be added through Python entry-point plugins.

## Implemented verticals

The local engine handles one normalized CI failure packet:

1. Load repository policy and task packet.
2. Verify all context paths against repository and task allowlists.
3. Redact common credentials before inference.
4. Call the selected provider adapter and model.
5. Require a JSON-schema-constrained response containing a unified diff.
6. Reject patches that escape scope or exceed file, diff, context, output, or cost limits.
7. Optionally create a detached worktree and apply the patch.
8. Run only validation commands declared by the repository owner.
9. Write a Markdown report, patch, and metadata without persisting the full prompt or response.

Version 0.2 adds a GitHub composite Action that:

1. Verifies the event, repository, checked-out commit, and fork trust before inference.
2. Executes one repository-owner-declared command from a JSON argument array without a shell.
3. Removes the provider API key from the child command environment.
4. Retains only a bounded, redacted log tail.
5. Calls the same provider-neutral engine only when the command fails.
6. Writes the diagnosis into the GitHub job summary and uploads the report and patch as an artifact.
7. Preserves the original non-zero result, so an advisory repair never turns a failing build green.

Version 0.3 adds a reproduce-before-repair gate that:

1. Re-runs the same owner-declared command from the verified commit in a clean detached worktree.
2. Removes the provider credential from both the original command and its reproduction.
3. Compares exit codes and normalized failure signatures before inference.
4. Skips the provider with zero model cost when the failure disappears, changes, or times out.
5. Stores `reproduction.log` and `reproduction.json` alongside the normal evidence.

This isolates repository state but is not an operating-system or network sandbox.

## Requirements

- Python 3.11+
- Git
- An API key for the provider selected in configuration

## Installation

```powershell
cd C:\path\to\repojanitor-mvp
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[openai]"
```

Set provider credentials only in the process environment; do not put them in repository configuration. For the included Fireworks preset:

```powershell
$env:FIREWORKS_API_KEY="your-key"
```

## Configure a repository

Copy `examples/repojanitor.json` to a location of your choice and update:

- `repo_path`: repository to maintain.
- `artifact_dir`: local reports and patches.
- `worktree_dir`: preferably outside the primary working tree.
- `allowed_paths` and `denied_paths`: repository-wide boundaries.
- `validation_commands`: arrays of executable and arguments. Strings are deliberately not passed through a shell.
- `reproduction_similarity_threshold`: minimum normalized failure-signature overlap, from `0.0` to `1.0`; the default is `0.5`.
- `provider`: adapter, endpoint, model, credential variable, request options, and pricing.

The included provider section is entirely declarative:

```json
{
  "provider": {
    "adapter": "openai_chat_completions",
    "name": "fireworks",
    "model": "accounts/fireworks/models/deepseek-v4-flash",
    "base_url": "https://api.fireworks.ai/inference/v1",
    "api_key_env": "FIREWORKS_API_KEY",
    "structured_output": "json_schema",
    "request_options": {
      "reasoning_effort": "high"
    },
    "pricing": {
      "input_per_million": 0.14,
      "cached_input_per_million": 0.028,
      "output_per_million": 0.28
    }
  }
}
```

Change those values for another compatible host or model. Use `json_object` or `prompt_only` when a provider does not implement strict JSON Schema. See [the architecture guide](docs/architecture.md) to publish an adapter for a different API protocol.

Example validation commands:

```json
{
  "validation_commands": [
    ["python", "-m", "pytest", "-q"],
    ["python", "-m", "mypy", "src"]
  ]
}
```

Create a task packet following `examples/ci-failure.json`. Keep `context_files` minimal and make the task allowlist narrower than the repository allowlist.

## Check the environment

```powershell
repojanitor doctor --config .\repojanitor.json
```

An absent API key is a warning so mock runs remain possible. A missing Git executable or invalid repository fails the check.

## Safe analysis-only run

This calls the configured provider but does not create a worktree or apply the proposed patch:

```powershell
repojanitor run `
  --config .\repojanitor.json `
  --packet .\ci-failure.json
```

## Apply and validate in an isolated worktree

```powershell
repojanitor run `
  --config .\repojanitor.json `
  --packet .\ci-failure.json `
  --apply
```

The resulting worktree is deliberately left in place for human inspection. No branch, commit, push, PR, or merge is created.

## Offline smoke test

The included mock response exercises the orchestration without an API key:

```powershell
repojanitor run `
  --config .\examples\repojanitor.json `
  --packet .\examples\ci-failure.json `
  --mock-response .\examples\mock-response.json
```

The example expects a repository at `examples/../demo-repo`; customize the path before running it.

## GitHub Actions vertical

Copy `examples/github-repojanitor.json` and adjust its context policy and validation commands. Then replace your normal test step with the composite Action:

```yaml
permissions:
  contents: read

steps:
  - uses: actions/checkout@v7
  - uses: actions/setup-python@v7
    with:
      python-version: "3.11"
  - name: Test and propose a repair on failure
    uses: pserrano95/repoJanitor@v0.3.0
    with:
      config: examples/github-repojanitor.json
      command-json: '["python", "-m", "unittest", "discover", "-s", "tests", "-v"]'
      context-files: |
        repojanitor/orchestrator.py
        repojanitor/policy.py
        tests/test_orchestrator.py
        tests/test_policy.py
      allowed-paths: |
        repojanitor/**
        tests/**
      acceptance: |
        The failing test passes.
        Existing tests remain green.
      apply: "true"
    env:
      FIREWORKS_API_KEY: ${{ secrets.FIREWORKS_API_KEY }}
```

The Action installs RepoJanitor, runs the declared command, and does nothing model-related when it succeeds. On failure it reproduces the command from the verified commit before inference. The default `reproduce-before-repair: "true"` input can be disabled explicitly for compatibility, though keeping the gate enabled is recommended. Evidence includes `ci.log`, `reproduction.log`, `reproduction.json`, `packet.json`, `report.md`, `proposed.patch`, and `metadata.json` when applicable; the generated run directory is uploaded for human review. Pin a release tag or full commit SHA in production workflows.

Inference is denied for `pull_request_target`, unsupported events, mismatched checkouts, and fork pull requests by default. The optional `allow-fork` input is an explicit trust decision and should not be combined with privileged secrets.

## Provider privacy posture

RepoJanitor core does not request provider-side persistence and avoids storing full prompts and responses locally. Retention, training, tracing, region, subprocessors, and caching behavior still depend on the configured provider and account. Audit those settings before sending private code.

For the Fireworks example, the MVP uses Chat Completions rather than Responses API, and does not enable Fireworks Tracing or FireOptimizer. If strict US residency is required, use an on-demand or enterprise deployment pinned to the `US` multi-region and verify the applicable contract.

## Security boundaries

- Repository content is marked as untrusted data in the model prompt.
- Context files must be explicitly listed and pass both policy layers.
- Common token, key, password, bearer-token, AWS-key, and private-key patterns are redacted.
- Patch paths are parsed independently from the model's declared file list; both must agree.
- Traversal, denied paths, excess files, and oversized diffs are rejected.
- The model's suggested commands are recorded neither as authority nor execution input.
- Validation commands use direct process invocation with no shell expansion.
- Model cost is estimated from provider usage and configured pricing before any patch is applied.
- Provider inference is gated on a matching clean-worktree reproduction; transient or materially different failures produce an artifact with zero model cost.

Redaction is defense in depth, not a secret scanner. Production use should add a dedicated scanner such as Gitleaks before inference and configure network and filesystem sandboxing around validation commands.

## Run tests

The test suite uses only the standard library and Git:

```powershell
python -m unittest discover -s tests -v
```

It covers credential redaction, patch path policy, traversal rejection, worktree isolation, patch application, and execution of owner-controlled validation commands.

## Not yet implemented

- Webhook and completed-workflow ingestion outside the current job.
- Downloading logs from arbitrary historical workflow runs.
- Iterative repair after validation failure.
- Standalone GitHub Checks, issues, or draft pull requests.
- Durable job queue and concurrency control.
- Dedicated US deployment provisioning.
- Gitleaks integration and operating-system/container sandboxing.
- Production observability without payload retention.

## Open-source project

RepoJanitor is released under the MIT License. See `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and the GitHub templates before contributing. The repository CI matrix exercises Python 3.11 and 3.13 on Linux and Windows.

The next hardening vertical should add a dedicated secret scanner before inference and a true container/runner sandbox around command execution.
