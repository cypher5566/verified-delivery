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

- Claude defaults to the versioned `claude-opus-4-8` model at `xhigh` effort.
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
VERIFIED_DELIVERY_CLAUDE_MODEL=claude-opus-4-8
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

## Result semantics

The runner's `status` describes execution, not correctness:

- `completed`: the verifier process exited successfully; inspect `response`.
- `failed`: the CLI, authentication, model, or provider failed.
- `timed_out`: the hard timeout ended the process.
- `dry_run`: selection and command construction were validated, but no gate ran.

Only an explicit passing response with sufficient citations can pass a gate. A failed
or timed-out invocation, empty response, ambiguous verdict, missing SSOT, or failing
deterministic test keeps the gate closed.

## Evidence and privacy

The runner sends prompts through stdin so they do not appear in process listings. It
stores a SHA-256 prompt hash instead of copying the prompt into result metadata. The
verifier response is stored because it is the audit evidence; choose the output path
accordingly if the response contains sensitive information.
