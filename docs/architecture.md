# Architecture

RepoJanitor separates model-dependent inference from model-independent policy and execution.

```text
Task packet + repository policy
             |
             v
      Context collector ----> Redactor
             |                    |
             +--------------------+
                         |
                         v
                 Provider adapter
                         |
                   ProposedFix JSON
                         |
                         v
                  Patch policy gate
                         |
                         v
                Detached Git worktree
                         |
                         v
             Owner-defined validations
                         |
                         v
               Local report + metadata
```

The GitHub Actions adapter sits before the task packet. It verifies workflow provenance, executes a trusted argument-array command, and converts only a bounded redacted log tail into normalized evidence. It has no provider-specific behavior.

```text
GitHub event + checked-out commit
              |
       Provenance/fork gate
              |
       Owner-declared command
              |
       Bounded log redactor
              |
              v
          TaskPacket  ----> provider-neutral core
```

## Core contracts

- `TaskPacket` describes evidence, acceptance criteria, context files, scope, and limits.
- `Provider` converts a normalized prompt into `ModelResult`.
- `ProposedFix` contains diagnosis, unified diff, declared paths, risks, and assumptions.
- `RepoConfig` owns repository policy, validation commands, provider selection, and pricing.
- `RepoJanitor` composes the flow without provider-specific behavior.
- `GitHubContext` and `CapturedCommand` normalize CI provenance and evidence without leaking GitHub semantics into the model adapter.

## Built-in adapter

`openai_chat_completions` works with providers implementing the OpenAI Chat Completions shape. Endpoint, API-key environment variable, model, structured-output mode, arbitrary request options, and token pricing are configuration.

Supported structured-output strategies:

- `json_schema`: strictest option when implemented by the provider.
- `json_object`: valid JSON without schema enforcement.
- `prompt_only`: for compatible APIs that reject `response_format`.

## External adapters

Third-party packages register factories in the `repojanitor.providers` entry-point group. This keeps provider SDKs and compatibility work outside core. An adapter may use Anthropic Messages, a local model server, a subprocess, or another transport, but it must return the normalized core contract.

## Trust boundaries

The provider never receives filesystem or process authority. It sees only context approved and redacted by core. Its patch is inert text until the policy gate accepts it. Validation commands come exclusively from trusted repository configuration and bypass shell parsing.

The GitHub Action also treats workflow metadata and logs as untrusted. It rejects `pull_request_target`, unsupported events, repository or SHA mismatches, and forks unless explicitly allowed. The failing command is invoked without a shell and without the configured provider API key in its environment. The Action needs only `contents: read`; it writes a job summary and artifact but cannot commit or modify the repository.

## Future modules

- CI-source adapters: GitHub Actions, GitLab CI, Buildkite, Jenkins.
- Publishers: GitHub Checks and draft PRs.
- Sandboxes: Docker, gVisor, Firecracker, Windows Sandbox.
- Secret scanners: Gitleaks and provider-independent redaction plugins.
- Schedulers and durable queues.
- Iterative repair with bounded attempts and independent review.
