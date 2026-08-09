import argparse
from contextlib import redirect_stdout
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from repojanitor.github_actions import (
    build_failure_packet,
    capture_command,
    failure_similarity,
    parse_command_json,
    verify_github_context,
)
from repojanitor.cli import run_ci


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class GitHubActionsTests(unittest.TestCase):
    def make_repo_and_env(self, root: Path, event: dict) -> tuple[Path, dict[str, str]]:
        repo = root / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")
        git(repo, "init")
        git(repo, "config", "user.email", "repojanitor@example.test")
        git(repo, "config", "user.name", "RepoJanitor Test")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "fixture")
        event_path = root / "event.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request" if "pull_request" in event else "push",
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_REPOSITORY": "owner/project",
            "GITHUB_SHA": git(repo, "rev-parse", "HEAD"),
            "GITHUB_WORKFLOW": "test",
            "GITHUB_JOB": "unit",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_SERVER_URL": "https://github.com",
        }
        return repo, env

    def test_command_requires_json_string_array(self):
        self.assertEqual(parse_command_json('["python", "-m", "unittest"]')[0], "python")
        with self.assertRaises(ValueError):
            parse_command_json("python -m unittest")
        with self.assertRaises(ValueError):
            parse_command_json('[]')

    def test_failure_similarity_ignores_volatile_numbers(self):
        original = (
            "/home/runner/work/project/tests/test_parser.py:18 "
            "FAILED test_blank in 0.12s: ValueError expected None"
        )
        reproduction = (
            "/tmp/repojanitor-worktrees/tests/test_parser.py:21 "
            "FAILED test_blank in 0.49s: ValueError expected None"
        )
        unrelated = "ModuleNotFoundError: no module named dependency"
        self.assertGreater(failure_similarity(original, reproduction), 0.8)
        self.assertLess(failure_similarity(original, unrelated), 0.5)

    def test_capture_is_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            script = "print('x' * 2000); print('API_KEY=super-secret-value')"
            with redirect_stdout(io.StringIO()):
                result = capture_command(
                    [sys.executable, "-c", script],
                    cwd=root,
                    log_path=root / "failure.log",
                    max_log_bytes=1024,
                    timeout_seconds=10,
                )
            log = result.log_path.read_text(encoding="utf-8")
            self.assertEqual(result.exit_code, 0)
            self.assertLessEqual(len(log.encode("utf-8")), 1024)
            self.assertNotIn("super-secret-value", log)
            self.assertIn("[REDACTED]", log)

    def test_capture_removes_provider_key_from_child_environment(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            previous = os.environ.get("REPOJANITOR_TEST_PROVIDER_KEY")
            os.environ["REPOJANITOR_TEST_PROVIDER_KEY"] = "must-not-reach-tests"
            try:
                script = (
                    "import os; "
                    "print(os.environ.get('REPOJANITOR_TEST_PROVIDER_KEY', 'missing'))"
                )
                with redirect_stdout(io.StringIO()):
                    result = capture_command(
                        [sys.executable, "-c", script],
                        cwd=root,
                        log_path=root / "capture.log",
                        timeout_seconds=10,
                        remove_env=("REPOJANITOR_TEST_PROVIDER_KEY",),
                    )
            finally:
                if previous is None:
                    os.environ.pop("REPOJANITOR_TEST_PROVIDER_KEY", None)
                else:
                    os.environ["REPOJANITOR_TEST_PROVIDER_KEY"] = previous
            self.assertEqual(result.log_path.read_text(encoding="utf-8").strip(), "missing")

    def test_accepts_matching_non_fork_checkout(self):
        with tempfile.TemporaryDirectory() as raw:
            event = {
                "repository": {"full_name": "owner/project"},
                "pull_request": {
                    "head": {"repo": {"full_name": "owner/project"}},
                    "base": {"repo": {"full_name": "owner/project"}},
                },
            }
            repo, env = self.make_repo_and_env(Path(raw), event)
            context = verify_github_context(repo, env=env)
            self.assertEqual(context.repository, "owner/project")
            self.assertEqual(context.run_url, "https://github.com/owner/project/actions/runs/123")

    def test_rejects_fork_by_default(self):
        with tempfile.TemporaryDirectory() as raw:
            event = {
                "repository": {"full_name": "owner/project"},
                "pull_request": {
                    "head": {"repo": {"full_name": "contributor/project"}},
                    "base": {"repo": {"full_name": "owner/project"}},
                },
            }
            repo, env = self.make_repo_and_env(Path(raw), event)
            with self.assertRaisesRegex(RuntimeError, "Fork pull requests"):
                verify_github_context(repo, env=env)

    def test_rejects_pull_request_target(self):
        with tempfile.TemporaryDirectory() as raw:
            event = {"repository": {"full_name": "owner/project"}}
            repo, env = self.make_repo_and_env(Path(raw), event)
            env["GITHUB_EVENT_NAME"] = "pull_request_target"
            with self.assertRaisesRegex(RuntimeError, "not trusted"):
                verify_github_context(repo, env=env)

    def test_builds_normalized_packet_from_redacted_log(self):
        with tempfile.TemporaryDirectory() as raw:
            event = {"repository": {"full_name": "owner/project"}}
            root = Path(raw)
            repo, env = self.make_repo_and_env(root, event)
            context = verify_github_context(repo, env=env)
            log = root / "failure.log"
            log.write_text("AssertionError: expected 2, got 3\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                capture = capture_command(
                    [sys.executable, "-c", "raise SystemExit(7)"],
                    cwd=repo,
                    log_path=log,
                    timeout_seconds=10,
                )
            packet = build_failure_packet(
                capture,
                context,
                title="Unit tests failed",
                context_files=("app.py",),
                allowed_paths=("app.py",),
            )
            self.assertEqual(packet.kind, "github_actions_failure")
            self.assertEqual(packet.base_ref, env["GITHUB_SHA"])
            self.assertIn("Exit code: 7", "\n".join(packet.evidence))

    def test_ci_failure_produces_review_artifacts_and_stays_failed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            event = {"repository": {"full_name": "owner/project"}}
            repo, env = self.make_repo_and_env(root, event)
            config_path = repo / "repojanitor.json"
            config_path.write_text(
                json.dumps(
                    {
                        "repo_path": ".",
                        "artifact_dir": ".repojanitor/runs",
                        "worktree_dir": str(root / "worktrees"),
                        "provider": {
                            "adapter": "openai_chat_completions",
                            "name": "mock",
                            "model": "mock-model",
                            "base_url": "https://example.test/v1",
                            "api_key_env": "MOCK_PROVIDER_KEY",
                        },
                        "allowed_paths": ["app.py"],
                    }
                ),
                encoding="utf-8",
            )
            response_path = root / "response.json"
            response_path.write_text(
                json.dumps(
                    {
                        "diagnosis": {
                            "summary": "The fixture fails.",
                            "root_cause": "The expected output is missing.",
                            "confidence": 0.9,
                        },
                        "proposed_change": {
                            "summary": "Update the fixture output.",
                            "patch": (
                                "diff --git a/app.py b/app.py\n"
                                "--- a/app.py\n"
                                "+++ b/app.py\n"
                                "@@ -1 +1 @@\n"
                                "-print('hello')\n"
                                "+print('fixed')\n"
                            ),
                            "changed_files": ["app.py"],
                        },
                        "verification": {"commands": [], "risks": [], "assumptions": []},
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                config=str(config_path),
                command_json=json.dumps([sys.executable, "-c", "raise SystemExit(9)"]),
                title="Fixture failed",
                context_files="app.py",
                allowed_paths="app.py",
                forbidden_paths="",
                acceptance="The fixture passes.",
                task_id=None,
                max_log_bytes=4096,
                allow_fork=False,
                apply=False,
                mock_response=str(response_path),
            )
            with patch.dict(os.environ, env, clear=False), redirect_stdout(io.StringIO()):
                exit_code = run_ci(args)
            run_dir = repo / ".repojanitor" / "runs" / "gh-123-2-unit"
            self.assertEqual(exit_code, 1)
            self.assertTrue((run_dir / "ci.log").is_file())
            self.assertTrue((run_dir / "packet.json").is_file())
            self.assertTrue((run_dir / "report.md").is_file())
            self.assertTrue((run_dir / "proposed.patch").is_file())
            reproduction = json.loads(
                (run_dir / "reproduction.json").read_text(encoding="utf-8")
            )
            self.assertEqual(reproduction["status"], "REPRODUCED")
            metadata = json.loads(
                (run_dir / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata["provider_called"])

    def test_ci_skips_model_when_failure_does_not_reproduce(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            event = {"repository": {"full_name": "owner/project"}}
            repo, env = self.make_repo_and_env(root, event)
            config_path = repo / "repojanitor.json"
            config_path.write_text(
                json.dumps(
                    {
                        "repo_path": ".",
                        "artifact_dir": ".repojanitor/runs",
                        "worktree_dir": str(root / "worktrees"),
                        "provider": {
                            "adapter": "openai_chat_completions",
                            "name": "mock",
                            "model": "must-not-run",
                            "base_url": "https://example.test/v1",
                            "api_key_env": "MOCK_PROVIDER_KEY",
                        },
                        "allowed_paths": ["app.py"],
                    }
                ),
                encoding="utf-8",
            )
            marker = root / "transient.marker"
            script = (
                "from pathlib import Path; import sys; "
                f"p=Path({str(marker)!r}); seen=p.exists(); "
                "p.write_text('seen'); raise SystemExit(0 if seen else 9)"
            )
            output_path = root / "github-output.txt"
            summary_path = root / "summary.md"
            env["GITHUB_OUTPUT"] = str(output_path)
            env["GITHUB_STEP_SUMMARY"] = str(summary_path)
            args = argparse.Namespace(
                config=str(config_path),
                command_json=json.dumps([sys.executable, "-c", script]),
                title="Transient fixture failed",
                context_files="app.py",
                allowed_paths="app.py",
                forbidden_paths="",
                acceptance="The fixture passes.",
                task_id=None,
                max_log_bytes=4096,
                allow_fork=False,
                apply=False,
                mock_response=str(root / "must-not-be-read.json"),
                skip_reproduction=False,
            )

            with patch.dict(os.environ, env, clear=False), redirect_stdout(io.StringIO()):
                exit_code = run_ci(args)

            run_dir = repo / ".repojanitor" / "runs" / "gh-123-2-unit"
            metadata = json.loads(
                (run_dir / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(metadata["status"], "NOT_REPRODUCIBLE")
            self.assertFalse(metadata["provider_called"])
            self.assertEqual(metadata["estimated_cost_usd"], 0.0)
            self.assertTrue((run_dir / "reproduction.log").is_file())
            self.assertFalse((run_dir / "proposed.patch").exists())
            self.assertIn("status=NOT_REPRODUCIBLE", output_path.read_text())


if __name__ == "__main__":
    unittest.main()
