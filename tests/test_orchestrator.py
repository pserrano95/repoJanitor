import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from repojanitor.config import ProviderConfig, RepoConfig
from repojanitor.models import ModelPricing, TaskLimits, TaskPacket
from repojanitor.orchestrator import RepoJanitor
from repojanitor.provider import FileProvider


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


class OrchestratorTests(unittest.TestCase):
    def test_applies_and_validates_patch_in_detached_worktree(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = base / "demo"
            repo.mkdir()
            (repo / "src").mkdir()
            (repo / "tests").mkdir()
            (repo / "src" / "parser.py").write_text(
                "def parse_value(value):\n    return value\n", encoding="utf-8"
            )
            (repo / "tests" / "test_parser.py").write_text(
                """import unittest
from src.parser import parse_value

class ParserTest(unittest.TestCase):
    def test_blank(self):
        self.assertIsNone(parse_value(""))
""",
                encoding="utf-8",
            )
            git(repo, "init")
            git(repo, "config", "user.email", "repojanitor@example.test")
            git(repo, "config", "user.name", "RepoJanitor Test")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "fixture")

            response_path = base / "response.json"
            response_path.write_text(
                json.dumps(
                    {
                        "diagnosis": {
                            "summary": "Blank input is returned unchanged.",
                            "root_cause": "Missing normalization.",
                            "confidence": 0.95,
                        },
                        "proposed_change": {
                            "summary": "Normalize blank strings.",
                            "patch": (
                                "diff --git a/src/parser.py b/src/parser.py\n"
                                "--- a/src/parser.py\n"
                                "+++ b/src/parser.py\n"
                                "@@ -1,2 +1,4 @@\n"
                                " def parse_value(value):\n"
                                "+    if value == \"\":\n"
                                "+        return None\n"
                                "     return value\n"
                            ),
                            "changed_files": ["src/parser.py"],
                        },
                        "verification": {
                            "commands": ["untrusted model command"],
                            "risks": [],
                            "assumptions": [],
                        },
                        "_usage": {
                            "input_tokens": 1000,
                            "cached_input_tokens": 500,
                            "output_tokens": 200,
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = RepoConfig(
                repo_path=repo,
                artifact_dir=base / "artifacts",
                worktree_dir=base / "worktrees",
                provider=ProviderConfig(
                    adapter="openai_chat_completions",
                    name="mock",
                    model="mock-model",
                    base_url="https://example.test/v1",
                    api_key_env="MOCK_API_KEY",
                    pricing=ModelPricing(
                        input_per_million=0.14,
                        cached_input_per_million=0.028,
                        output_per_million=0.28,
                    ),
                ),
                allowed_paths=("src/**", "tests/**"),
                validation_commands=(("python", "-m", "unittest", "discover", "-s", "tests", "-v"),),
            )
            packet = TaskPacket(
                id="parser-fix",
                kind="failing_test",
                title="Fix blank parsing",
                context_files=("src/parser.py", "tests/test_parser.py"),
                allowed_paths=("src/parser.py", "tests/test_parser.py"),
                limits=TaskLimits(max_cost_usd=1.0),
            )

            result = RepoJanitor(config, FileProvider(response_path)).run(packet, apply=True)

            self.assertEqual(result.status, "VALIDATED")
            self.assertTrue(all(item.passed for item in result.validations))
            self.assertIn("return None", (Path(result.worktree_path) / "src" / "parser.py").read_text())
            self.assertTrue(Path(result.report_path).is_file())
            report = Path(result.report_path).read_text(encoding="utf-8")
            self.assertIn("Only commands configured", report)
            self.assertNotIn("untrusted model command`", report)

    def test_rejected_patch_still_produces_auditable_artifacts(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = base / "demo"
            repo.mkdir()
            (repo / "src").mkdir()
            (repo / "src" / "parser.py").write_text(
                "def parse_value(value):\n    return value\n", encoding="utf-8"
            )
            git(repo, "init")
            git(repo, "config", "user.email", "repojanitor@example.test")
            git(repo, "config", "user.name", "RepoJanitor Test")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "fixture")

            response_path = base / "response.json"
            response_path.write_text(
                json.dumps(
                    {
                        "diagnosis": {
                            "summary": "Blank input is returned unchanged.",
                            "root_cause": "Missing normalization.",
                            "confidence": 0.95,
                        },
                        "proposed_change": {
                            "summary": "Normalize blank strings.",
                            "patch": (
                                "diff --git a/src/parser.py b/src/parser.py\n"
                                "--- a/src/parser.py\n"
                                "+++ b/src/parser.py\n"
                                "@@ -1,2 +1,4 @@\n"
                                " def parse_different_name(value):\n"
                                "+    if value == \"\":\n"
                                "+        return None\n"
                                "     return value\n"
                            ),
                            "changed_files": ["src/parser.py"],
                        },
                        "verification": {
                            "commands": [],
                            "risks": [],
                            "assumptions": [],
                        },
                        "_usage": {"input_tokens": 10, "output_tokens": 10},
                    }
                ),
                encoding="utf-8",
            )
            config = RepoConfig(
                repo_path=repo,
                artifact_dir=base / "artifacts",
                worktree_dir=base / "worktrees",
                provider=ProviderConfig(
                    adapter="openai_chat_completions",
                    name="mock",
                    model="mock-model",
                    base_url="https://example.test/v1",
                    api_key_env="MOCK_API_KEY",
                ),
                allowed_paths=("src/**",),
                validation_commands=(("python", "-c", "raise SystemExit(99)"),),
            )
            packet = TaskPacket(
                id="rejected-patch",
                kind="failing_test",
                title="Fix blank parsing",
                context_files=("src/parser.py",),
                allowed_paths=("src/parser.py",),
                limits=TaskLimits(max_cost_usd=1.0),
            )

            result = RepoJanitor(config, FileProvider(response_path)).run(packet, apply=True)

            self.assertEqual(result.status, "PATCH_REJECTED")
            self.assertEqual(result.validations, ())
            self.assertTrue(Path(result.patch_path).is_file())
            metadata = json.loads(
                (Path(result.report_path).parent / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["status"], "PATCH_REJECTED")
            self.assertIn("patch does not apply", metadata["application_error"])


if __name__ == "__main__":
    unittest.main()
