from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_verifier.py"


FAKE_CLI = r"""#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

provider = Path(sys.argv[0]).name
record = {
    "provider": provider,
    "argv": sys.argv[1:],
    "stdin": sys.stdin.read(),
    "has_claudecode": "CLAUDECODE" in os.environ,
    "has_codex_thread_id": "CODEX_THREAD_ID" in os.environ,
}
Path(os.environ["FAKE_LOG"]).write_text(json.dumps(record), encoding="utf-8")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
if os.environ.get("FAKE_EXIT"):
    print("provider failure", file=sys.stderr)
    raise SystemExit(int(os.environ["FAKE_EXIT"]))
if provider == "claude":
    print(json.dumps({
        "result": "CHECK: TRUE README.md:1\nOVERALL VERDICT: PASS",
        "modelUsage": {"claude-haiku-4-5": {}, "claude-opus-4-8": {}},
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "total_cost_usd": 0.01,
    }))
else:
    started = {"type": "thread.started"}
    if not os.environ.get("FAKE_NO_MODEL"):
        started["model"] = "gpt-test"
    print(json.dumps(started))
    print(json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "CHECK: TRUE README.md:1\nOVERALL VERDICT: PASS"},
    }))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}))
"""


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        for provider in ("claude", "codex"):
            path = self.bin / provider
            path.write_text(FAKE_CLI, encoding="utf-8")
            path.chmod(0o755)
        self.log = self.base / "cli-log.json"
        self.output = self.base / "result.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def env(self, **overrides: str) -> dict[str, str]:
        env = dict(os.environ)
        env["PATH"] = str(self.bin)
        env["FAKE_LOG"] = str(self.log)
        env.update(overrides)
        return env

    def run_runner(
        self,
        author: str,
        *extra: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
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
                str(self.base),
                "--prompt",
                "Check README.md against the plan.",
                "--output",
                str(self.output),
                *extra,
            ],
            capture_output=True,
            text=True,
            env=env or self.env(),
            check=False,
        )

    def result(self) -> dict:
        return json.loads(self.output.read_text(encoding="utf-8"))

    def invocation(self) -> dict:
        return json.loads(self.log.read_text(encoding="utf-8"))

    def test_codex_author_routes_to_read_only_claude_opus(self) -> None:
        completed = self.run_runner("codex", env=self.env(CLAUDECODE="nested"))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.result()
        invocation = self.invocation()
        self.assertEqual(result["verifier"], "claude")
        self.assertEqual(result["assurance"], "independent")
        self.assertEqual(result["actual_model"], "claude-opus-4-8")
        self.assertEqual(result["models_used"], ["claude-haiku-4-5", "claude-opus-4-8"])
        self.assertEqual(result["requested_effort"], "xhigh")
        self.assertIn("--safe-mode", invocation["argv"])
        self.assertIn("Read,Glob,Grep", invocation["argv"])
        self.assertFalse(invocation["has_claudecode"])
        self.assertIn("OVERALL VERDICT: PASS", result["response"])

    def test_claude_author_preserves_original_codex_audit_route(self) -> None:
        completed = self.run_runner(
            "claude-code", env=self.env(CODEX_THREAD_ID="parent-thread")
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.result()
        invocation = self.invocation()
        self.assertEqual(result["verifier"], "codex")
        self.assertEqual(result["actual_model"], "gpt-test")
        self.assertIn("--sandbox", invocation["argv"])
        self.assertIn("read-only", invocation["argv"])
        self.assertIn("--ephemeral", invocation["argv"])
        self.assertIn("--ignore-user-config", invocation["argv"])
        self.assertIn("--ignore-rules", invocation["argv"])
        self.assertIn('model_reasoning_effort="xhigh"', invocation["argv"])
        self.assertFalse(invocation["has_codex_thread_id"])

    def test_codex_config_model_is_recorded_and_pinned_for_clean_run(self) -> None:
        codex_home = self.base / "codex-home"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            'model = "gpt-configured"\n', encoding="utf-8"
        )
        completed = self.run_runner(
            "claude-code",
            env=self.env(CODEX_HOME=str(codex_home), FAKE_NO_MODEL="1"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.result()
        invocation = self.invocation()
        self.assertEqual(result["requested_model"], "gpt-configured")
        self.assertEqual(result["actual_model"], "gpt-configured")
        self.assertEqual(result["model_source"], str(codex_home / "config.toml"))
        model_index = invocation["argv"].index("--model")
        self.assertEqual(invocation["argv"][model_index + 1], "gpt-configured")

    def test_multi_provider_agent_using_anthropic_routes_to_codex(self) -> None:
        completed = self.run_runner("cursor", "--author-provider", "anthropic")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.result()
        self.assertEqual(result["author_provider"], "claude")
        self.assertEqual(result["verifier"], "codex")
        self.assertEqual(result["assurance"], "independent")

    def test_third_party_author_uses_claude_when_codex_is_not_installed(self) -> None:
        (self.bin / "codex").unlink()
        completed = self.run_runner("gemini-cli")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.result()
        self.assertEqual(result["author_provider"], "other")
        self.assertEqual(result["verifier"], "claude")
        self.assertEqual(result["assurance"], "independent")

    def test_multi_provider_agent_using_openai_routes_to_claude(self) -> None:
        completed = self.run_runner("windsurf", "--author-provider", "openai")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.result()
        self.assertEqual(result["author_provider"], "codex")
        self.assertEqual(result["verifier"], "claude")

    def test_unknown_multi_provider_agent_requires_provider_hint(self) -> None:
        completed = self.run_runner("cursor")
        self.assertEqual(completed.returncode, 3)
        self.assertIn("--author-provider", self.result()["error"])
        self.assertFalse(self.log.exists())

    def test_invalid_third_party_preference_is_rejected(self) -> None:
        completed = self.run_runner(
            "gemini", env=self.env(VERIFIED_DELIVERY_OTHER_VERIFIER="invalid")
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("VERIFIED_DELIVERY_OTHER_VERIFIER", self.result()["error"])
        self.assertFalse(self.log.exists())

    def test_same_provider_is_rejected_without_explicit_override(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--author",
                "claude",
                "--verifier",
                "claude",
                "--gate",
                "plan",
                "--cwd",
                str(self.base),
                "--prompt",
                "Check it.",
                "--output",
                str(self.output),
            ],
            capture_output=True,
            text=True,
            env=self.env(),
            check=False,
        )
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(self.result()["status"], "failed")
        self.assertIn("same-provider", self.result()["error"])
        self.assertFalse(self.log.exists())

    def test_timeout_fails_closed_and_keeps_prompt_hash(self) -> None:
        completed = self.run_runner(
            "codex", "--timeout", "0.5", env=self.env(FAKE_SLEEP="2")
        )
        self.assertEqual(completed.returncode, 124)
        result = self.result()
        invocation = self.invocation()
        self.assertEqual(result["status"], "timed_out")
        expected_hash = hashlib.sha256(invocation["stdin"].encode("utf-8")).hexdigest()
        self.assertEqual(result["prompt_sha256"], expected_hash)

    def test_cli_failure_is_not_a_completed_gate(self) -> None:
        completed = self.run_runner("codex", env=self.env(FAKE_EXIT="9"))
        self.assertEqual(completed.returncode, 1)
        result = self.result()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 9)
        self.assertIn("provider failure", result["stderr_excerpt"])


if __name__ == "__main__":
    unittest.main()
