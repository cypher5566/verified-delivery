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
Make sure it's installed and authenticated first. Run it from a dir containing **both**
the SSOT and the target, read-only — that dir is often a non-git common parent (e.g. when
the SSOT and target live in different repos/locations), so pass **`--skip-git-repo-check`**
(codex otherwise aborts with "Not inside a trusted directory") and redirect **`< /dev/null`**
(else codex blocks on "Reading additional input from stdin…" when backgrounded), pass
**`-o <verdict-file>`** (`--output-last-message`: codex writes ONLY its final message there —
that is the file you read afterwards), and bound it
with a portable hard timeout — **`perl -e 'alarm shift; exec @ARGV' 600`** (macOS ships no
`timeout`/`gtimeout`, but perl's `alarm` survives `exec`). Force
`model_reasoning_effort="high"` — independent verification is the whole point, so give it max
reasoning; don't pin `-m` (inherit your default codex model):
```bash
cd <dir-with-both> && perl -e 'alarm shift; exec @ARGV' 600 \
  codex exec --sandbox read-only --skip-git-repo-check \
  -c model_reasoning_effort="high" \
  -o <verdict-file> \
  "Verify each of these against <SSOT path/table> and the working tree, \
   reporting TRUE/FALSE/PARTIAL + a file:line (or table:column) citation: \
   <paste the uncertain-points list, or 'read <plan path>'>. Read-only. Be concise." \
  < /dev/null > <transcript-file> 2>&1; echo "EXIT=$?"
```
`codex exec` **buffers all output until it finishes** (both files read 0 bytes mid-run
— normal). Run it in the background, poll the transcript until it grows, then **read the
verdict file — never the transcript**. The transcript is the full reasoning dump (the
"Be concise" in the prompt is best-effort only: codex routinely ignores it and dumps tens
of KB, a prime driver of failed compactions in long agent sessions) plus an echo of your
own prompt — grepping it re-reads your own words. It stays on disk for forensics and must
not enter the caller's context. The verdict file is codex's final message only — normally
the TRUE/FALSE/PARTIAL list + verdict line, a couple of KB:
```bash
t=<transcript-file>; until [ "$(wc -c < "$t" 2>/dev/null || echo 0)" -gt 120 ]; do sleep 5; done
v=<verdict-file>
if [ -s "$v" ]; then cat "$v"; else
  # -o file missing/empty (crash, timeout, old codex) — size-gated extraction, never a blind cat
  sz=$(wc -c < "$t")
  echo "[no verdict file; extracting from ${sz}-byte transcript]"
  grep -anE 'TRUE|FALSE|PARTIAL|PASS|FAIL|VERDICT' "$t" | head -30
  tail -c 2500 "$t"    # codex writes its conclusions last
fi
```
If the verdict is ambiguous or truncated, pull the specific region from the transcript
with a targeted `grep -A/-B` or `sed -n 'X,Yp'` — never the whole file.
A 0-byte transcript + nonzero exit is usually a blocked telemetry write, not a failed analysis —
re-run with a shorter prompt if it truly wedges. The hard timeout above is **not optional**:
without it a wedged codex hangs forever and "still working" is indistinguishable from "dead" —
the runtime only signals on *completion*, which a hang denies, so "running in the background
already bounds it" is FALSE. `EXIT=142` = the timeout fired (shorten the prompt or retry);
output stuck tiny on "Reading additional input from stdin…" = the `< /dev/null` was dropped.
