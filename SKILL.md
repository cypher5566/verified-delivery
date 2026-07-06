---
name: verified-delivery
description: "A high-assurance delivery loop for any change where being wrong is expensive — code OR data/analysis. An independent verifier (codex exec — different model, different blind spots) gates BOTH the plan (before any work) and the result (after), because the author can't catch the author's own bad assumptions. Everything is anchored to a named source of truth with file:line / table:column citations. Use whenever the user says: verified delivery, 走驗證流程, plan then codex then exec, codex 把關, 雙重驗證, 高保證, port/mirror an existing source, build something correctness-critical, or asks to verify a plan or an implementation against ground truth before shipping. Prefer this over an unverified one-shot whenever a wrong assumption would be costly to discover late."
user-invocable: true
---

# verified-delivery

A loop for shipping **one unit of work** with high confidence — a feature, a
migration, a tricky bugfix, or a metric / SQL / report. Same spine for code and data.

## Why (don't cut these)
1. **Two independent gates.** The reviewer is *not the author*. You're blind to
   your own bad assumptions, so `codex exec` checks twice: the **plan before you
   build** (catching a wrong assumption here is ~10× cheaper than after — the
   highest-leverage step), and the **result after**.
2. **Ground truth first, with citations.** Pull the exact contract from a named
   **SSOT** and cite it (`file:line` / `table:column` / the exact query). Keep
   what you *know* (defensible by citation) apart from what you're *guessing*.
3. **Question the ask.** The requested batch usually shouldn't ship whole. Tag
   each piece **do now / defer (why) / N/A (why)** before working.

## The loop

**1 — Ground & scope.** Name the SSOT (with its path) — the thing correctness is
judged against: the legacy implementation, a spec doc, a ground-truth table, an API
contract, a schema. Tag the batch (do/defer/N-A). Pull the contract with citations.
Write down **only the genuinely uncertain points** (defaults, ordering, edge cases,
timing/double-fire, gating) — everything else you should be able to defend with a
citation. Verify your assumptions about the *target* too, not just the source (a
derived view ≠ the business fact).

**2 — Gate 1: codex verifies the plan** (before you build). Pass the **original problem**
+ the SSOT pointer + your uncertain-points list **inline in the prompt** (write a file
only if the plan is too big to inline), and brief codex per **The verifier's brief**
(below) so it audits the frame — not just your list. Fold every correction in *before*
writing anything — codex routinely fixes defaults, surface mapping, timing, and whether
a thing exists at all.

**3 — Build.** Mirror the SSOT; deviate only for a documented reason. Then check your
*own* output against the SSOT before handing it over: tests + format the files you
changed (code), or re-run the query and reconcile against the SSOT, not a cache (data).

**4 — Gate 2: codex verifies the result → fix → integrate.** Confirm with the user
before changing code. Run codex on the diff / output vs the SSOT + plan **under the same
verifier's brief**; fix **every** correctness flag with a check per fix. Show the user
codex's `-o` verdict file here — not just your paraphrase, so
a flag can't be quietly waved off. Then integrate **per your team's convention** —
commit to the working branch, or open a PR; the loop is agnostic. If it's a production
change, remember commit ≠ deploy: push if that's how the deploy fires, and say plainly
whether it's live or only committed.

## The verifier's brief — audit the frame, not just your list
The default "verify each of these against the SSOT" makes codex a checker of *your*
list, so it inherits your blind spots — you drew the frame it looks through. Widen it:
hand codex the **original problem** and the **SSOT itself** (not only your plan), and
require these, adapted from the co-engineer-loop principles for a single-shot verifier:

- **P1 — solve the right problem.** Restate the original problem, then say whether the
  plan/diff actually solves *that*, not just whether it does what it claims. Stay within
  the named scope for line checks — flag a wrong-shape approach, don't redesign it.
- **P5 — ground every claim.** Trace each point to a citation in the SSOT / working tree;
  mark it **grounded signal** vs **unverified assumption**.
- **P2 — invariants first.** State the invariants the SSOT implies; flag a diff that is
  correct line-by-line but breaks one in composition.
- **P4 — fragile assumption first.** Attack the one assumption that, if false, collapses
  the whole change, before details — you run under a hard time cap.
- **P6 — name band-aids.** Flag anything that masks a deeper issue instead of fixing at
  the right layer, even if it matches the SSOT line-for-line.
- **Open sweep.** Then list anything wrong I did *not* ask about.

Drop co-engineer-loop's "friendly to the author" principle — codex has no author to
spare. Keep only its kernel: stay strict regardless of how confident or polished the
proposal looks; don't anchor on the author's framing.

Scope note: this hardens both gates against a biased or incomplete frame (the author
choosing what codex sees). It does **not** touch the other half — the author still reads
the verdict and could misreport or wave off a flag. Close that separately: surface
codex's `-o` verdict file to the user — never
just your paraphrase.

## codex, mechanically
This skill uses [codex](https://github.com/openai/codex) as the independent verifier.
Install + authenticate first. Run codex read-only from the source location — for a **single**
source, `cd` into that exact repo/dir by **absolute path**, not a broad common parent that also
holds look-alike siblings; for **cross-source** work (you can't `cd` into one) name each source
by absolute path and lean on the grounding guard below.

**Ground codex on the right source — and make it prove it.** A look-alike name (a `-test` /
`-staging` sibling, two repos one word apart) is a silent failure: codex reads the wrong source
and returns a confident PASS against the wrong ground — worse than no gate. So the brief must
require a one-line grounding preamble *before* any analysis, and stop on mismatch: for each
source, print an identifier names can't collide on — a git repo: `git -C <path> remote get-url
origin` + `rev-parse HEAD`; a database / dataset: the resolved connection + db/table name — and
report `MISMATCH` without analysing if any differs from what you specified. Disambiguate by that
fingerprint, never by directory name.

Pass **`--skip-git-repo-check`**
(non-trusted dirs), **`< /dev/null`** (non-TTY/agent shells pipe stdin — else codex stalls on
"Reading additional input from stdin…"), **`-o <verdict-file>`** (`--output-last-message`:
codex writes ONLY its final message there — that is the file you read afterwards), and
**`perl -e 'alarm shift; exec @ARGV' 600`** (hard cap; macOS has no `timeout`).
`-c model_reasoning_effort="high"`; don't pin `-m`:
```bash
cd <dir-with-both> && perl -e 'alarm shift; exec @ARGV' 600 \
  env CODEX_HOME="$HOME/.codex" \
  codex exec --sandbox read-only --skip-git-repo-check \
  -c model_reasoning_effort="high" \
  -o <verdict-file> \
  "Sources (absolute paths): <SSOT abs path>[, <other abs paths>]. FIRST print each source's \
   fingerprint (git repo: remote get-url origin + HEAD SHA; db/dataset: connection + db/table) \
   and STOP with MISMATCH — do not analyse — if any differs from these. Then, original problem: \
   <one line>. Audit the plan/diff against <SSOT> per the verifier brief: restate + judge whether \
   it actually solves the problem; per point report TRUE/FALSE/PARTIAL + a source-qualified \
   file:line (or table:column) citation and mark grounded-signal vs my-assumption; state the SSOT \
   invariants and flag any line-correct diff that breaks one; take the most fragile assumption \
   first; flag band-aids; then list anything wrong I did not ask about: \
   <paste the uncertain-points list, or 'read <plan path>'>. Read-only. Be concise." \
  < /dev/null > <transcript-file> 2>&1; echo "EXIT=$?"
```
`env CODEX_HOME="$HOME/.codex"` pins the verifier to the default Codex home,
overriding any `CODEX_HOME` inherited from the launching process.

Buffers until exit (empty files mid-run are normal). After the `EXIT=` line appears,
**read the verdict file, never the transcript**. The transcript holds the full reasoning
dump (tens of KB — the "Be concise" in the prompt is best-effort only; codex routinely
ignores it) plus an echo of your own prompt, so grepping it re-reads your own words;
it stays on disk for forensics and must not enter the caller's context. The verdict
file is the final message only — normally the TRUE/FALSE/PARTIAL list + VERDICT line,
a couple of KB:
```bash
v=<verdict-file>; t=<transcript-file>
if [ -s "$v" ]; then
  sz=$(wc -c < "$v")
  if [ "$sz" -le 4000 ]; then cat "$v"; else
    echo "[verdict: ${sz} bytes — tail only]"; tail -c 3000 "$v"
  fi
else  # -o file missing/empty (crash, timeout, old codex) — extract, never cat
  sz=$(wc -c < "$t")
  echo "[no verdict file; extracting from ${sz}-byte transcript]"
  grep -anE 'TRUE|FALSE|PARTIAL|PASS|FAIL|VERDICT' "$t" | head -30
  tail -c 2500 "$t"    # codex writes its conclusions last
fi
```
Ambiguous or truncated verdict → pull the specific region from the transcript with
targeted `grep -A/-B` or `sed -n 'X,Yp'`, never the whole file.
`EXIT=142` = timeout. Stuck on the stdin line = missing `< /dev/null`.
