#!/usr/bin/env python3
"""Run a provider-independent verification gate and emit attributable JSON evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
EXIT_TIMEOUT = 124
SUPPORTED_PROVIDERS = ("claude", "codex")


class ConfigurationError(Exception):
    """Raised when a safe verifier configuration cannot be constructed."""


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
    return f"""You are the independent verifier for the {gate} gate of a verified-delivery workflow.
Stay read-only. Judge claims against the named source of truth and current files, not plausibility.
For every requested check, report TRUE, FALSE, or PARTIAL with reasoning and a file:line,
table:column, contract-section, or exact-query citation. Keep missing evidence as uncertainty.
End with an explicit overall verdict: PASS, FAIL, or PARTIAL. Be concise.

<verification_request>
{prompt.rstrip()}
</verification_request>
"""


def claude_command(model: str, effort: str) -> list[str]:
    return [
        "claude",
        "-p",
        "--safe-mode",
        "--model",
        model,
        "--effort",
        effort,
        "--permission-mode",
        "plan",
        "--tools",
        "Read,Glob,Grep",
        "--no-session-persistence",
        "--output-format",
        "json",
    ]


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


def command_for(verifier: str, model: str | None, effort: str) -> list[str]:
    if verifier == "claude":
        if not model:
            raise ConfigurationError("the Claude adapter requires a model")
        return claude_command(model, effort)
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
    ap.add_argument("--dry-run", action="store_true")
    return ap


def error_payload(args: argparse.Namespace, message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "failed",
        "gate": args.gate,
        "author": args.author,
        "verifier": None,
        "assurance": "none",
        "error": message,
        "finished_at": utc_now(),
    }


def run(args: argparse.Namespace) -> int:
    try:
        cwd = args.cwd.expanduser().resolve(strict=True)
        if not cwd.is_dir():
            raise ConfigurationError(f"cwd is not a directory: {cwd}")
        if args.timeout <= 0:
            raise ConfigurationError("timeout must be greater than zero")
        verifier, author_provider, selection_reason = choose_verifier(
            args.author,
            args.author_provider,
            args.verifier,
            args.allow_same_provider,
        )
        prompt = wrap_prompt(args.gate, read_prompt(args))
        if args.model:
            command_model = args.model
            requested_model = args.model
            requested_model_source = "--model"
        elif verifier == "claude":
            command_model = env_default(
                "VERIFIED_DELIVERY_CLAUDE_MODEL", "claude-opus-4-8"
            )
            requested_model = command_model or "claude-opus-4-8"
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
        command = command_for(verifier, command_model, args.effort)
    except (ConfigurationError, OSError) as exc:
        write_result(error_payload(args, str(exc)), args.output)
        return EXIT_UNAVAILABLE

    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    started_at = utc_now()
    started = time.monotonic()
    assurance = "independent" if verifier != author_provider else "reduced"
    base: dict[str, Any] = {
        "schema_version": 1,
        "status": "dry_run" if args.dry_run else "running",
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
        "command": [*command, "<prompt-via-stdin>"],
        "executable": shutil.which(verifier),
        "started_at": started_at,
    }

    if args.dry_run:
        base["duration_seconds"] = round(time.monotonic() - started, 3)
        base["finished_at"] = utc_now()
        write_result(base, args.output)
        return 0

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
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
                "exit_code": EXIT_FAILED,
                "duration_seconds": round(time.monotonic() - started, 3),
                "finished_at": utc_now(),
                "error": f"could not start verifier CLI: {exc}",
            }
        )
        write_result(base, args.output)
        return EXIT_FAILED

    try:
        stdout, stderr = process.communicate(input=prompt, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        stdout, stderr = stop_process_group(process)
        base.update(
            {
                "status": "timed_out",
                "exit_code": EXIT_TIMEOUT,
                "duration_seconds": round(time.monotonic() - started, 3),
                "finished_at": utc_now(),
                "stdout_excerpt": excerpt(stdout),
                "stderr_excerpt": excerpt(stderr),
                "error": "verifier exceeded the hard timeout; the gate did not run",
            }
        )
        write_result(base, args.output)
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
                "stdout_excerpt": excerpt(stdout),
                "stderr_excerpt": excerpt(stderr),
                "error": "verifier CLI exited nonzero; the gate did not run",
            }
        )
        write_result(base, args.output)
        return EXIT_FAILED

    parsed = (
        parse_claude(stdout, requested_model)
        if verifier == "claude"
        else parse_codex(stdout, requested_model, requested_model_source)
    )
    base.update(parsed)
    base["status"] = "completed"
    if stderr.strip():
        base["stderr_excerpt"] = excerpt(stderr)
    write_result(base, args.output)
    return 0


def main() -> int:
    args = parser().parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
