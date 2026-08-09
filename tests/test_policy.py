import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from repojanitor.config import ProviderConfig, RepoConfig
from repojanitor.models import ModelPricing, TaskLimits, TaskPacket
from repojanitor.policy import PolicyViolation, validate_patch


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.config = RepoConfig(
            repo_path=base,
            artifact_dir=base / "runs",
            worktree_dir=base / "worktrees",
            provider=ProviderConfig(
                adapter="openai_chat_completions",
                name="test",
                model="test-model",
                base_url="https://example.test/v1",
                api_key_env="TEST_API_KEY",
                pricing=ModelPricing(),
            ),
            allowed_paths=("src/**", "tests/**"),
        )
        self.packet = TaskPacket(
            id="task",
            kind="failing_test",
            title="Test",
            allowed_paths=("src/**",),
            limits=TaskLimits(max_changed_files=2, max_diff_lines=20),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_patch_inside_allowlist(self):
        patch = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-old
+new
"""
        self.assertEqual(validate_patch(patch, self.config, self.packet), ("src/a.py",))

    def test_rejects_patch_outside_task_scope(self):
        patch = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
-old
+new
"""
        with self.assertRaises(PolicyViolation):
            validate_patch(patch, self.config, self.packet)

    def test_rejects_traversal(self):
        patch = """diff --git a/../outside.py b/../outside.py
--- a/../outside.py
+++ b/../outside.py
@@ -1 +1 @@
-old
+new
"""
        with self.assertRaises(PolicyViolation):
            validate_patch(patch, self.config, self.packet)

    def test_rejects_symlinks(self):
        patch = """diff --git a/src/link b/src/link
new file mode 120000
--- /dev/null
+++ b/src/link
@@ -0,0 +1 @@
+../../outside
"""
        with self.assertRaises(PolicyViolation):
            validate_patch(patch, self.config, self.packet)

    def test_path_matching_is_case_insensitive_for_cross_platform_safety(self):
        packet = TaskPacket(
            id="task-env",
            kind="test",
            title="Secret",
            allowed_paths=("**",),
        )
        patch = """diff --git a/.ENV b/.ENV
--- a/.ENV
+++ b/.ENV
@@ -1 +1 @@
-TOKEN=old
+TOKEN=new
"""
        with self.assertRaises(PolicyViolation):
            validate_patch(patch, replace(self.config, allowed_paths=("**",)), packet)


if __name__ == "__main__":
    unittest.main()
