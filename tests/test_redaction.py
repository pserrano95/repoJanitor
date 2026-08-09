import unittest
import tempfile
from pathlib import Path

from repojanitor.config import ProviderConfig, RepoConfig
from repojanitor.models import ModelPricing, TaskPacket
from repojanitor.prompting import build_prompt
from repojanitor.redaction import redact


class RedactionTests(unittest.TestCase):
    def test_redacts_common_credentials(self):
        source = "API_KEY=super-secret-value\nAuthorization: Bearer abcdefghijklmnop123456\n"
        clean, count = redact(source)
        self.assertNotIn("super-secret-value", clean)
        self.assertNotIn("abcdefghijklmnop123456", clean)
        self.assertGreaterEqual(count, 2)

    def test_preserves_normal_code(self):
        source = "def add(a, b):\n    return a + b\n"
        clean, count = redact(source)
        self.assertEqual(clean, source)
        self.assertEqual(count, 0)

    def test_redacts_task_evidence_before_building_prompt(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = RepoConfig(
                repo_path=root,
                artifact_dir=root / "runs",
                worktree_dir=root / "worktrees",
                provider=ProviderConfig(
                    adapter="openai_chat_completions",
                    name="mock",
                    model="mock",
                    base_url="https://example.test/v1",
                    api_key_env="MOCK_KEY",
                    pricing=ModelPricing(),
                ),
            )
            packet = TaskPacket(
                id="redaction-test",
                kind="ci_failure",
                title="Failure",
                evidence=("API_KEY=do-not-send-this",),
            )
            prompt, count = build_prompt(root, config, packet)
            self.assertNotIn("do-not-send-this", prompt)
            self.assertIn("[REDACTED]", prompt)
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
