from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
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
        self.audited = self.base / "audited"
        self.audited.mkdir()
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
                str(self.audited),
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
        permission_index = invocation["argv"].index("--permission-mode")
        self.assertEqual(invocation["argv"][permission_index + 1], "plan")
        self.assertNotIn("Bash", invocation["argv"])
        self.assertFalse(result["readonly_shell"]["enabled"])
        self.assertFalse(invocation["has_claudecode"])
        self.assertIn("OVERALL VERDICT: PASS", result["response"])

    def test_stdout_result_keeps_event_sidecar_outside_cwd(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--author",
                "codex",
                "--verifier",
                "auto",
                "--gate",
                "plan",
                "--cwd",
                str(self.audited),
                "--prompt",
                "Check the plan.",
            ],
            capture_output=True,
            text=True,
            env=self.env(),
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        events = Path(result["events_file"])
        self.addCleanup(events.unlink, missing_ok=True)
        self.assertTrue(events.is_file())
        self.assertNotEqual(events.parent, self.audited)
        self.assertFalse((self.audited / "-.events.jsonl").exists())

    def test_claude_readonly_shell_is_exact_sandboxed_and_attributed(self) -> None:
        commands = [
            "git status --short",
            "python3 -m pytest -p no:cacheprovider -q tests/test_example.py",
        ]
        completed = self.run_runner(
            "codex",
            "--allow-readonly-shell",
            "--shell-command",
            commands[0],
            "--shell-command",
            commands[1],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.result()
        invocation = self.invocation()
        permission_index = invocation["argv"].index("--permission-mode")
        self.assertEqual(invocation["argv"][permission_index + 1], "dontAsk")
        self.assertIn("Read,Glob,Grep,Bash", invocation["argv"])
        self.assertIn(f"Bash({commands[0]})", invocation["argv"])
        self.assertIn(f"Bash({commands[1]})", invocation["argv"])
        self.assertIn("--strict-mcp-config", invocation["argv"])
        settings_index = invocation["argv"].index("--settings")
        settings = json.loads(invocation["argv"][settings_index + 1])
        sandbox = settings["sandbox"]
        self.assertTrue(sandbox["enabled"])
        self.assertFalse(sandbox["autoAllowBashIfSandboxed"])
        self.assertTrue(sandbox["failIfUnavailable"])
        self.assertFalse(sandbox["allowUnsandboxedCommands"])
        self.assertEqual(
            sandbox["filesystem"]["denyWrite"], [str(self.audited.resolve())]
        )
        self.assertEqual(result["readonly_shell"]["allowed_commands"], commands)
        self.assertEqual(
            result["readonly_shell"]["deny_write"], [str(self.audited.resolve())]
        )
        self.assertIn(
            "The Bash tool already returns stdout, stderr, and exit status",
            invocation["stdin"],
        )
        self.assertIn("Never append", invocation["stdin"])

    @unittest.skipUnless(sys.platform == "darwin", "macOS Seatbelt only")
    def test_macos_seatbelt_command_is_wrapped_and_native_excluded(self) -> None:
        requested = (
            "PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider "
            "-q tests/test_browser.py"
        )
        completed = self.run_runner(
            "codex",
            "--allow-readonly-shell",
            "--macos-seatbelt-command",
            requested,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = self.result()
        invocation = self.invocation()
        entries = result["readonly_shell"]["macos_seatbelt_commands"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["requested"], requested)
        wrapper = entries[0]["wrapper"]
        self.assertIn("run_macos_seatbelt.py", wrapper)
        self.assertIn(f"Bash({wrapper})", invocation["argv"])
        settings_index = invocation["argv"].index("--settings")
        settings = json.loads(invocation["argv"][settings_index + 1])
        self.assertEqual(
            settings["sandbox"]["excludedCommands"],
            [
                f"{shlex.join([str(Path(sys.executable).resolve()), str(ROOT / 'scripts' / 'run_macos_seatbelt.py')])} *"
            ],
        )
        self.assertIn(wrapper, invocation["stdin"])

    @unittest.skipUnless(sys.platform == "darwin", "macOS Seatbelt only")
    def test_macos_seatbelt_wrapper_supports_skill_path_with_spaces(self) -> None:
        spaced_scripts = self.base / "skill copy" / "scripts"
        spaced_scripts.mkdir(parents=True)
        copied_runner = spaced_scripts / "run_verifier.py"
        copied_seatbelt = spaced_scripts / "run_macos_seatbelt.py"
        shutil.copy2(RUNNER, copied_runner)
        shutil.copy2(ROOT / "scripts" / "run_macos_seatbelt.py", copied_seatbelt)
        completed = subprocess.run(
            [
                sys.executable,
                str(copied_runner),
                "--author",
                "codex",
                "--verifier",
                "auto",
                "--gate",
                "result",
                "--cwd",
                str(self.audited),
                "--prompt",
                "Check the result.",
                "--output",
                str(self.output),
                "--allow-readonly-shell",
                "--macos-seatbelt-command",
                "python3 -m pytest -q tests/test_browser.py",
            ],
            capture_output=True,
            text=True,
            env=self.env(),
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        invocation = self.invocation()
        settings_index = invocation["argv"].index("--settings")
        settings = json.loads(invocation["argv"][settings_index + 1])
        prefix = shlex.join(
            [str(Path(sys.executable).resolve()), str(copied_seatbelt.resolve())]
        )
        self.assertEqual(
            settings["sandbox"]["excludedCommands"],
            [f"{prefix} *"],
        )
        self.assertTrue(
            any(
                value.startswith(f"Bash({prefix} ")
                for value in invocation["argv"]
            )
        )

    @unittest.skipUnless(sys.platform == "darwin", "macOS Seatbelt only")
    def test_macos_seatbelt_command_rejects_nested_shell(self) -> None:
        for command in (
            "bash -c 'python3 -m pytest -q tests/test_browser.py'",
            "nice bash -c 'python3 -m pytest -q tests/test_browser.py'",
        ):
            with self.subTest(command=command):
                completed = self.run_runner(
                    "codex",
                    "--allow-readonly-shell",
                    "--macos-seatbelt-command",
                    command,
                )
                self.assertEqual(completed.returncode, 3)
                self.assertIn("cannot include env or a shell", self.result()["error"])
                self.assertFalse(self.log.exists())

    def test_readonly_shell_requires_result_output_outside_cwd(self) -> None:
        inside = self.audited / "result.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--author",
                "codex",
                "--verifier",
                "auto",
                "--gate",
                "result",
                "--cwd",
                str(self.audited),
                "--prompt",
                "Check the result.",
                "--output",
                str(inside),
                "--allow-readonly-shell",
                "--shell-command",
                "git status --short",
            ],
            capture_output=True,
            text=True,
            env=self.env(),
            check=False,
        )
        self.assertEqual(completed.returncode, 3)
        self.assertFalse(inside.exists())
        self.assertFalse((Path(f"{inside}.events.jsonl")).exists())
        self.assertFalse(self.log.exists())
        self.assertIn("outside the deny-write cwd", completed.stdout)

    def test_event_sidecar_failure_overwrites_stale_result(self) -> None:
        self.output.write_text(
            '{"status":"completed","response":"OVERALL VERDICT: PASS"}\n',
            encoding="utf-8",
        )
        Path(f"{self.output}.events.jsonl").mkdir()
        completed = self.run_runner("codex")
        self.assertEqual(completed.returncode, 1)
        result = self.result()
        self.assertEqual(result["status"], "failed")
        self.assertIn("cannot open verifier event sidecar", result["error"])
        self.assertFalse(self.log.exists())

    def test_macos_seatbelt_command_requires_readonly_shell_opt_in(self) -> None:
        completed = self.run_runner(
            "codex",
            "--macos-seatbelt-command",
            "python3 -m pytest -q tests/test_browser.py",
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("requires explicit", self.result()["error"])
        self.assertFalse(self.log.exists())

    def test_readonly_shell_fails_closed_without_exact_commands(self) -> None:
        completed = self.run_runner("codex", "--allow-readonly-shell")
        self.assertEqual(completed.returncode, 3)
        self.assertIn("requires at least one", self.result()["error"])
        self.assertFalse(self.log.exists())

    def test_shell_command_requires_explicit_opt_in(self) -> None:
        completed = self.run_runner(
            "codex", "--shell-command", "git status --short"
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("requires explicit", self.result()["error"])
        self.assertFalse(self.log.exists())

    def test_readonly_shell_rejects_compound_commands(self) -> None:
        completed = self.run_runner(
            "codex",
            "--allow-readonly-shell",
            "--shell-command",
            "git status --short && git push",
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("non-compound", self.result()["error"])
        self.assertFalse(self.log.exists())

    def test_readonly_shell_rejects_permission_metacharacters(self) -> None:
        for command in (
            "git status --short > /tmp/status.txt",
            "python3 -m pytest tests/*",
        ):
            with self.subTest(command=command):
                completed = self.run_runner(
                    "codex",
                    "--allow-readonly-shell",
                    "--shell-command",
                    command,
                )
                self.assertEqual(completed.returncode, 3)
                self.assertIn("non-compound", self.result()["error"])
                self.assertFalse(self.log.exists())

    def test_readonly_shell_is_not_reapplied_to_codex_adapter(self) -> None:
        completed = self.run_runner(
            "claude-code",
            "--allow-readonly-shell",
            "--shell-command",
            "git status --short",
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("only needed by the Claude adapter", self.result()["error"])
        self.assertFalse(self.log.exists())

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
