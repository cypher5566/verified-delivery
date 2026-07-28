# Claude verifier adapter

Use this adapter when the author is Codex or when the user explicitly selects Claude.

## Defaults

```text
CLI: claude -p
Model: claude-opus-5
Effort: xhigh
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

When a result gate cannot pass because the verifier must independently reproduce hashes,
Git drift, or deterministic tests, opt in with `--allow-readonly-shell` and repeat one
exact `--shell-command` per check. This changes the Claude permission mode to `dontAsk`,
adds only those exact Bash approvals, and enables Claude's native OS sandbox with:

- the entire `--cwd` tree deny-write;
- `autoAllowBashIfSandboxed: false`;
- `failIfUnavailable: true`;
- `allowUnsandboxedCommands: false`.

Shell separators, redirects, substitutions, and the `*` permission wildcard are
rejected. Keep pytest caches and bytecode disabled because the audited tree is genuinely
read-only. The profile is opt-in so normal source review keeps the smaller Read/Glob/Grep
surface. `--output` must resolve outside `cwd`, which also keeps the raw events sidecar
outside the audited tree.

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
verdict. A successful CLI exit with an omitted or plan-transition-only report is
recorded as failed. A complete FAIL or PARTIAL report is preserved as `completed`, but
the runner exits 4 and sets `reported_gate_passed: false`.

## Equivalent command

The runner constructs the equivalent of:

```bash
env -u CLAUDECODE claude -p --safe-mode \
  --model claude-opus-5 --effort xhigh \
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
