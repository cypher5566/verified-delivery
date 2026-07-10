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

## Rubrics（非確定性面的評分）

If the repo you are working in — or the repo **driving** the work (cross-repo sessions) —
defines `docs/RUBRIC.md`, fold its axes into **every** codex gate prompt and require
per-item verdicts with citations: design-decision gates append the decision rubric,
retrospective/completeness reviews append the audit rubric, and the anti-reward-hacking
rules always ride along. Deterministic gates (tests / exit codes) remain the final stop
condition; the rubric catches direction/scope/evidence defects machines can't.

## codex, mechanically
This skill uses [codex](https://github.com/openai/codex) as the independent verifier.
Make sure it's installed and authenticated first. Run it from a dir containing **both**
the SSOT and the target, read-only — that dir is often a non-git common parent (e.g. when
the SSOT and target live in different repos/locations), so pass **`--skip-git-repo-check`**
(codex otherwise aborts with "Not inside a trusted directory") and redirect **`< /dev/null`**
(else codex blocks on "Reading additional input from stdin…" when backgrounded), and bound it
with a portable hard timeout — **`perl -e 'alarm shift; exec @ARGV' 600`** (macOS ships no
`timeout`/`gtimeout`, but perl's `alarm` survives `exec`).

**Force `model_reasoning_effort="xhigh"`, but don't pin the model.** Independent
verification is the whole point, so always give the verifier max reasoning — `xhigh` is the
ceiling of the effort ladder and never goes stale, so pin it hard (the skill used to force
`high`, which on a modern codex config is a silent *downgrade*). The **model**, though, you
leave to `-m`-off so the gate inherits your codex default: the day you bump
`~/.codex/config.toml` to a newer model, this gate picks it up automatically — no skill
edit, always the latest. Override `-m` only when you deliberately want a specific verifier:

| Pass | When |
|---|---|
| *(omit `-m`)* — **default** | Inherit your codex config's default model. Auto-tracks the latest as codex ships new models. |
| `-m gpt-5.6-sol` | Force today's strongest verifier, regardless of what config says. |
| `-m gpt-5.5` | When the user asks for it, **or** as a fallback if the inherited model is unavailable / rate-limited (see the failure note below). |

State which model actually ran in your gate report — codex prints it at startup — so the
verification is attributable and a silent downgrade can't hide.

```bash
cd <dir-with-both> && perl -e 'alarm shift; exec @ARGV' 600 \
  codex exec --sandbox read-only --skip-git-repo-check \
  -c model_reasoning_effort="xhigh" \
  "Verify each of these against <SSOT path/table> and the working tree, \
   reporting TRUE/FALSE/PARTIAL + a file:line (or table:column) citation: \
   <paste the uncertain-points list, or 'read <plan path>'>. Read-only. Be concise." \
  < /dev/null > <output-file> 2>&1; echo "EXIT=$?"
```
To pin a specific verifier instead of inheriting the default, add `-m gpt-5.6-sol` or
`-m gpt-5.5` on the `codex exec` line (keep `-c model_reasoning_effort="xhigh"` either way).
Don't fold `-m` into a `#` comment inside the command — the `\` line-continuations collapse
the block into one logical line, so a mid-command `#` would swallow the prompt and redirect.
`codex exec` **buffers all output until it finishes** (the file reads 0 bytes mid-run
— normal). Run it in the background, then poll until it grows:
```bash
f=<output-file>; until [ "$(wc -c < "$f" 2>/dev/null || echo 0)" -gt 120 ]; do sleep 5; done; cat "$f"
```
A 0-byte file + nonzero exit is usually a blocked telemetry write, not a failed analysis —
re-run with a shorter prompt if it truly wedges. The hard timeout above is **not optional**:
without it a wedged codex hangs forever and "still working" is indistinguishable from "dead" —
the runtime only signals on *completion*, which a hang denies, so "running in the background
already bounds it" is FALSE. `EXIT=142` = the timeout fired (shorten the prompt or retry);
output stuck tiny on "Reading additional input from stdin…" = the `< /dev/null` was dropped.

**Model fallback.** If the inherited default model fails for an *availability* reason — a fast
nonzero exit whose output names the model / rate-limit / access (distinct from the telemetry
false alarm above and from `EXIT=142`, which is the timeout, not the model) — re-run the same
command with the model pinned to an available one (`-m gpt-5.5`, still `xhigh`) and note the
fallback in your gate report. Don't fall back on a real correctness failure or a timeout;
those aren't the model's fault.
