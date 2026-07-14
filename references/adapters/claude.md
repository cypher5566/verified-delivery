# Claude verifier adapter

Use this adapter when the author is Codex or when the user explicitly selects Claude.

## Defaults

```text
CLI: claude -p
Model: claude-opus-4-8
Effort: xhigh
Permission mode: plan
Tools: Read, Glob, Grep
Session persistence: disabled
Customizations: disabled with --safe-mode
```

The runner removes `CLAUDECODE` so a verifier can start even if its parent environment
came from Claude Code. `--safe-mode` disables project instructions, memory, skills,
hooks, plugins, and MCP servers; put every required rubric and contract pointer in the
gate prompt.

The adapter deliberately exposes no Bash or write tool. Place the SSOT and target under
the selected `--cwd`, or choose their closest safe common parent. If the verifier needs
a diff, create a current diff artifact inside that readable tree before running Gate 2.

Claude is invoked with JSON output. The runner extracts `result`, usage, and the actual
model reported by `modelUsage`. A successful CLI exit still does not imply a passing
verification verdict.

## Equivalent command

The runner constructs the equivalent of:

```bash
env -u CLAUDECODE claude -p --safe-mode \
  --model claude-opus-4-8 --effort xhigh \
  --permission-mode plan --tools Read,Glob,Grep \
  --no-session-persistence --output-format json
```

The prompt is supplied over stdin and the Python runner provides the hard timeout.
