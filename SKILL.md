---
name: verified-delivery
description: "A provider-neutral, high-assurance delivery loop for correctness-critical code or data changes. An independent verifier from a different provider gates both the plan and the finished result against a named source of truth with file:line or table:column evidence. Use whenever the user says verified delivery, 走驗證流程, Claude/Codex 把關, plan then verify then build, 雙重驗證, 高保證, port or mirror an existing source, or asks to verify a plan and implementation before shipping. Prefer this whenever a wrong assumption would be expensive to discover late."
---

# verified-delivery

Ship one correctness-critical unit of work with two independent gates. The author may
be Codex, Claude Code, or another agent; the verifier should be a different provider
with different blind spots.

## Role guard — are you the author or the verifier?

This skill installs identically on every AI CLI, so the agent hired as the
*verifier* may find its own copy and keyword-match the request back into this
skill. That would re-enter the loop as an author and try to recruit yet another
verifier — an infinite mirror.

**If the prompt begins with a `<<verified-delivery-gate: ...>>` marker, you are
the VERIFIER inside someone else's run.** The loop is already running; this
skill's workflow is not for you right now. Do not run the loop, do not recruit
another verifier, do not consult this skill further. Perform the requested
read-only audit alone and reply with per-item verdicts, citations, and an
overall PASS/FAIL/PARTIAL.

Without that marker, you are the author: run the loop below.

## Why this works

1. **Independent gates.** The author does not review its own assumptions. Gate 1 checks
   the plan before work begins; Gate 2 checks the result before integration.
2. **Ground truth first.** Name the single source of truth (SSOT) and cite it with
   `file:line`, `table:column`, an API contract section, or the exact query.
3. **Scope before motion.** Tag each requested item `do now`, `defer (why)`, or
   `N/A (why)` so an invalid batch does not become an invalid implementation.
4. **Fail closed.** A missing verifier, timeout, CLI error, ambiguous verdict, or
   unavailable model is not a passed gate.

## Before the loop

Determine the current upstream coding agent or provider, such as `codex`, `claude`,
`cursor`, `windsurf`, `gemini`, or `aider`. Then read
[`references/verifier-policy.md`](references/verifier-policy.md). Read only the adapter
selected by that policy:

- Claude verifier: [`references/adapters/claude.md`](references/adapters/claude.md)
- Codex verifier: [`references/adapters/codex.md`](references/adapters/codex.md)

Use the bundled `scripts/run_verifier.py` instead of reconstructing provider commands
by hand. It selects the opposite provider, enforces read-only flags and a hard timeout,
and records attributable JSON evidence.

## The loop

### 1. Ground and scope

Name the SSOT with its path or identifier. Pull the contract with citations. Separate
facts supported by the SSOT from genuine uncertainties such as defaults, ordering,
edge cases, timing, double-fire behavior, gating, and target-system differences.

Tag the requested batch `do now`, `defer`, or `N/A`. Verify assumptions about the
target too: a derived view is not automatically the underlying business fact.

### 2. Gate 1: verify the plan

Prepare a concise verification request containing:

- the original problem, restated in one line (the verifier audits the frame, not
  just your list — see the brief the runner injects);
- the SSOT path or identifier, plus expected source fingerprints (git remote +
  HEAD SHA, or resolved db/table) whenever look-alike paths or siblings exist;
- the scoped plan;
- the uncertain-points list;
- the target paths the verifier may read;
- `docs/RUBRIC.md` when the working or driving repo defines it;
- a request for `TRUE`, `FALSE`, or `PARTIAL` per item with citations.

Run the independent verifier before implementing:

```bash
python3 <skill-root>/scripts/run_verifier.py \
  --author <upstream-agent-or-provider> \
  --author-provider <actual-model-provider-if-agent-is-multi-provider> \
  --verifier auto \
  --gate plan \
  --cwd <dir-containing-ssot-and-target> \
  --prompt-file <gate-1-prompt.md> \
  --output <gate-1-result.json>
```

`status: completed` means only that the verifier CLI ran successfully. Read `response`
and require an explicit passing verdict supported by citations. Fold every correction
into the plan before writing the implementation.

### 3. Build and self-check

Mirror the SSOT and deviate only for a documented reason. Check the result yourself:

- code: run relevant tests and formatting for changed files;
- data: rerun the query and reconcile against the SSOT rather than a cache;
- both: record deterministic evidence and remaining uncertainty.

Do not let a model verdict override a failing deterministic test.

### 4. Gate 2: verify the result

Prepare a fresh result-gate request containing the accepted plan, SSOT, changed paths
or diff artifact, test evidence, and any applicable rubric. Start a new verifier
process; do not resume Gate 1's session.

```bash
python3 <skill-root>/scripts/run_verifier.py \
  --author <upstream-agent-or-provider> \
  --author-provider <actual-model-provider-if-agent-is-multi-provider> \
  --verifier auto \
  --gate result \
  --cwd <dir-containing-ssot-and-target> \
  --prompt-file <gate-2-prompt.md> \
  --output <gate-2-result.json>
```

Claude verification is source-read-only by default. If Gate 2 stays non-passing solely
because Claude must reproduce deterministic commands rather than read their artifacts,
rerun with the explicit evidence profile:

```bash
  --allow-readonly-shell \
  --shell-command 'git status --short' \
  --shell-command 'git diff --check' \
  --shell-command 'python3 -m pytest -p no:cacheprovider -q <frozen-tests>'
```

Use one exact, non-compound command per flag and include cache/bytecode-off options where
needed. Shell separators, redirects, substitutions, and the `*` permission wildcard are
rejected. The runner changes Claude to `dontAsk`, deny-writes the entire `cwd` through
the native OS sandbox, requires sandbox startup, and disables unsandboxed fallback. This
is an evidence-reproduction escape hatch, not a broader authoring mode; keep it off when
readable artifacts are sufficient. Put `--output` outside `cwd`; the runner rejects
stdout-only or in-tree result/event artifacts in this mode.

The boundary protects the audited `cwd`, not a remote device, database, API, or every
host path. Approve only semantically read-only commands and keep ADB/database/cloud
checks query-only.

If a macOS Playwright command alone fails because Claude's native sandbox blocks
Chromium Mach IPC, pass that one exact command as `--macos-seatbelt-command` instead.
The runner uses a bundled argv-only wrapper and a fixed external Seatbelt profile that
still deny-writes the full `cwd`; it records both requested argv and wrapper and rejects
nested shell interpreters. Chromium may still use host resources outside `cwd`, so only
approve trusted deterministic browser tests. Never reclassify a browser-launch sandbox
failure as a product pass.

Fix every correctness flag and add a check for each fix. Rerun deterministic checks
and Gate 2 until both pass. Integrate only within the user's authorization and the
team's convention. Commit is not deploy; state plainly whether the change is local,
committed, pushed, deployed, or merely reviewed.

## Assurance rules

- Opposite-provider verification is the default: Claude author → Codex verifier;
  Codex author → Claude verifier. Other upstream agents prefer Codex when available,
  then Claude; both are independent of a genuinely third-party author.
- Multi-provider shells such as Cursor and Windsurf must pass their actual upstream
  model provider through `--author-provider`; the shell name alone cannot prove
  independence.
- `auto` never silently falls back to the author's provider. If independence is
  unavailable, stop and report the blocked gate.
- Same-provider verification requires explicit user approval plus
  `--allow-same-provider`; label the result `reduced`, not independent assurance.
- Do not add an automatic model fallback. A deliberate retry must name and record the
  replacement model.
- Preserve each gate's JSON result. It records verifier, requested and observed model,
  effort, prompt hash, duration, exit status, and response.
- Treat `timed_out`, `failed`, missing citations, and ambiguous responses as non-passing.
