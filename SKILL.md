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

**2 — Gate 1: codex verifies the plan** (before you build). Pass the SSOT pointer +
your uncertain-points list **inline in the prompt** (write a file only if the plan is
too big to inline). Fold every correction in *before* writing anything — codex
routinely fixes defaults, surface mapping, timing, and whether a thing exists at all.

**3 — Build.** Mirror the SSOT; deviate only for a documented reason. Then check your
*own* output against the SSOT before handing it over: tests + format the files you
changed (code), or re-run the query and reconcile against the SSOT, not a cache (data).

**4 — Gate 2: codex verifies the result → fix → integrate.** Confirm with the user
before changing code. Run codex on the diff / output vs the SSOT + plan; fix **every**
correctness flag with a check per fix. Then integrate **per your team's convention** —
commit to the working branch, or open a PR; the loop is agnostic. If it's a production
change, remember commit ≠ deploy: push if that's how the deploy fires, and say plainly
whether it's live or only committed.

## codex, mechanically
This skill uses [codex](https://github.com/openai/codex) as the independent verifier.
Install + authenticate first. Run from a dir with **both** the SSOT and the target, read-only
(often a common parent when they live in different repos). Pass **`--skip-git-repo-check`**
(non-trusted dirs), **`< /dev/null`** (non-TTY/agent shells pipe stdin — else codex stalls on
"Reading additional input from stdin…"), and **`perl -e 'alarm shift; exec @ARGV' 600`** (hard
cap; macOS has no `timeout`). `-c model_reasoning_effort="high"`; don't pin `-m`:
```bash
cd <dir-with-both> && perl -e 'alarm shift; exec @ARGV' 600 \
  codex exec --sandbox read-only --skip-git-repo-check \
  -c model_reasoning_effort="high" \
  "Verify each of these against <SSOT path/table> and the working tree, \
   reporting TRUE/FALSE/PARTIAL + a file:line (or table:column) citation: \
   <paste the uncertain-points list, or 'read <plan path>'>. Read-only. Be concise." \
  < /dev/null > <output-file> 2>&1; echo "EXIT=$?"
```
Buffers until exit (empty file mid-run is normal). Poll until `wc -c` > 120:
```bash
f=<output-file>; until [ "$(wc -c < "$f" 2>/dev/null || echo 0)" -gt 120 ]; do sleep 5; done; cat "$f"
```
`EXIT=142` = timeout. Stuck on the stdin line = missing `< /dev/null`.
