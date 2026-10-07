# Claude verifier adapter

Use this adapter when the author is Codex or when the user explicitly selects Claude.

## Defaults

```text
CLI: claude -p
Model: claude-opus-5
Effort: model default (pass --effort to override)
Permission mode: dontAsk
Tools: Read, Glob, Grep
Session persistence: disabled
Customizations: disabled with --safe-mode
```

Only Read/Glob/Grep are allowed; write, shell, delegation, web, and
`ExitPlanMode` tools are denied in both the default and shell-enabled profiles. Using `dontAsk` instead of Claude's special `plan`
mode keeps the audit source-read-only while ensuring the complete report travels
through Claude's preserved final-result field.

The runner removes `CLAUDECODE` so a verifier can start even if its parent environment
came from Claude Code. `--safe-mode` disables project instructions, memory, skills,
hooks, plugins, and MCP servers; put every required rubric and contract pointer in the
gate prompt.

The default adapter deliberately exposes no Bash or write tool. Place the SSOT and target
under the selected `--cwd`, or choose their closest safe common parent. If the verifier
only needs a diff, create a current diff artifact inside that readable tree before
Gate 2, but outside every fingerprinted repo (or at an explicitly ignored path before
the first fingerprint). This keeps the evidence readable without changing the candidate
fingerprint.

For a Git-backed Result Gate whose PASS requires independent reproduction of hashes,
Git drift, or portable deterministic tests, opt in on the first attempt with
`--allow-readonly-shell` and repeat one exact `--shell-command` per check. This changes
the Claude permission mode to `dontAsk`, adds only those exact Bash approvals, and
enables Claude's native OS sandbox with:

- the entire `--cwd` tree deny-write;
- `autoAllowBashIfSandboxed: false`;
- `failIfUnavailable: true`;
- `allowUnsandboxedCommands: false`.

Shell separators, redirects, substitutions, and the `*` permission wildcard are
rejected. Keep pytest caches and bytecode disabled because the audited tree is genuinely
read-only. The profile remains opt-in: Plan Gates and Result Gates with sufficient
candidate-bound readable artifacts keep the smaller Read/Glob/Grep surface. `--output`
must resolve outside `cwd`, which also keeps the raw events sidecar outside the audited
tree.

Classify commands before approval. Host process tables, devices, keychains, host IPC,
and platform integration are `target-host` evidence even when the command itself looks
read-only; do not force them through the verifier sandbox. Bind sanitized author output,
exit status, and artifact hash to the frozen candidate, then ask Claude to audit that
evidence and the relevant source. A sandbox skip is not a pass, and a sandbox capability
failure is not automatically a candidate defect. The final report records each command
as EXECUTED_PASS, EXECUTED_FAIL, or UNAVAILABLE with candidate/environment/unknown scope.

Give the verifier a bounded review packet: acceptance criteria, source routing,
candidate fingerprint, exact test evidence, prior blocking findings, and explicit
non-goals. Prefer identifiers and focused ranges over invitations to read every changed
file or an entire large log. The runner's convergence guard uses roughly 20 evidence
tool calls as a synthesis checkpoint; unresolved material uncertainty becomes PARTIAL
instead of consuming the report budget until timeout.

For a Plan Gate, do not require planned new artifacts to exist before implementation.
Audit whether the plan names their integration points and proof. Treat citation
precision as blocking only when the referenced behavior cannot be located uniquely or
the ambiguity could change the material verdict.

The bundled `scripts/candidate_fingerprint.py` is a suitable exact command: it reads
Git metadata and file content to hash HEAD, index, staged/unstaged changes, and
untracked state without writing the worktree.

This is a `cwd` integrity boundary, not proof that an exact command cannot mutate an ADB
device, database, API, or other remote target. The caller must approve only semantically
read-only query commands.

Claude's native macOS sandbox blocks Chromium's Mach bootstrap ports. For a Playwright
command that fails specifically at browser launch, use `--macos-seatbelt-command`
instead of `--shell-command`. The runner turns it into an argv-only call through the
bundled `run_macos_seatbelt.py`, excludes only that wrapper from Claude's native
sandbox, and immediately reapplies a fixed macOS Seatbelt profile that deny-writes the
entire `cwd`. The underlying command never passes through `shell=True`; the wrapper and
requested argv are both recorded in result JSON. This option is macOS-only and fails
closed when `/usr/bin/sandbox-exec` is unavailable. Nested shell interpreters are
rejected. Seatbelt still permits ordinary host activity outside `cwd` for Chromium, so
only trusted deterministic browser commands belong in this path.

Claude is invoked with JSON output. The runner extracts `result`, usage, and the actual
model reported by `modelUsage`, then validates the complete-report envelope and overall
verdict. One complete envelope may be extracted from harmless non-verdict progress text;
the raw response and warning are preserved. Multiple envelopes, a verdict outside the
envelope, or an omitted/plan-transition-only report are recorded as failed. A complete
FAIL or PARTIAL report is preserved as `completed`, but the runner exits 4 and sets
`reported_gate_passed: false`.

On macOS the runner owns liveness with `/usr/bin/caffeinate -i --` by default and
records it in `power_assertion`; `--allow-system-sleep` is the explicit opt-out.

## Equivalent command

The runner constructs the equivalent of:

```bash
env -u CLAUDECODE claude -p --safe-mode \
  --model claude-opus-5 \
  --permission-mode dontAsk --tools Read,Glob,Grep \
  --no-session-persistence --output-format json
```

For a shell-enabled evidence gate, use the runner rather than reconstructing the longer
`dontAsk` + exact approvals + sandbox settings command by hand.

The prompt is supplied over stdin and the Python runner provides the hard timeout.

Every gate prompt is prefixed with the `<<verified-delivery-gate: ...>>`
role-handshake marker; a Claude-side copy of this skill recognizes it via the
SKILL.md role guard and stays in the verifier role instead of re-entering the
authoring loop. The runner also preserves raw verifier output at
`<output>.events.jsonl` for mid-run visibility and post-hoc audit.

The prompt also requires
`<<verified-delivery-report:start>> ... <<verified-delivery-report:end>>` in the final
response and forbids `ExitPlanMode`. Missing markers or a missing exact
`OVERALL VERDICT:` line keep the gate closed.
