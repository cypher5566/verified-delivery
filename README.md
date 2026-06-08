# verified-delivery

A [Claude Code](https://claude.com/claude-code) skill for shipping correctness-critical
changes with high confidence. An **independent verifier** ([codex](https://github.com/openai/codex))
gates **both your plan and your finished result** — because the author can't catch the
author's own bad assumptions.

> **plan → codex verifies → build → codex verifies → fix → integrate**

It works for code (a feature, a migration, a tricky bugfix, a port) and for
data/analysis (a metric, a SQL change, a report). The spine is the same.

## Why this exists

Strip away any specific project and only three things make this valuable:

1. **Two independent gates.** Having "a review" isn't the point — having a reviewer
   who is *not the author* is. You're blind to your own bad assumptions, so a
   different model (codex — different training, different blind spots) checks twice:
   the **plan, before you build** (catching a wrong assumption here is ~10× cheaper
   than after you've built on it — the single highest-leverage step), and the
   **result, after**.
2. **Ground truth first, with citations.** Before touching anything, pull the exact
   contract from a named **source of truth (SSOT)** and cite it (`file:line`,
   `table:column`, or the exact query). Keep what you *know* (defensible by a citation)
   apart from what you're *guessing*.
3. **Question the ask.** The requested batch usually shouldn't ship whole. Tag each
   piece **do now / defer / N-A** before working, so you never build against a surface
   that doesn't exist or a case that never fires.

It does **not** make you faster. It makes you wrong less often — and wrong *early*,
when it's cheap.

## When to use it

Use it when **both** are true: (1) being wrong is expensive and would be discovered
late, and (2) there's a checkable source of truth. Good fits: metric/SQL changes that
feed a dashboard, cache-vs-source reconciliations, production hotfixes with blast
radius, ports where output must match a source exactly, schema migrations.

Skip it for: read-only questions, auditing an existing artifact, throwaway scripts,
cosmetic edits, renames, plan-only asks, and plain debugging where you don't yet know
the fix. For a 5-line obvious, reversible change, the plan gate costs more than it's
worth.

## Prerequisites

- [Claude Code](https://claude.com/claude-code)
- [codex CLI](https://github.com/openai/codex), installed and authenticated
  (`codex` on your `PATH`; any default model is fine — the skill forces high reasoning
  effort per-call)

## Install

Copy the skill into your Claude Code skills directory:

```bash
mkdir -p ~/.claude/skills/verified-delivery
cp SKILL.md ~/.claude/skills/verified-delivery/SKILL.md
```

## Using it

It triggers on intent, not just a magic word. Any of these will start it:

- "Port this analytics event to the new app, the props must match the old one — plan
  first, then have codex verify before I implement"
- "This changes production billing logic; do the kind where the plan gets verified and
  the result gets verified"
- "走驗證流程 …" / "plan then codex then exec …" / "double-check both my plan and the
  implementation before I ship"

Or invoke it directly: `/verified-delivery`.

## Validating triggering

Skill descriptions are the trigger mechanism, so triggering quality is measurable.
`evals/validate.py` runs each query in `evals/trigger-eval.example.json` against the
**installed skill** once and computes a confusion matrix (precision / recall / accuracy)
plus the misclassifications:

```bash
python evals/validate.py --skill verified-delivery --eval evals/trigger-eval.example.json
```

> **Note:** test triggering against the *real installed skill* like this, not via a
> harness that registers a temp copy — if the skill is already installed under its base
> name, the model fires the real one and a name-matching harness can silently report 0%.

## Origin

Distilled, from first principles, out of a native-iOS → Flutter **parity port** pipeline
(where analytics events had to be byte-identical and a second model verified both the
plan and the implementation). The project-specific scaffolding — worktrees, a specific
repo, a PR step, a specific event contract — was deleted; what survived is the
transferable kernel above.

## License

MIT — see [LICENSE](LICENSE).
