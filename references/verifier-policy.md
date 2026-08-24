# Verifier policy

Use this policy before either verification gate. Its purpose is to preserve
independence and make failures visible rather than merely finding any available model.

## Selection

| Author | `auto` verifier | Assurance |
|---|---|---|
| Codex | Claude Code | independent |
| Claude Code | Codex | independent |
| Other agent (Cursor, Windsurf, Gemini, Aider, etc.) | Codex when available, otherwise Claude | independent |

For Claude and Codex authors, `auto` checks only the required opposite-provider CLI.
It does not fall back to the author's provider when that CLI is missing or unavailable.
For a third-party model provider, either supported verifier is independent; `auto` prefers Codex
to preserve the original Claude-to-Codex audit experience and uses Claude only when the
Codex CLI is not installed. This is initial capability selection, not a retry after a
failed gate.

Multi-provider shells such as Cursor and Windsurf are not themselves model providers.
Pass `--author-provider anthropic`, `--author-provider openai`, or the actual provider.
The runner fails closed when it cannot infer this value because guessing could select
the same provider and falsely label the review independent.

An explicit same-provider verifier requires both user approval and
`--allow-same-provider`. The resulting JSON is labeled `reduced`; never describe it as
independent verification.

## Model policy

- Claude defaults to the versioned `claude-opus-5` model at `xhigh` effort.
- Codex resolves the user's configured model and pins it for a clean invocation at
  `xhigh` reasoning effort because Codex model identifiers change independently of this skill. Set
  `VERIFIED_DELIVERY_CODEX_MODEL` or pass `--model` when a versioned identifier is
  required for auditability.
- The runner reads only the top-level `model` field from Codex `config.toml` for
  attribution and passes it explicitly while ignoring the rest of user config; it does
  not copy other config values into the audit. When neither the
  config nor CLI reports a model, the result says `configured-default` rather than
  inventing an ID.
- There is no automatic fallback. If a model is unavailable, explicitly rerun with a
  named alternative and record why.

Environment defaults:

```text
VERIFIED_DELIVERY_VERIFIER=auto|claude|codex
VERIFIED_DELIVERY_CLAUDE_MODEL=claude-opus-5
VERIFIED_DELIVERY_CODEX_MODEL=<optional model id>
VERIFIED_DELIVERY_OTHER_VERIFIER=codex|claude
VERIFIED_DELIVERY_EFFORT=xhigh
VERIFIED_DELIVERY_TIMEOUT=600
```

Command-line values override environment values.

## Gate contract

Every gate prompt should name:

1. whether it is the plan gate or result gate;
2. the SSOT and readable target paths;
3. the claims or uncertain points to check;
4. the accepted plan for the result gate;
5. deterministic test evidence;
6. any applicable `docs/RUBRIC.md` axes.

Ask for a per-item `TRUE`, `FALSE`, or `PARTIAL` verdict, reasoning, and citations.
Missing evidence must remain uncertainty rather than being guessed into a pass.
For a result gate, include every repo's frozen candidate fingerprint and bind the
test/build evidence to it. Require findings to be classified `BLOCKING` or
`NON-BLOCKING`; PASS may contain non-blocking follow-ups, while PARTIAL is reserved for
material uncertainty.

For a Plan Gate, evaluate the proposed behavior, integration points, and planned proof.
A new file, test, helper, or copy key described by the plan is expected to be absent
before implementation. Its absence is not blocking unless the plan leaves its role,
integration, or acceptance proof materially ambiguous. Citation precision is blocking
only when the evidence cannot be located uniquely or the ambiguity could change the
verdict; otherwise narrower line ranges are non-blocking polish.

For Result Gates, route each acceptance criterion to the smallest useful set of
production files, tests, and evidence artifacts. Include exact identifiers or line
ranges where practical, summarize large logs, and state non-goals. The verifier should
stop gathering optional evidence once a claim can be classified and reserve time for
the complete report; unresolved material evidence is PARTIAL, not a reason to read until
the hard timeout.

Classify each criterion and deterministic command before Gate 2 as `portable`,
`target-host`, `external-readonly`, or `privileged-live`. Portable commands are the only
ones reproduced through the native verifier sandbox. Target-host checks such as process
identity, device access, host IPC, or platform integration must instead have sanitized
output, exit status, and artifact hash tied to the frozen candidate, plus source audit.
External/live checks require explicit authorization and freshness metadata. A skipped
check is never a pass; it declares which other domain must supply the proof.
When a gate spans domains, require dual proof: rerun every applicable portable check in
the verifier sandbox and separately audit fresh candidate-bound target/external/live
evidence. Neither evidence source replaces the other.

Claude source audits default to `dontAsk` with only Read/Glob/Grep allowed; this avoids
Claude's plan-transition channel while exposing no write or shell tool. If a result
gate on a Git-backed candidate specifically requires independent freshness, hash, or
portable command reproduction, the caller should opt in on the first attempt to the runner's
read-only shell profile with one exact, non-compound command per approval.
Separators, redirects,
substitutions, and the `*` permission wildcard are rejected. The profile is fail-closed:
Claude runs in `dontAsk`, the full `cwd` is OS-level deny-write, sandbox startup must
succeed, and unsandboxed retry is disabled. This is evidence execution, not permission
to modify the target. Plan Gates and Result Gates with sufficient candidate-bound
readable artifacts retain the smaller no-shell profile. The result path and live event
sidecar must resolve outside `cwd`.

The invariant is scoped to the audited tree. Exact ADB, database, cloud, or network
commands can still mutate external targets, so approve only semantically read-only
queries and never infer device- or host-wide read-only behavior from this profile.
Do not pass host-specific commands merely because their spelling is read-only: sandbox
capability is part of reproducibility.

On macOS, Playwright/Chromium can require Mach IPC that Claude's native sandbox blocks.
Use `--macos-seatbelt-command` only for that exact browser command. The bundled argv-only
wrapper runs outside the native sandbox and immediately reapplies a fixed Seatbelt
`cwd` deny-write boundary. Nested shells are rejected. The wrapper can use normal host
resources outside `cwd` to launch Chromium; it is not a general unsandboxed escape hatch
or a host-wide read-only sandbox.

## Result semantics

The runner's `status` describes execution, not correctness:

- `completed`: the verifier process exited successfully and returned a structurally
  complete report; inspect `response`. An explicit PASS exits `0`; a structurally
  complete FAIL or PARTIAL exits `4` so shell automation keeps the gate closed.
- `failed`: the CLI, authentication, model, provider, or final-report validation failed.
- `timed_out`: the hard timeout ended the process.
- `dry_run`: selection and command construction were validated, but no gate ran.

Only an explicit passing response with sufficient citations can pass a gate. A failed
or timed-out invocation, empty response, ambiguous verdict, missing SSOT, or failing
deterministic test keeps the gate closed.

For every approved command, require the report to record its evidence domain,
`EXECUTED_PASS`/`EXECUTED_FAIL`/`UNAVAILABLE`, and whether any failure is attributable to
the candidate, environment, or remains unknown. An environment mismatch is not an
automatic candidate failure, but unresolved material evidence still produces PARTIAL.

Every wrapped prompt requires the full final report between
`<<verified-delivery-report:start>>` and
`<<verified-delivery-report:end>>`, with a substantive body and exactly one
`OVERALL VERDICT:` line.
The runner validates this envelope after provider parsing. Exactly one complete envelope
may be extracted from harmless non-verdict progress narration; the raw response and a
warning remain in JSON. Multiple envelopes, any verdict outside the envelope, a missing
body, or a summary such as "the details are above" becomes `status: failed`.

`report_validation` is present on every normalized payload. Before a report completes,
or on configuration/provider/timeout failure, it is
`{"valid": false, "verdict": null, "errors": [...]}`.
`verifier_verdict` repeats the parsed verdict at the top level and
`reported_gate_passed` is true only for PASS. These fields make the process outcome
machine-readable without pretending to validate the quality of citations.

On macOS, the runner wraps the verifier with `/usr/bin/caffeinate -i --` by default and
records the assertion as `power_assertion`. The minimal idle-system-sleep assertion does
not force the display awake. Use `--allow-system-sleep` only for an intentional,
recorded opt-out. Sleep prevention protects liveness; it does not turn a timeout or
incomplete report into a pass.

## Evidence and privacy

The runner sends prompts through stdin so they do not appear in process listings. It
stores a SHA-256 prompt hash instead of copying the prompt into result metadata. The
verifier response is stored because it is the audit evidence; choose the output path
accordingly if the response contains sensitive information.
