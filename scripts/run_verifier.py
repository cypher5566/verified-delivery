#!/usr/bin/env python3
"""Run a provider-independent verification gate and emit attributable JSON evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3
EXIT_GATE_CLOSED = 4
EXIT_TIMEOUT = 124
SUPPORTED_PROVIDERS = ("claude", "codex")
FORBIDDEN_SHELL_FRAGMENTS = (
    "\n",
    "\r",
    "\0",
    "&&",
    "||",
    ";",
    "|",
    "&",
    "`",
    "$(",
    "<",
    ">",
    "*",
)
MACOS_SEATBELT_RUNNER = Path(__file__).resolve().with_name("run_macos_seatbelt.py")
MACOS_CAFFEINATE = Path("/usr/bin/caffeinate")
SHELL_EXECUTABLES = {
    "bash",
    "csh",
    "dash",
    "fish",
    "ksh",
    "powershell",
    "pwsh",
    "sh",
    "tcsh",
    "zsh",
}
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)
REPORT_START = "<<verified-delivery-report:start>>"
REPORT_END = "<<verified-delivery-report:end>>"
OVERALL_VERDICT = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*|__)?"
    r"OVERALL VERDICT:\s*(PASS|FAIL|PARTIAL)"
    r"(?:\*\*|__)?\s*$"
)


class ConfigurationError(Exception):
    """Raised when a safe verifier configuration cannot be constructed."""


def missing_report_validation(reason: str) -> dict[str, Any]:
    return {
        "valid": False,
        "verdict": None,
        "errors": [reason],
        "warnings": [],
        "envelope_extracted": False,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def env_default(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def provider_family(value: str) -> str:
    normalized = value.strip().lower()
    if any(token in normalized for token in ("claude", "anthropic")):
        return "claude"
    if any(token in normalized for token in ("codex", "openai", "chatgpt", "gpt")):
        return "codex"
    if any(
        token in normalized
        for token in ("gemini", "google", "mistral", "qwen", "deepseek", "ollama")
    ):
        return "other"
    return "unknown"


def choose_verifier(
    author: str,
    author_provider_hint: str | None,
    requested: str,
    allow_same: bool,
) -> tuple[str, str, str]:
    if requested not in ("auto", *SUPPORTED_PROVIDERS):
        raise ConfigurationError(
            f"unsupported verifier '{requested}'; choose auto, claude, or codex"
        )
    author_provider = provider_family(author_provider_hint or author)
    if author_provider == "unknown":
        raise ConfigurationError(
            f"cannot infer the model provider used by upstream agent '{author}'; "
            "pass --author-provider (for example anthropic, openai, or google)"
        )
    if requested == "auto":
        if author_provider == "codex":
            selected = "claude"
            reason = "opposite provider for a Codex/OpenAI author"
        elif author_provider == "claude":
            selected = "codex"
            reason = "opposite provider for a Claude/Anthropic author"
        else:
            preferred = env_default("VERIFIED_DELIVERY_OTHER_VERIFIER", "codex")
            if preferred not in SUPPORTED_PROVIDERS:
                raise ConfigurationError(
                    "VERIFIED_DELIVERY_OTHER_VERIFIER must be claude or codex"
                )
            candidates = [preferred] + [
                provider for provider in SUPPORTED_PROVIDERS if provider != preferred
            ]
            selected = next(
                (provider for provider in candidates if shutil.which(provider)), ""
            )
            if not selected:
                raise ConfigurationError(
                    "no supported independent verifier CLI is available on PATH"
                )
            reason = f"available independent verifier for third-party author '{author}'"
    else:
        selected = requested
        reason = "explicit verifier selection"

    if selected == author_provider and not allow_same:
        raise ConfigurationError(
            "same-provider verification is not independent; obtain explicit user "
            "approval and pass --allow-same-provider to accept reduced assurance"
        )

    if shutil.which(selected) is None:
        raise ConfigurationError(
            f"required verifier CLI '{selected}' is not available on PATH; "
            "auto fallback is intentionally disabled"
        )
    return selected, author_provider, reason


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        prompt = args.prompt
    else:
        try:
            prompt = args.prompt_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationError(f"cannot read prompt file: {exc}") from exc
    if not prompt.strip():
        raise ConfigurationError("verification prompt must not be empty")
    return prompt


def wrap_prompt(gate: str, prompt: str) -> str:
    # The first line is the role-handshake marker. A verifier that has its own copy
    # of this skill installed would otherwise keyword-match the request and re-enter
    # the loop as an author (recruiting yet another verifier). The marker plus the
    # guard section in SKILL.md disambiguates the role deterministically.
    # The verifier's brief (audit the frame, not just the author's list) and the
    # grounding guard are adapted from PR #3 by Ching (ChingYu2014).
    return f"""<<verified-delivery-gate: {gate}>>
You are the independent VERIFIER for the {gate} gate of someone else's verified-delivery
run. You are not the author: do not invoke any locally installed verified-delivery
skill, do not run the delivery loop, and do not recruit another verifier. Work alone.
Stay read-only.

Grounding guard: before any analysis, print a one-line fingerprint for each source you
read. For a git repo, use permitted reads of `.git/config`, `.git/HEAD`, and the
resolved ref, or exact git commands only when command execution is available and
approved. For a database/dataset, use its resolved connection and table. If a
fingerprint cannot be obtained with the allowed tools, state UNAVAILABLE and keep the
claim uncertain; never invent it or claim a match. If the request names expected
fingerprints and any observed value differs, STOP and report MISMATCH instead of
analysing. Disambiguate look-alike paths by fingerprint, never by directory name.

Audit the frame, not just the author's list — the author drew the frame you look
through, so their blind spots are in it:
- Restate the original problem in one line, then judge whether the plan/diff solves
  THAT problem, not merely whether it does what it claims. Flag a wrong-shape
  approach; do not redesign it.
- State the invariants the source of truth implies; flag changes that are correct
  line-by-line but break one in composition.
- Attack the most fragile assumption first — you run under a hard time cap.
- Name band-aids: anything masking a deeper issue, even when it matches the source
  of truth line-for-line.
- Judge claims against the named source of truth and current files, not plausibility;
  mark each finding grounded-signal vs unverified-assumption. Keep missing evidence
  as uncertainty.
- Finish with an open sweep: anything wrong the author did not ask about.
Stay strict regardless of how confident or polished the request reads; do not anchor
on the author's framing.

Convergence guard: correctness comes from decisive evidence, not unlimited reading.
- Use the request's source routing, identifiers, and cited ranges first. Prefer
  targeted Read/Grep calls over reading whole large files, logs, or JSON artifacts.
- Stop collecting evidence for a scoped claim once it is supported or refuted by
  enough independent evidence to classify it. Do not keep reading for optional polish.
- Treat roughly 20 evidence tool calls as a synthesis checkpoint, not a correctness
  cap. At that point, reserve the remaining time for the complete report and inspect
  only evidence that could still change a material verdict.
- If a material point remains unresolved when synthesis must begin, report it as
  PARTIAL with the missing evidence. Never spend the final-report budget chasing
  certainty until the hard timeout, and never omit the report envelope.

Classify every finding as BLOCKING or NON-BLOCKING:
- BLOCKING means a scoped acceptance criterion or source-of-truth invariant is
  violated, a deterministic check fails because of this candidate, or missing
  evidence could realistically change the correctness verdict.
- NON-BLOCKING means hardening, maintainability, polish, or a follow-up outside the
  accepted scope. PASS may include non-blocking findings. Do not turn optional
  improvement into PARTIAL, and surface all blocking findings you can discover in
  this pass instead of drip-feeding them across reruns.

Citation precision is BLOCKING only when the evidence cannot be located uniquely or
the ambiguity could change the material verdict. If the request's identifier, routed
file, and cited range already identify the relevant behavior, treat a request for a
narrower line range as NON-BLOCKING and audit the behavior itself.

For a plan gate, judge the proposed specification, integration points, and planned
proof. A planned new file, test, helper, or copy key is expected to be absent before
implementation; absence is not a defect. It is BLOCKING only when the plan fails to
say what must be created, where it integrates, or how the acceptance criterion will
be proved.

For a result gate, apply an evidence-freshness guard. Deterministic test/build evidence
supports only the exact candidate fingerprint it was run against. Check every named
repo's HEAD and staged/unstaged/untracked state, plus any supplied diff/artifact hashes.
If source or contract inputs changed after the cited evidence, or one repo in a
multi-repo delivery was omitted, mark the affected claim PARTIAL. Do not infer freshness
from a passing command that ran against an unidentified candidate.

For a result gate, also apply an evidence-domain guard. Classify each requested check as
portable, target-host, external-readonly, or privileged-live. Reproduce portable checks
when an exact approved command is available. For target-host/device/live evidence,
verify the candidate binding, artifact identity, and relevant source without pretending
a sandbox skip is a pass. A command failure is candidate-caused only when grounded
evidence attributes it to the candidate; sandbox or capability failure is an environment
mismatch, and unresolved attribution remains unknown. Report each command's domain,
EXECUTED_PASS/EXECUTED_FAIL/UNAVAILABLE status, and candidate/environment/unknown scope.
When the gate spans domains, enforce dual proof: rerun all applicable portable checks
and separately audit fresh candidate-bound target-host/external/live evidence. Neither
half replaces the other.

For every requested check, report TRUE, FALSE, or PARTIAL with reasoning and a file:line,
table:column, contract-section, or exact-query citation.
End with an explicit overall verdict: PASS, FAIL, or PARTIAL. Be concise.

<verification_request>
{prompt.rstrip()}
</verification_request>

Your final response is the audit artifact. Put the COMPLETE report in the final
response; do not call ExitPlanMode, do not put findings in a plan transition or
another tool, and do not refer to content as being "above". The runner fails closed
if the report envelope or explicit verdict is missing.

Use this exact envelope, with every finding and citation inside it:
{REPORT_START}
[complete report]
OVERALL VERDICT: PASS|FAIL|PARTIAL
{REPORT_END}
"""


def readonly_shell_contract(commands: list[str]) -> str:
    rendered = "\n".join(f"- `{command}`" for command in commands)
    return f"""

<readonly_shell_contract>
The Bash tool already returns stdout, stderr, and exit status. Invoke each approved
command separately and character-for-character exactly as listed below. Never append
`echo $?`, a separator, redirect, loop, wrapper, timeout, `cd`, environment change, or
any other character. A modified or combined command will be permission-denied and must
remain a non-passing uncertainty; do not retry it in a different shape.

The caller classified these commands as portable, but verify that assumption from the
observed result. For each command, record EXECUTED_PASS, EXECUTED_FAIL, or UNAVAILABLE
and classify a failure as candidate, environment, or unknown. Do not label the candidate
broken merely because the OS sandbox cannot expose a host process table, device, IPC,
network, credential, or other undeclared capability. Such a mismatch keeps material
evidence open unless the request supplies same-fingerprint target-host evidence plus a
source audit. Never weaken a checked invariant or invent a pass to compensate.

Approved exact commands:
{rendered}
</readonly_shell_contract>
"""


def validate_shell_commands(commands: list[str]) -> None:
    for command in commands:
        if not command.strip():
            raise ConfigurationError("an approved evidence command cannot be empty")
        fragment = next(
            (part for part in FORBIDDEN_SHELL_FRAGMENTS if part in command), None
        )
        if fragment is not None:
            raise ConfigurationError(
                "an approved evidence command must be exact and non-compound; "
                f"found forbidden fragment {fragment!r}"
            )


def encode_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def macos_command_executable(argv: list[str]) -> str:
    index = 0
    while index < len(argv) and ENV_ASSIGNMENT.fullmatch(argv[index]):
        index += 1
    if index >= len(argv):
        raise ConfigurationError(
            "--macos-seatbelt-command must include an executable after environment "
            "assignments"
        )
    executable = Path(argv[index]).name.lower()
    forbidden = next(
        (
            Path(item).name.lower()
            for item in argv[index:]
            if Path(item).name.lower() == "env"
            or Path(item).name.lower() in SHELL_EXECUTABLES
        ),
        None,
    )
    if forbidden is not None:
        raise ConfigurationError(
            "--macos-seatbelt-command cannot include env or a shell interpreter "
            f"argv ({forbidden}); "
            "provide the deterministic executable argv directly"
        )
    return executable


def macos_seatbelt_wrapper(cwd: Path, command: str) -> str:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ConfigurationError(f"invalid --macos-seatbelt-command: {exc}") from exc
    if not argv:
        raise ConfigurationError("--macos-seatbelt-command cannot be empty")
    macos_command_executable(argv)
    return shlex.join(
        [
            str(Path(sys.executable).resolve()),
            str(MACOS_SEATBELT_RUNNER),
            "--deny-write-base64",
            encode_json(str(cwd)),
            "--argv-base64",
            encode_json(argv),
        ]
    )


def normalize_result_output(output: str, cwd: Path, readonly_shell: bool) -> str:
    if output == "-":
        if readonly_shell:
            raise ConfigurationError(
                "--allow-readonly-shell requires --output at a path outside cwd"
            )
        return output
    destination = Path(output).expanduser().resolve()
    if readonly_shell and (destination == cwd or cwd in destination.parents):
        raise ConfigurationError(
            "--allow-readonly-shell requires --output outside the deny-write cwd"
        )
    return str(destination)


def open_events_file(output: str) -> tuple[Path, Any]:
    if output == "-":
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix="verified-delivery-",
            suffix=".events.jsonl",
            delete=False,
        )
        return Path(handle.name), handle
    events_path = Path(f"{output}.events.jsonl")
    events_path.parent.mkdir(parents=True, exist_ok=True)
    return events_path, events_path.open("w", encoding="utf-8")


def claude_command(
    model: str,
    effort: str,
    cwd: Path,
    shell_commands: list[str],
    excluded_commands: list[str],
) -> list[str]:
    command = [
        "claude",
        "-p",
        "--safe-mode",
        "--model",
        model,
        "--effort",
        effort,
    ]
    if not shell_commands:
        command.extend(
            [
                "--permission-mode",
                "dontAsk",
                "--tools",
                "Read,Glob,Grep",
                "--allowedTools",
                "Read",
                "Glob",
                "Grep",
                "--disallowedTools",
                "Edit",
                "Write",
                "NotebookEdit",
                "Bash",
                "WebFetch",
                "WebSearch",
                "Agent",
                "Task",
                "ExitPlanMode",
                "--strict-mcp-config",
            ]
        )
    else:
        # Claude's native sandbox uses Seatbelt on macOS and bubblewrap on Linux.
        # The caller opts in with exact commands; the target tree remains OS-level
        # read-only even for pytest/node subprocesses, and unsandboxed fallback is
        # a hard failure rather than a silent downgrade.
        sandbox_settings = {
            "sandbox": {
                "enabled": True,
                "autoAllowBashIfSandboxed": False,
                "failIfUnavailable": True,
                "allowUnsandboxedCommands": False,
                "filesystem": {"denyWrite": [str(cwd)]},
                "network": {"allowLocalBinding": True},
            }
        }
        if excluded_commands:
            sandbox_settings["sandbox"]["excludedCommands"] = excluded_commands
        command.extend(
            [
                "--permission-mode",
                "dontAsk",
                "--tools",
                "Read,Glob,Grep,Bash",
                "--allowedTools",
                "Read",
                "Glob",
                "Grep",
                *[f"Bash({item})" for item in shell_commands],
                "--disallowedTools",
                "Edit",
                "Write",
                "NotebookEdit",
                "WebFetch",
                "WebSearch",
                "Agent",
                "Task",
                "ExitPlanMode",
                "--settings",
                json.dumps(sandbox_settings, separators=(",", ":")),
                "--strict-mcp-config",
            ]
        )
    command.extend(
        [
            "--no-session-persistence",
            "--output-format",
            "json",
        ]
    )
    return command


def codex_command(model: str | None, effort: str) -> list[str]:
    command = [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--json",
        "-c",
        f'model_reasoning_effort="{effort}"',
    ]
    if model:
        command.extend(["--model", model])
    command.append("-")
    return command


def command_for(
    verifier: str,
    model: str | None,
    effort: str,
    cwd: Path,
    shell_commands: list[str],
    excluded_commands: list[str],
) -> list[str]:
    if verifier == "claude":
        if not model:
            raise ConfigurationError("the Claude adapter requires a model")
        return claude_command(
            model,
            effort,
            cwd,
            shell_commands,
            excluded_commands,
        )
    return codex_command(model, effort)


def verifier_environment(verifier: str) -> dict[str, str]:
    env = dict(os.environ)
    if verifier == "claude":
        env.pop("CLAUDECODE", None)
    else:
        env.pop("CODEX_THREAD_ID", None)
    return env


def stop_process_group(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Stop the verifier and its children, then return any remaining output."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        process.terminate()
    try:
        return process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        return process.communicate()


def excerpt(value: str | bytes | None, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return value[-limit:]


def find_model_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "model" and isinstance(child, str):
                found.append(child)
            else:
                found.extend(find_model_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_model_values(child))
    return found


def parse_claude(stdout: str, requested_model: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "response": stdout.strip(),
            "actual_model": requested_model,
            "model_source": "requested; CLI output was not JSON",
        }

    model_usage = payload.get("modelUsage") or {}
    models = list(model_usage) if isinstance(model_usage, dict) else []
    actual: str | list[str]
    if requested_model in models:
        actual = requested_model
        model_source = "requested model confirmed in modelUsage"
    elif len(models) == 1:
        actual = models[0]
        model_source = "modelUsage"
    elif models:
        actual = models
        model_source = "modelUsage"
    else:
        actual = requested_model
        model_source = "requested"
    response = payload.get("structured_output", payload.get("result", ""))
    return {
        "response": response,
        "actual_model": actual,
        "models_used": models,
        "model_source": model_source,
        "usage": payload.get("usage"),
        "cost_usd": payload.get("total_cost_usd"),
    }


def parse_codex(
    stdout: str, requested_model: str, requested_model_source: str
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)

    messages: list[Any] = []
    usage: Any = None
    for event in events:
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict):
            if item.get("type") in {"agent_message", "message"}:
                messages.append(item.get("text", item.get("content", "")))
        if event.get("type") == "turn.completed":
            usage = event.get("usage")

    reported_models = []
    for model in find_model_values(events):
        if model not in reported_models:
            reported_models.append(model)
    if len(reported_models) == 1:
        actual_model: Any = reported_models[0]
        model_source = "codex event"
    elif reported_models:
        actual_model = reported_models
        model_source = "codex events"
    elif requested_model != "configured-default":
        actual_model = requested_model
        model_source = requested_model_source
    else:
        actual_model = "configured-default"
        model_source = "not reported by CLI"

    response = messages[-1] if messages else stdout.strip()
    return {
        "response": response,
        "actual_model": actual_model,
        "model_source": model_source,
        "usage": usage,
    }


def validate_report(response: Any) -> dict[str, Any]:
    """Require a complete, self-contained verifier artifact.

    Provider exit code 0 only proves that the CLI completed. The envelope prevents a
    verifier from placing its substantive findings in a plan-transition/tool payload
    that the provider's final-result field does not preserve.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(response, str):
        return {
            "valid": False,
            "verdict": None,
            "errors": ["response is not text"],
            "warnings": [],
            "envelope_extracted": False,
        }

    raw = response.strip()
    start_count = raw.count(REPORT_START)
    end_count = raw.count(REPORT_END)
    report = ""
    outside = raw
    if start_count != 1 or end_count != 1:
        errors.append("exactly one complete report envelope is required")
    else:
        start = raw.index(REPORT_START)
        end = raw.find(REPORT_END, start + len(REPORT_START))
        if end < 0:
            errors.append("complete report envelope is malformed")
        else:
            end += len(REPORT_END)
            report = raw[start:end]
            outside = (raw[:start] + "\n" + raw[end:]).strip()
            if outside:
                warnings.append(
                    "ignored non-verdict text outside the single complete report envelope"
                )
            if OVERALL_VERDICT.search(outside):
                errors.append("overall verdict outside the report envelope is not allowed")

    verdicts = OVERALL_VERDICT.findall(report)
    if len(verdicts) != 1:
        errors.append("exactly one explicit overall verdict is required")
    elif report:
        body = report[len(REPORT_START) : -len(REPORT_END)]
        body_without_verdict = OVERALL_VERDICT.sub("", body).strip()
        if not body_without_verdict:
            errors.append("substantive report body is missing")

    return {
        "valid": not errors,
        "verdict": verdicts[0].upper() if len(verdicts) == 1 else None,
        "errors": errors,
        "warnings": warnings,
        "envelope_extracted": bool(report) and bool(outside),
        "report": report or None,
    }


def configured_codex_model() -> tuple[str | None, str]:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    config_path = codex_home / "config.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None, "Codex CLI default"
    model = config.get("model")
    if isinstance(model, str) and model:
        return model, str(config_path)
    return None, "Codex CLI default"


def write_result(payload: dict[str, Any], output: str) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output != "-":
        destination = Path(output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=destination.parent, delete=False
        ) as handle:
            handle.write(rendered)
            temporary = Path(handle.name)
        os.replace(temporary, destination)
    sys.stdout.write(rendered)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--author",
        required=True,
        help="Upstream coding agent/provider, e.g. claude, codex, cursor, windsurf, gemini",
    )
    ap.add_argument(
        "--author-provider",
        help=(
            "Actual upstream model provider for multi-provider agents such as Cursor "
            "or Windsurf, e.g. anthropic, openai, or google"
        ),
    )
    ap.add_argument(
        "--verifier",
        choices=("auto", *SUPPORTED_PROVIDERS),
        default=env_default("VERIFIED_DELIVERY_VERIFIER", "auto"),
    )
    ap.add_argument("--allow-same-provider", action="store_true")
    ap.add_argument("--gate", required=True, choices=("plan", "result"))
    ap.add_argument("--cwd", type=Path, default=Path.cwd())
    prompt_group = ap.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt")
    prompt_group.add_argument("--prompt-file", type=Path)
    ap.add_argument("--output", default="-")
    ap.add_argument("--model", help="Override the selected verifier model")
    ap.add_argument(
        "--effort", default=env_default("VERIFIED_DELIVERY_EFFORT", "xhigh")
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=float(env_default("VERIFIED_DELIVERY_TIMEOUT", "600")),
    )
    ap.add_argument(
        "--allow-system-sleep",
        action="store_true",
        help=(
            "Opt out of the runner's macOS caffeinate assertion. By default a "
            "long verifier process prevents idle/system sleep so the hard timeout, "
            "not host suspension, owns liveness."
        ),
    )
    ap.add_argument(
        "--allow-readonly-shell",
        action="store_true",
        help=(
            "Opt a Claude verifier into exact Bash commands inside its native "
            "OS sandbox; cwd is deny-write, output must be external, and "
            "unsandboxed fallback is disabled"
        ),
    )
    ap.add_argument(
        "--shell-command",
        action="append",
        default=[],
        help=(
            "One exact, non-compound command permitted by --allow-readonly-shell; "
            "repeat for each deterministic check"
        ),
    )
    ap.add_argument(
        "--macos-seatbelt-command",
        action="append",
        default=[],
        help=(
            "One exact argv-only command that needs macOS IPC (for example "
            "Playwright); runs outside Claude's native sandbox but inside a fixed "
            "Seatbelt profile that deny-writes cwd"
        ),
    )
    ap.add_argument("--dry-run", action="store_true")
    return ap


def error_payload(args: argparse.Namespace, message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "failed",
        "gate_outcome_class": "configuration_error",
        "verifier_verdict": None,
        "reported_gate_passed": False,
        "gate": args.gate,
        "author": args.author,
        "verifier": None,
        "assurance": "none",
        "report_validation": missing_report_validation(
            "gate did not produce a verifier report"
        ),
        "error": message,
        "finished_at": utc_now(),
    }


def run(args: argparse.Namespace) -> int:
    result_output = args.output if not args.allow_readonly_shell else "-"
    try:
        cwd = args.cwd.expanduser().resolve(strict=True)
        if not cwd.is_dir():
            raise ConfigurationError(f"cwd is not a directory: {cwd}")
        if args.timeout <= 0:
            raise ConfigurationError("timeout must be greater than zero")
        result_output = normalize_result_output(
            args.output,
            cwd,
            args.allow_readonly_shell,
        )
        verifier, author_provider, selection_reason = choose_verifier(
            args.author,
            args.author_provider,
            args.verifier,
            args.allow_same_provider,
        )
        requested_commands = [*args.shell_command, *args.macos_seatbelt_command]
        if requested_commands and not args.allow_readonly_shell:
            raise ConfigurationError(
                "a shell command requires explicit --allow-readonly-shell"
            )
        if args.allow_readonly_shell and not requested_commands:
            raise ConfigurationError(
                "--allow-readonly-shell requires at least one shell command"
            )
        if args.allow_readonly_shell and verifier != "claude":
            raise ConfigurationError(
                "--allow-readonly-shell is only needed by the Claude adapter; "
                "the Codex adapter already uses its native read-only sandbox"
            )
        validate_shell_commands(requested_commands)
        if args.macos_seatbelt_command:
            if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
                raise ConfigurationError(
                    "--macos-seatbelt-command requires macOS /usr/bin/sandbox-exec"
                )
            if not MACOS_SEATBELT_RUNNER.is_file():
                raise ConfigurationError(
                    f"missing bundled Seatbelt runner: {MACOS_SEATBELT_RUNNER}"
                )
        seatbelt_commands = [
            {
                "requested": item,
                "wrapper": macos_seatbelt_wrapper(cwd, item),
            }
            for item in args.macos_seatbelt_command
        ]
        effective_shell_commands = [
            *args.shell_command,
            *[item["wrapper"] for item in seatbelt_commands],
        ]
        excluded_prefix = shlex.join(
            [str(Path(sys.executable).resolve()), str(MACOS_SEATBELT_RUNNER)]
        )
        excluded_commands = [f"{excluded_prefix} *"] if seatbelt_commands else []
        prompt = wrap_prompt(args.gate, read_prompt(args))
        if args.allow_readonly_shell:
            prompt += readonly_shell_contract(effective_shell_commands)
        if args.model:
            command_model = args.model
            requested_model = args.model
            requested_model_source = "--model"
        elif verifier == "claude":
            command_model = env_default(
                "VERIFIED_DELIVERY_CLAUDE_MODEL", "claude-opus-5"
            )
            requested_model = command_model or "claude-opus-5"
            requested_model_source = (
                "VERIFIED_DELIVERY_CLAUDE_MODEL or built-in default"
            )
        else:
            command_model = env_default("VERIFIED_DELIVERY_CODEX_MODEL")
            if command_model:
                requested_model = command_model
                requested_model_source = "VERIFIED_DELIVERY_CODEX_MODEL"
            else:
                configured_model, configured_source = configured_codex_model()
                requested_model = configured_model or "configured-default"
                requested_model_source = configured_source
                command_model = configured_model
        command = command_for(
            verifier,
            command_model,
            args.effort,
            cwd,
            effective_shell_commands,
            excluded_commands,
        )
        power_assertion: dict[str, Any] = {
            "enabled": False,
            "provider": None,
            "reason": "not_macos",
        }
        if sys.platform == "darwin":
            if args.allow_system_sleep:
                power_assertion["reason"] = "explicit_opt_out"
            elif MACOS_CAFFEINATE.is_file():
                command = [str(MACOS_CAFFEINATE), "-i", "--", *command]
                power_assertion = {
                    "enabled": True,
                    "provider": str(MACOS_CAFFEINATE),
                    "reason": "protect_verifier_liveness",
                }
            else:
                power_assertion["reason"] = "caffeinate_unavailable"
    except (ConfigurationError, OSError) as exc:
        write_result(error_payload(args, str(exc)), result_output)
        return EXIT_UNAVAILABLE

    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    started_at = utc_now()
    started = time.monotonic()
    assurance = "independent" if verifier != author_provider else "reduced"
    base: dict[str, Any] = {
        "schema_version": 1,
        "status": "dry_run" if args.dry_run else "running",
        "gate_outcome_class": "dry_run" if args.dry_run else "pending",
        "verifier_verdict": None,
        "reported_gate_passed": False,
        "gate": args.gate,
        "author": args.author,
        "author_provider": author_provider,
        "author_provider_input": args.author_provider,
        "verifier": verifier,
        "selection_reason": selection_reason,
        "assurance": assurance,
        "requested_model": requested_model,
        "requested_model_source": requested_model_source,
        "requested_effort": args.effort,
        "cwd": str(cwd),
        "prompt_sha256": prompt_hash,
        "timeout_seconds": args.timeout,
        "power_assertion": power_assertion,
        "report_validation": missing_report_validation(
            "verifier report has not completed"
        ),
        "readonly_shell": {
            "enabled": args.allow_readonly_shell,
            "sandbox": "claude-native" if args.allow_readonly_shell else None,
            "permission_mode": "dontAsk" if verifier == "claude" else None,
            "deny_write": [str(cwd)] if args.allow_readonly_shell else [],
            "allowed_commands": effective_shell_commands,
            "direct_commands": args.shell_command,
            "macos_seatbelt_commands": seatbelt_commands,
            "native_sandbox_exclusions": excluded_commands,
            "unsandboxed_fallback": False if args.allow_readonly_shell else None,
        },
        "command": [*command, "<prompt-via-stdin>"],
        "executable": shutil.which(verifier),
        "started_at": started_at,
    }

    if args.dry_run:
        base["duration_seconds"] = round(time.monotonic() - started, 3)
        base["finished_at"] = utc_now()
        write_result(base, result_output)
        return 0

    # Audit-trail sidecar: raw verifier stdout (Codex JSONL exec events show which
    # files/commands the auditor ran). Written live so `tail -f <output>.events.jsonl`
    # gives mid-run visibility; kept on success for post-hoc audit.
    try:
        events_path, events_fh = open_events_file(result_output)
    except OSError as exc:
        base.update(
            {
                "status": "failed",
                "gate_outcome_class": "verifier_infrastructure",
                "exit_code": EXIT_FAILED,
                "duration_seconds": round(time.monotonic() - started, 3),
                "finished_at": utc_now(),
                "error": f"cannot open verifier event sidecar: {exc}",
            }
        )
        try:
            write_result(base, result_output)
        except OSError as output_exc:
            base["error"] += f"; cannot write result output: {output_exc}"
            write_result(base, "-")
        return EXIT_FAILED
    base["events_file"] = str(events_path)

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=events_fh,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
            cwd=cwd,
            env=verifier_environment(verifier),
        )
    except OSError as exc:
        base.update(
            {
                "status": "failed",
                "gate_outcome_class": "verifier_infrastructure",
                "exit_code": EXIT_FAILED,
                "duration_seconds": round(time.monotonic() - started, 3),
                "finished_at": utc_now(),
                "error": f"could not start verifier CLI: {exc}",
            }
        )
        events_fh.close()
        write_result(base, result_output)
        return EXIT_FAILED

    def read_events() -> str:
        events_fh.flush()
        try:
            with events_path.open(encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    try:
        _, stderr = process.communicate(input=prompt, timeout=args.timeout)
        stdout = read_events()
    except subprocess.TimeoutExpired:
        _, stderr = stop_process_group(process)
        stdout = read_events()
        base.update(
            {
                "status": "timed_out",
                "gate_outcome_class": "verifier_timeout",
                "exit_code": EXIT_TIMEOUT,
                "duration_seconds": round(time.monotonic() - started, 3),
                "finished_at": utc_now(),
                "stdout_excerpt": excerpt(stdout),
                "stderr_excerpt": excerpt(stderr),
                "error": "verifier exceeded the hard timeout; the gate did not run",
            }
        )
        events_fh.close()
        write_result(base, result_output)
        return EXIT_TIMEOUT

    base.update(
        {
            "exit_code": process.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "finished_at": utc_now(),
        }
    )
    if process.returncode != 0:
        base.update(
            {
                "status": "failed",
                "gate_outcome_class": "verifier_infrastructure",
                "stdout_excerpt": excerpt(stdout),
                "stderr_excerpt": excerpt(stderr),
                "error": "verifier CLI exited nonzero; the gate did not run",
            }
        )
        events_fh.close()
        write_result(base, result_output)
        return EXIT_FAILED

    events_fh.close()
    parsed = (
        parse_claude(stdout, requested_model)
        if verifier == "claude"
        else parse_codex(stdout, requested_model, requested_model_source)
    )
    base.update(parsed)
    report_validation = validate_report(base.get("response"))
    base["report_validation"] = report_validation
    if report_validation.get("report"):
        base["verified_report"] = report_validation["report"]
    if stderr.strip():
        base["stderr_excerpt"] = excerpt(stderr)
    if not report_validation["valid"]:
        base["status"] = "failed"
        base["gate_outcome_class"] = "verifier_protocol"
        base["error"] = (
            "verifier returned an incomplete final report; gate remains closed: "
            + "; ".join(report_validation["errors"])
        )
        write_result(base, result_output)
        return EXIT_FAILED
    verifier_verdict = report_validation["verdict"]
    base["verifier_verdict"] = verifier_verdict
    base["reported_gate_passed"] = verifier_verdict == "PASS"
    base["status"] = "completed"
    base["gate_outcome_class"] = (
        "gate_passed" if base["reported_gate_passed"] else "gate_nonpassing"
    )
    if not base["reported_gate_passed"]:
        base["gate_closed_reason"] = (
            f"verifier returned {verifier_verdict}; the gate remains closed"
        )
        write_result(base, result_output)
        return EXIT_GATE_CLOSED
    write_result(base, result_output)
    return 0


def main() -> int:
    args = parser().parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
