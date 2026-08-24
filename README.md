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
| Codex / OpenAI | Claude Code (`claude-opus-5`, `xhigh`) |
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

The normal path is one plan review and one result review. A result PASS may contain
non-blocking follow-ups; optional polish does not keep the gate open. Another result
round is needed only when the verdict is non-passing or the candidate/contract changes.

It is intentionally heavier than a normal one-shot change. Use it when being wrong is
expensive and the error would otherwise be discovered late. The first-principles test
is proportionality: each extra round or permission must falsify a material assumption,
not merely produce more ceremony.

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
│   ├── candidate_fingerprint.py
│   └── run_verifier.py
├── tests/
│   ├── test_candidate_fingerprint.py
│   ├── test_cli_compatibility.py
│   └── test_run_verifier.py
└── evals/
```

`SKILL.md` owns the provider-neutral workflow. Adapter details are progressively loaded
only for the selected verifier. `run_verifier.py` performs provider selection, applies
read-only flags, wraps and supplies the prompt over stdin, enforces a hard timeout,
validates that the complete final report was preserved, and writes a normalized JSON
audit record. Both adapters suppress unrelated customizations; Codex's configured model
ID is resolved first and then pinned for the clean verifier process.

## Prerequisites

- Python 3.11 or later
- At least one authenticated verifier CLI:
  - [Claude Code](https://claude.com/claude-code), or
  - [Codex CLI](https://github.com/openai/codex)
- For automatic opposite-provider review, the verifier CLI must differ from the
  upstream author.

## Install

Install the entire directory because the skill depends on `references/` and `scripts/`.
Install it in exactly one directory scanned by your runtime. If Codex scans both
`~/.codex/skills` and `~/.agents/skills`, do not install the same skill in both places.
Keep evaluation workspaces and `skill-snapshot-*` baselines outside every active
skill-discovery root so they cannot be selected as executable skills.

If duplicate catalog entries already exist, compare each copy's resolved path plus Git
HEAD and dirty state when available, or content hash/provenance for a plain snapshot.
Preserve dirty or historical copies by moving them intact to an archive outside the
discovery roots; never overwrite them during cleanup.

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

The JSON `status: completed` means the CLI returned a structurally complete report; it
still does not mean the verifier passed the work. The final response must use:

```text
<<verified-delivery-report:start>>
[substantive findings and citations]
OVERALL VERDICT: PASS|FAIL|PARTIAL
<<verified-delivery-report:end>>
```

Exactly one complete envelope is required. Harmless non-verdict progress text before or
after it is tolerated and recorded as a warning while the raw response is preserved.
Multiple envelopes or any verdict outside the envelope fail closed. `OVERALL VERDICT:`
must occupy exactly one whole line with only `PASS`, `FAIL`, or `PARTIAL` after the
colon. A Markdown heading or paired bold wrapper around that line is accepted; trailing
commentary on the verdict line is not.

`report_validation` has the shape
`{"valid": bool, "verdict": "PASS|FAIL|PARTIAL"|null, "errors": [...],
"warnings": [...], "envelope_extracted": bool}`. It checks a single complete envelope,
a substantive body, and exactly one in-envelope overall-verdict line; it does not judge
whether citations or reasoning are correct. The field is present on success, failure,
timeout, configuration error, and dry-run payloads. `verified_report` contains the
extracted envelope when non-verdict text surrounds it.
Read `response` yourself and require an explicit, cited PASS. If a verifier puts
findings in an unpreserved plan transition or returns only "the details are above",
the runner preserves that response but returns `status: failed`.

Statuses and process exits are intentionally separate:

| Status | Meaning | Process exit |
|---|---|---:|
| `completed` + PASS | Structurally valid passing report returned | `0` |
| `completed` + FAIL/PARTIAL | Complete review returned; gate remains closed | `4` |
| `failed` | Configuration, provider, CLI, or report validation failed | `1` or `3` |
| `timed_out` | Hard timeout ended the verifier | `124` |
| `dry_run` | Routing/command construction only; no report | `0` |

Argparse usage errors use exit `2`. `verifier_verdict` records the parsed verdict and
`reported_gate_passed` is true only for PASS. Citation quality still requires the
author's inspection; this field prevents automation from confusing a finished review
with a passing review.

`gate_outcome_class` separates process outcomes without guessing the root cause inside
a verifier report: `gate_passed`, `gate_nonpassing`, `verifier_protocol`,
`verifier_infrastructure`, `verifier_timeout`, `configuration_error`, or `dry_run`.

Before the final result gate, freeze the candidate and record every in-scope repo's
remote + HEAD, staged/unstaged diff identity, and untracked-file state. Run final
tests/builds after that freeze and attach exact commands, exit status, and artifact
hashes. Any later source or contract edit invalidates the older evidence.

The bundled helper makes that evidence deterministic and read-only:

```bash
python3 scripts/candidate_fingerprint.py --repo /absolute/repo
```

Run it immediately before final checks and again before Gate 2. Matching
`candidate_sha256` values bind the evidence to the candidate; repeat it for every repo.
Fingerprint relevant or dirty submodules separately because a parent fingerprint knows
the gitlink and dirty marker, not the identity of uncommitted submodule changes.

Put any materialized diff artifact outside every fingerprinted repo under the readable
common `cwd`, or create it at an explicitly ignored path before the first fingerprint.
An untracked artifact created between fingerprints is candidate drift.

Build a bounded Result Gate packet: map each acceptance criterion to the smallest useful
set of production files, tests, and evidence artifacts; provide exact identifiers or
line ranges where practical; summarize large logs; and state non-goals. This lets the
verifier spend its fixed time attacking fragile assumptions and composing a durable
report instead of rediscovering the review surface.

Classify each check as `portable`, `target-host`, `external-readonly`, or
`privileged-live`. Only portable commands belong in the verifier's shell sandbox.
Target-host checks (for example process identity, device access, host IPC, or platform
integration) need same-fingerprint author output plus an artifact hash and verifier
source audit. A skipped host check is not a pass; it is a declaration that another
evidence domain must prove the criterion.
For a mixed-domain Gate, rerun every portable check and separately audit fresh
candidate-bound host/external/live evidence; neither half substitutes for the other.

Require the verifier to classify findings as `BLOCKING` or `NON-BLOCKING`. PASS can
carry non-blocking hardening ideas into a follow-up. If result verification has not
converged after two attempts on the same candidate/evidence profile, stop blind reruns
and classify candidate defect, environment mismatch, missing evidence, verifier
infrastructure/protocol, or scope creep/inconsistent judgment before making another
edit. Do not implement unrelated non-blocking polish while the gate is closed.

Claude uses `dontAsk` with only Read/Glob/Grep allowed by default. This avoids Claude's
special plan-transition channel without exposing write or shell tools. For a Git-backed
Result Gate that requires independent candidate-freshness, hash, or deterministic-test
checks that are portable in the verifier sandbox, opt in to exact commands on the first
attempt:

```bash
python3 scripts/run_verifier.py \
  --author codex \
  --verifier claude \
  --gate result \
  --cwd /path/to/common-parent \
  --prompt-file /tmp/result-gate.md \
  --output /tmp/result-gate.json \
  --allow-readonly-shell \
  --shell-command 'git -C /absolute/target-repo status --short' \
  --shell-command 'git -C /absolute/ssot-repo status --short'
```

The runner uses `dontAsk` plus exact approvals and Claude's native OS sandbox. The
entire `cwd` is deny-write, sandbox startup is mandatory, unsandboxed fallback is off,
and shell separators, redirects, substitutions, and the `*` permission wildcard are
rejected. This keeps evidence reproduction independent without turning the verifier
into a coding agent. Keep the smaller no-shell profile for Plan Gates and Result Gates
with sufficient candidate-bound readable artifacts. In shell mode, `--output` is
mandatory and must be outside `cwd`;
the result and its live `.events.jsonl` sidecar therefore cannot alter the audited tree.

Every real run, including the default no-shell profile, writes raw provider output to
`<output>.events.jsonl` (or a temporary external path when output is stdout). It may
contain the full verifier response, so protect it like the main audit JSON.

On macOS, the runner wraps the verifier with `/usr/bin/caffeinate -i --` by default and
records the decision in `power_assertion`. This prevents idle system sleep from silently
consuming a long gate without forcing the display awake. Use `--allow-system-sleep` for
an explicit opt-out.

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
VERIFIED_DELIVERY_CLAUDE_MODEL=claude-opus-5
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
