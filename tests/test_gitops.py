import subprocess
import tempfile
import unittest
from pathlib import Path

from repojanitor.gitops import apply_patch


class GitOpsTests(unittest.TestCase):
    def test_apply_patch_recounts_model_hunk_lengths(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "demo"
            repo.mkdir()
            source = repo / "parser.py"
            source.write_text("def parse(value):\n    return int(value)\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)

            patch = (
                "diff --git a/parser.py b/parser.py\n"
                "--- a/parser.py\n"
                "+++ b/parser.py\n"
                "@@ -1,20 +1,22 @@\n"
                " def parse(value):\n"
                "+    if value == \"\":\n"
                "+        return None\n"
                "     return int(value)\n"
            )

            apply_patch(repo, patch)

            self.assertIn("return None", source.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
