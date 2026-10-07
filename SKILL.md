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
read-only review alone and reply with the report the gate brief defines, ending
with an overall PASS/FAIL/PARTIAL.

Without that marker, you are the author: run the loop below.

## Why this works

1. **Independent review where blind spots are expensive.** The author does not review
   its own assumptions. The tier decides which gates run: a plan challenge before work
   begins when the risk is in the design, a result review before integration always.
2. **Ground truth first.** Name the single source of truth (SSOT) and cite it with
   `file:line`, `table:column`, an API contract section, or the exact query.
3. **Scope before motion.** Tag each requested item `do now`, `defer (why)`, or
   `N/A (why)` so an invalid batch does not become an invalid implementation.
4. **Fail closed.** A missing verifier, timeout, CLI error, ambiguous verdict, or
   unavailable model is not a passed gate.

## Proportional friction

Use this loop when a wrong assumption would be expensive to discover late. The goal is
not the most ceremony; it is the smallest independent evidence loop that can falsify
the risky assumptions. A gate must distinguish product correctness from protocol,
environment, and citation-format problems so operational noise does not masquerade as
a product defect. Do not change verifier model or add review rounds without evidence
that the existing route is the source of a material miss.

## Before the loop

### Resolve the active installation

If the skill catalog exposes more than one `verified-delivery`, resolve the ambiguity
before running a gate. There must be exactly one active checkout across all directories
the runtime scans for skills. For every duplicate, inspect its resolved path plus Git
HEAD and dirty state when it is a checkout; for a plain snapshot, record its content
hash or provenance instead. Do not assume identical names mean identical content.

Keep one current, clean canonical checkout active. Never overwrite or delete a dirty
duplicate: move it intact to an archive outside every skill-discovery root. Keep eval
workspaces and `skill-snapshot-*` baselines outside directories named `skills` as well;
they are evidence, not executable installations. If a single active checkout cannot be
identified without losing local work, keep the gate closed and report the ambiguity.

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

### 0. Pick the tier

The reviewer exists to find what a different model sees, not to certify paperwork. Spend
reviewer runs where a blind spot is expensive:

| Tier | Typical change | Reviewer runs |
|---|---|---|
| 1 — ordinary fix | Bounded code change with deterministic tests | Result review only: one run on the frozen diff + test output |
| 2 — concurrency, ordering, data shape, shared state | Async/callback races, queues, caches, app-logic migrations | One plan challenge before building (fold its scenarios in; do not rerun it), then one result review |
| 3 — irreversible or privileged-live | Production schema/data mutation, credential rotation, a destructive deploy step | Plan review until PASS, precondition record before execution (3a), then result review |

Pick the lowest tier that covers the riskiest part of the change and state it in the
first request. Raise the tier when a review finds an irreversible or cross-system risk.
Run the reviewer in the background while you run your own tests.

**Run budget.** Each completed review counts once. Protocol failures (timeout, missing
envelope, fingerprint drift that does not touch the reviewed content) are tooling
defects: fix the invocation and rerun without counting it, and never treat them as a
verdict. The budget is per delivery, not per candidate: a rerun after a fix counts, so
fix → refreeze → review cannot loop forever. After two counted runs of the same gate in
one delivery, stop rerunning:
fix the remaining blocking scenarios with a test each and decide yourself with an
explicit asymmetric-risk rationale (which failure would hurt the user more if the
reviewer is right). Tell the user the gate was closed by author decision and why. At
tier 3 the author never closes the gate alone: after two counted runs without PASS,
stop and give the user the open scenarios and your recommendation.

**Blocking means a concrete scenario.** The runner's brief requires every blocking
finding to name the trigger, the observable harm, the location, and the smallest check
that would show it. Evidence format, provenance, citation precision, and fingerprints
are protocol notes and never block. Fix a real scenario with a test; answer a protocol
note with tooling or a one-line clarification, not another review round.

**Use the reviewer early when the root cause is uncertain.** Before choosing a fix, one
plan-gate run that challenges the root-cause hypothesis (what would falsify it, what else
explains the symptom) is the cheapest, highest-leverage use of a second model.

### 1. Ground and scope

Name the SSOT with its path or identifier. Pull the contract with citations. Separate
facts supported by the SSOT from genuine uncertainties such as defaults, ordering,
edge cases, timing, double-fire behavior, gating, and target-system differences.

Tag the requested batch `do now`, `defer`, or `N/A`. Verify assumptions about the
target too: a derived view is not automatically the underlying business fact. State
the acceptance criteria, invariants, and explicit non-goals before Gate 1. This gives
the verifier a materiality boundary: strict on correctness, quiet about optional polish.

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
- the tier, and the risks you most want challenged.

Do not add your own output format: the runner's brief defines the report shape, and
competing format demands make reports longer without finding more.

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

`status: completed` means only that the verifier CLI returned a complete report. Read
`response` and require an explicit passing verdict supported by citations. The runner
also records `report_validation`; a missing report envelope or overall verdict fails
closed even when the provider exits successfully. `reported_gate_passed` is true only
for an explicit `PASS`; `FAIL` and `PARTIAL` preserve the complete report but exit 4 so
automation cannot mistake a finished review for an open gate. Fold every blocking
correction into the plan before writing the implementation. At tier 2 the plan
challenge runs once: fold each blocking scenario in with a planned test and build; the
result review checks the folded fixes. Only tier 3 reruns the plan gate until PASS.

Plan Gate evaluates a future specification. A file, helper, test, or copy key that the
plan explicitly proposes to create is expected to be absent before implementation.
Treat absence as blocking only when the plan omits its integration point, behavior, or
proof. Citation precision is blocking only when the evidence cannot be located uniquely
or ambiguity could change the material verdict; a request for a tighter range around an
already unique identifier is non-blocking.

### 3. Build and self-check

Mirror the SSOT and deviate only for a documented reason. Check the result yourself:

- code: run relevant tests and formatting for changed files;
- data: rerun the query and reconcile against the SSOT rather than a cache;
- both: record deterministic evidence and remaining uncertainty.

Freeze the intended candidate before final evidence. For every repo in scope, record a
candidate fingerprint: remote + HEAD, staged/unstaged diff identity, and untracked-file
state. Then run final tests/builds and record exact commands, exit status, and artifact
hashes against that fingerprint. A source or contract change invalidates older evidence;
rerun affected checks instead of carrying a green result forward.

Generate the fingerprint without changing the worktree:

```bash
python3 <skill-root>/scripts/candidate_fingerprint.py --repo <repo>
```

Run it once immediately before final deterministic checks and again when preparing
Gate 2; the `candidate_sha256` values must match. Repeat it for every repo in scope.
Treat each relevant or dirty Git submodule as a separate in-scope repo: the parent
fingerprint records its gitlink and dirty marker, not the identity of internal changes.

Before running final checks, assign every acceptance criterion and command to an
evidence domain. Put the matrix in the Result Gate request:

| Domain | What belongs here | Required proof |
|---|---|---|
| `portable` | Checks needing only the audited tree and ordinary sandbox capabilities | The verifier reruns the exact command against the frozen candidate |
| `target-host` | Process tables, host IPC, devices, keychains, platform services, or host-specific integration | The author runs it on the target host, saves exit status/output/hash outside the repo, and binds it to the same candidate; the verifier audits both evidence and source |
| `external-readonly` | Database, cloud, or API queries that are semantically read-only but depend on external state | Record endpoint/identity/time and sanitized result; rerun only when authorization and freshness permit |
| `privileged-live` | Checks requiring credentials, production access, mutation risk, or user interaction | Never infer permission; use scoped author evidence or stop with material uncertainty |

A skip is not a pass. It only declares that another evidence domain must prove that
criterion. Do not force target-host, device, or live checks into the verifier sandbox,
and do not weaken a production invariant merely to make a portable profile green.
Conversely, author evidence cannot replace a portable rerun when the verifier can
reproduce it safely.

Use dual proof when one Result Gate spans domains: every fresh Gate 2 after an evidence
profile correction must both rerun all applicable portable checks in the verifier
sandbox and audit fresh candidate-bound evidence for every target-host/external/live
criterion. Neither half substitutes for the other.

Do not let a model verdict override a failing deterministic test.

### 3a. Before an irreversible privileged-live step (tier 3)

Gate 2 runs after the fact: for a one-shot production mutation it can record a skipped
precondition but cannot undo it. Immediately before executing such a step, write a
precondition record outside every fingerprinted repo and keep it with the Gate 2
evidence:

| Accepted-plan precondition (quoted, with plan line) | Exact check executed now | Raw result artifact | MATCH / DEVIATION |
|---|---|---|---|

Fill one row for every precondition the accepted plan names, plus one row binding the
target identity (project/host/ref) to the exact command and file hash about to run.
Execute only when every row is MATCH. A check weaker than, narrower than, or different
from the planned one is a DEVIATION even when its result looks safe. On a DEVIATION,
hold: amend the plan and rerun Gate 1, or get the user's explicit approval of that
specific deviation and record it in the row. While executing, append the executed
command, target identity, file hash, start/end time, and attempt count to the record.

### 4. Gate 2: verify the result

Prepare a fresh result-gate request containing the accepted plan, SSOT, changed paths
or diff artifact, the candidate fingerprint for every repo, test/build evidence tied to
that candidate, prior-gate findings when this is a rerun, and any applicable rubric.
Make it a bounded review packet: list the acceptance criteria, route each claim to the
relevant production files, tests, and evidence artifacts, cite exact identifiers or
line ranges where practical, summarize large logs instead of asking the verifier to
read them in full, and name explicit non-goals. Do not ask for a line-by-line review of
every changed file when a smaller set of invariants proves the result.

Start a new verifier process; do not resume Gate 1's session. The runner's brief asks
for one open sweep in which every finding is BLOCKING (a concrete scenario: trigger,
harm, location, check), NON-BLOCKING, or a PROTOCOL NOTE. `PASS` may include
non-blocking findings and protocol notes. `PARTIAL` is only for something that could not
be inspected and could hide a blocking scenario, not a wishlist.

At tier 3, also ask for an evidence-command table for every requested command: domain,
execution status (`EXECUTED_PASS`, `EXECUTED_FAIL`, or `UNAVAILABLE`), and failure
scope (`candidate`, `environment`, or `unknown`). A verifier-sandbox limitation is not
by itself a candidate defect.

If the verifier needs a materialized diff artifact, create it before the first
fingerprint either outside every fingerprinted repo under the readable common `cwd`,
or at an explicitly ignored path. Never add an untracked artifact inside a fingerprinted
repo between the two fingerprint runs; the artifact itself would create candidate drift.

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

Claude verification is source-read-only by default. For a Git-backed Result Gate whose
PASS depends on independently checking candidate freshness, artifact hashes, or
portable deterministic commands, use the explicit evidence profile on the first Gate 2
attempt.
This avoids a predictable PARTIAL caused only by withholding evidence capability:

```bash
  --allow-readonly-shell \
  --shell-command 'git -C /absolute/target-repo status --short' \
  --shell-command 'git -C /absolute/ssot-repo status --short' \
  --shell-command 'git -C /absolute/target-repo diff --check' \
  --shell-command 'python3 -m pytest -p no:cacheprovider -q <frozen-tests>'
```

Use one exact, non-compound command per flag and include cache/bytecode-off options where
needed. Shell separators, redirects, substitutions, and the `*` permission wildcard are
rejected. The runner changes Claude to `dontAsk`, deny-writes the entire `cwd` through
the native OS sandbox, requires sandbox startup, and disables unsandboxed fallback. This
is a narrow portable evidence-reproduction profile, not a broader authoring mode. Only
pass commands classified `portable`; host-specific commands belong in
fingerprint-bound artifacts instead. Keep it off for Plan Gates and when readable,
candidate-bound artifacts are sufficient. Put
`--output` outside `cwd`; the runner rejects
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

Fix every blocking correctness flag and add a check for each fix. While the gate is
closed, do not implement non-blocking findings unless they are directly required to
diagnose or fix the blocker; that is scope expansion, not convergence. Defer
non-blocking findings by default once the candidate has passed; implementing them
mutates the candidate and legitimately requires fresh evidence and Gate 2. The normal
path is one Plan Gate and one Result Gate. Rerun Gate 2 only after a non-passing verdict
or a candidate/contract change.

The run budget in step 0 applies (two counted runs per gate per delivery). When a run
does not pass, classify the cause before another code edit or model rerun:

- `candidate-defect`: the same check fails on the author/target environment or source
  proves the invariant is broken — fix code, refreeze, rerun affected evidence;
- `evidence-environment-mismatch`: the verifier lacks a declared host/device/network
  capability — fix the evidence matrix/profile, not production behavior, then rerun
  the portable subset and audit fresh candidate-bound target evidence;
- `missing-evidence`: collect the smallest candidate-bound proof that could change the
  material verdict;
- `verifier-infrastructure-or-protocol`: fix invocation, model availability, timeout
  routing, or report-envelope delivery without pretending a judgment occurred;
- `scope-creep-or-inconsistent-judgment`: restore the accepted materiality boundary and
  carry all prior grounded findings into the next fresh review.

One diagnostic replay may confirm an environment mismatch; never use repeated model
runs as a substitute for changing the faulty input. A protocol-only rerun is uncounted;
a rerun after a candidate fix is counted. Neither erases earlier
findings.

The same convergence rule applies to a corrected Plan Gate. If one corrected full retry
contradicts a prior complete judgment on unchanged evidence, do not keep sampling until
a PASS appears. Preserve both reports and allow one bounded adjudication that compares
the exact disputed claim against the SSOT and materiality boundary. If it cannot resolve
the conflict with cited evidence, the gate remains PARTIAL and the user sees the real
uncertainty.

Integrate only within the user's authorization and the team's convention. Commit is
not deploy; state plainly whether the change is local, committed, pushed, deployed, or
merely reviewed.

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
- Effort is not pinned: by default the runner passes none, so the model's own default
  applies (the 2026-10 replay benchmark found low and medium equal on recall). Pass
  `--effort medium` at tier 3, or when a run demonstrably missed a scenario; record why.
- Preserve each gate's JSON result. It records verifier, requested and observed model,
  effort, prompt hash, duration, exit status, response, report validation, and whether
  the reported verdict passed. A structurally complete `FAIL`/`PARTIAL` exits 4.
- Treat `timed_out`, `failed`, missing citations, and ambiguous responses as non-passing.
- Require each Result Gate to cover all repos and the exact candidate that produced its
  deterministic evidence. Passing evidence from an older candidate is not evidence.
- PASS ends the gate even when the open sweep contains non-blocking follow-ups. Do not
  churn a passing candidate merely to make the verifier's wishlist empty.
- Never recover omitted findings from conversational context. If a verifier says its
  report is "above", refers to an unpreserved plan transition, or omits the report
  envelope, keep the gate closed and rerun only after fixing the verifier path.
- Accept exactly one complete report envelope even when harmless non-verdict progress
  narration surrounds it. Preserve the raw response and warning. Multiple envelopes,
  any verdict outside the envelope, or a missing substantive body still fail closed.
- On macOS, the runner owns a minimal `caffeinate -i` assertion by default so idle
  system sleep cannot
  silently consume a gate attempt. `--allow-system-sleep` is the explicit, recorded
  opt-out.
