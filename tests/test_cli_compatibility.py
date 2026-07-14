from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_verifier.py"
LIVE = os.environ.get("VERIFIED_DELIVERY_LIVE_TESTS") == "1"


class CliCompatibilityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("claude"), "claude CLI is not installed")
    def test_claude_help_exposes_required_read_only_flags(self) -> None:
        completed = subprocess.run(
            ["claude", "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        help_text = completed.stdout + completed.stderr
        for flag in (
            "--safe-mode",
            "--model",
            "--effort",
            "xhigh",
            "--permission-mode",
            "--tools",
            "--no-session-persistence",
            "--output-format",
        ):
            self.assertIn(flag, help_text)

    @unittest.skipUnless(shutil.which("codex"), "codex CLI is not installed")
    def test_codex_help_exposes_required_read_only_flags(self) -> None:
        completed = subprocess.run(
            ["codex", "exec", "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        help_text = completed.stdout + completed.stderr
        for flag in (
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--json",
            "--model",
            "--config",
        ):
            self.assertIn(flag, help_text)

    @unittest.skipUnless(LIVE, "set VERIFIED_DELIVERY_LIVE_TESTS=1; consumes credits")
    @unittest.skipUnless(shutil.which("claude"), "claude CLI is not installed")
    def test_live_codex_author_to_claude_gate(self) -> None:
        self.assert_live_gate(author="codex", expected_verifier="claude")

    @unittest.skipUnless(LIVE, "set VERIFIED_DELIVERY_LIVE_TESTS=1; consumes credits")
    @unittest.skipUnless(shutil.which("codex"), "codex CLI is not installed")
    def test_live_claude_author_to_codex_gate(self) -> None:
        self.assert_live_gate(author="claude-code", expected_verifier="codex")

    def assert_live_gate(self, author: str, expected_verifier: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "SSOT.md").write_text("# verified-delivery\n", encoding="utf-8")
            output = base / "result.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--author",
                    author,
                    "--verifier",
                    "auto",
                    "--gate",
                    "plan",
                    "--cwd",
                    str(base),
                    "--prompt",
                    "Verify that SSOT.md:1 names verified-delivery. Cite it and PASS if true.",
                    "--output",
                    str(output),
                    "--timeout",
                    "180",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=210,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["verifier"], expected_verifier)
            self.assertEqual(result["assurance"], "independent")
            self.assertIn("PASS", str(result["response"]).upper())
            self.assertTrue(result["actual_model"])


if __name__ == "__main__":
    unittest.main()
