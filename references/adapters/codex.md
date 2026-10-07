# Codex verifier adapter

Use this adapter when the author is Claude Code or when the user explicitly selects
Codex.

## Defaults

```text
CLI: codex exec
Model: configured Codex default, unless explicitly overridden
Reasoning effort: model default (pass --effort to override)
Sandbox: read-only
Session persistence: ephemeral
User config and rules: ignored after resolving the model
Output: JSONL
```

The runner removes `CODEX_THREAD_ID` and uses `--ephemeral` so every gate starts a new
session. It reads the configured model ID, passes that ID explicitly, then uses
`--ignore-user-config --ignore-rules` so unrelated MCP servers, hooks, and exec rules do
not influence the independent audit. Authentication still comes from `CODEX_HOME`.
`--skip-git-repo-check` supports a safe common parent that contains separate SSOT and
target repositories. The read-only sandbox remains the final write boundary.

Read-only does not imply target-host capability. Classify process-table, device,
keychain, host-IPC, platform-service, external, and privileged checks before the gate.
Run only portable checks inside the verifier sandbox; bind target-host output and hashes
to the frozen candidate for source audit. A sandbox skip is not a pass, and a capability
failure is not automatically a candidate defect.

The runner reads only the top-level `model` field from `$CODEX_HOME/config.toml`, then
pins that value for the gate so attribution survives the clean-config invocation. Pass
`--model <id>` or set `VERIFIED_DELIVERY_CODEX_MODEL` to override it. If neither the
config nor Codex reports a model, the runner records `configured-default` rather than
making an unsupported claim.

The runner extracts the last agent message and usage from Codex JSONL events, then
requires the complete-report envelope and one explicit overall verdict. A successful
CLI exit still does not imply a passing verification verdict. A complete FAIL or
PARTIAL report is preserved, but closes the process gate with exit 4.

The raw JSONL event stream is preserved at `<output>.events.jsonl` and written
live, so the audit trail (which files/commands the verifier ran, via `item.*`
events with `type: command_execution`) survives success and can be watched
mid-run with `tail -f <output>.events.jsonl`. Post-hoc:
`jq -r 'select(.item.type=="command_execution") | .item.command' <output>.events.jsonl`.

Every gate prompt is prefixed with the `<<verified-delivery-gate: ...>>`
role-handshake marker; a Codex-side copy of this skill recognizes it via the
SKILL.md role guard and stays in the verifier role instead of re-entering the
authoring loop.

The same prompt requires the final agent message to contain
`<<verified-delivery-report:start>> ... <<verified-delivery-report:end>>`; an omitted
or intermediate-only report fails closed.

## Equivalent command

The runner constructs the equivalent of:

```bash
env -u CODEX_THREAD_ID codex exec --sandbox read-only \
  --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules --json \
  -
```

The runner adds `--model <resolved-config-id>` when available. The prompt is supplied
over stdin, and the Python runner provides the hard timeout.
