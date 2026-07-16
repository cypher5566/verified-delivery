# verified-delivery

A provider-neutral skill for shipping correctness-critical changes with two independent
reviews: one before implementation and one before integration.

> **ground truth → independent plan audit → build → independent result audit → fix → integrate**

The upstream coding agent can be Claude Code, Codex, Cursor, Windsurf, Gemini, Aider,
or another agent. The verifier is selected from a different provider so the author is
not grading its own assumptions.

## Default routing

| Upstream author | Independent verifier |
|---|---|
| Claude Code / Anthropic | Codex |
| Codex / OpenAI | Claude Code (`claude-opus-4-8`, `xhigh`) |
| Other coding agent | Codex when installed, otherwise Claude Code |

The original Claude Code → Codex workflow remains the default for Claude users. Runtime
failure never triggers a silent model or provider fallback.

## What stays invariant

1. Name a checkable single source of truth (SSOT) and cite it.
2. Scope the requested batch as `do now`, `defer`, or `N/A`.
3. Have a different provider verify the plan before implementation.
4. Build and run deterministic checks.
5. Start a fresh verifier process to audit the result against the SSOT and plan.
6. Treat missing evidence, timeout, CLI failure, and ambiguous verdicts as non-passing.

It is intentionally heavier than a normal one-shot change. Use it when being wrong is
expensive and the error would otherwise be discovered late.

## Repository layout

```text
verified-delivery/
├── SKILL.md
├── references/
│   ├── verifier-policy.md
│   └── adapters/
│       ├── claude.md
│       └── codex.md
├── scripts/
│   └── run_verifier.py
├── tests/
│   ├── test_cli_compatibility.py
│   └── test_run_verifier.py
└── evals/
```

`SKILL.md` owns the provider-neutral workflow. Adapter details are progressively loaded
only for the selected verifier. `run_verifier.py` performs provider selection, applies
read-only flags, supplies the prompt over stdin, enforces a hard timeout, and writes a
normalized JSON audit record. Both adapters suppress unrelated customizations; Codex's
configured model ID is resolved first and then pinned for the clean verifier process.

## Prerequisites

- Python 3.11 or later
- At least one authenticated verifier CLI:
  - [Claude Code](https://claude.com/claude-code), or
  - [Codex CLI](https://github.com/openai/codex)
- For automatic opposite-provider review, the verifier CLI must differ from the
  upstream author.

## Install

Install the entire directory because the skill depends on `references/` and `scripts/`.

Claude Code:

```bash
git clone https://github.com/cypher5566/verified-delivery.git \
  ~/.claude/skills/verified-delivery
```

Codex:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo cypher5566/verified-delivery --path . --name verified-delivery
```

Or clone/copy the repository to `~/.codex/skills/verified-delivery`.

## Use

Invoke `/verified-delivery` or ask naturally:

- “This is a billing change. Verify the plan and implementation against the contract.”
- “走驗證流程，把舊 app 的 analytics event 精準移植過來。”
- “Have a different model audit both the migration plan and final diff.”

The skill calls the runner for each gate. A direct dry run can inspect routing without
calling a model:

```bash
python3 scripts/run_verifier.py \
  --author cursor \
  --author-provider anthropic \
  --verifier auto \
  --gate plan \
  --cwd . \
  --prompt "Verify this plan against README.md" \
  --dry-run
```

For real gates, prefer `--prompt-file` and preserve `--output` as audit evidence:

```bash
python3 scripts/run_verifier.py \
  --author claude-code \
  --verifier auto \
  --gate result \
  --cwd /path/to/common-parent \
  --prompt-file /tmp/result-gate.md \
  --output /tmp/result-gate.json
```

The JSON `status: completed` means the CLI ran, not that the verifier passed the work.
Read `response` and require an explicit, cited verdict.

Claude uses Read/Glob/Grep by default. If a result gate is blocked only because the
independent verifier must rerun deterministic evidence, opt in to exact commands:

```bash
python3 scripts/run_verifier.py \
  --author codex \
  --verifier claude \
  --gate result \
  --cwd /path/to/common-parent \
  --prompt-file /tmp/result-gate.md \
  --output /tmp/result-gate.json \
  --allow-readonly-shell \
  --shell-command 'git status --short' \
  --shell-command 'git diff --check'
```

The runner uses `dontAsk` plus exact approvals and Claude's native OS sandbox. The
entire `cwd` is deny-write, sandbox startup is mandatory, unsandboxed fallback is off,
and shell separators, redirects, substitutions, and the `*` permission wildcard are
rejected. This keeps evidence reproduction independent without turning the verifier
into a coding agent. In this mode, `--output` is mandatory and must be outside `cwd`;
the result and its live `.events.jsonl` sidecar therefore cannot alter the audited tree.

“Read-only” here means the audited `cwd`, not every external system. Approve only
semantically read-only checks: the sandbox cannot stop an exact `adb`, database, cloud,
or network command from mutating its remote target. Keep those commands query-only.

On macOS, Chromium may need Mach IPC that Claude's native Bash sandbox denies. Put only
the affected Playwright command behind `--macos-seatbelt-command`. The bundled wrapper
runs argv-only (no shell), excludes only itself from the native sandbox, and immediately
reapplies a fixed Seatbelt profile with the same full-`cwd` deny-write boundary. The
runner records the requested command and generated wrapper and fails closed if Seatbelt
is unavailable. It rejects nested shell interpreters. The wrapper may use ordinary host
resources outside `cwd` so Chromium can start; use it only for trusted deterministic
browser checks, never as a host- or device-wide read-only boundary.

## Configuration

Command-line options override these environment defaults:

```text
VERIFIED_DELIVERY_VERIFIER=auto
VERIFIED_DELIVERY_CLAUDE_MODEL=claude-opus-4-8
VERIFIED_DELIVERY_CODEX_MODEL=<optional versioned model>
VERIFIED_DELIVERY_OTHER_VERIFIER=codex
VERIFIED_DELIVERY_EFFORT=xhigh
VERIFIED_DELIVERY_TIMEOUT=600
```

For a multi-provider shell such as Cursor or Windsurf, pass its actual model provider
with `--author-provider`. This prevents a Cursor session using GPT from being incorrectly
routed back to Codex and labeled independent.

Same-provider verification is rejected unless the user explicitly approves the reduced
assurance and the caller passes `--allow-same-provider`.

## Test

The runner tests use fake CLIs, so they do not consume model credits:

```bash
python3 -m unittest discover -s tests -v
```

When the real CLIs are installed, the same suite also checks their current `--help`
output for every required safety/session flag. Two live end-to-end tests are opt-in
because they consume model credits:

```bash
VERIFIED_DELIVERY_LIVE_TESTS=1 python3 -m unittest discover -s tests -v
```

The live tests execute both Claude→Codex and Codex→Claude routing against a temporary
SSOT, require an independently attributed `completed` result, and require the verifier
response to contain `PASS`.

`evals/validate.py` remains a Claude Code trigger-quality harness for an installed
skill. `evals/evals.json` documents provider-routing workflow cases.

## Origin

Distilled from a native-iOS → Flutter parity pipeline where analytics events had to be
byte-identical and Codex independently verified Claude Code's plan and implementation.
That original path remains first-class; the delivery contract now works for any upstream
coding agent.

## License

MIT — see [LICENSE](LICENSE).
