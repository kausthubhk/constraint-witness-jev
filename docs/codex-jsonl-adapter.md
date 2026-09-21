# Codex JSONL adapter

`contract_eval.codex_jsonl.import_codex_jsonl` consumes bounded UTF-8 JSONL
from `codex exec --json`. It requires a `CodexCaseContext` containing the
runtime-original task request, instruction surfaces, and constraints. It does
not infer constraints from agent messages, tool output, or later repository
state.

The adapter maps only the documented `item.started` and `item.completed`
`command_execution` examples and completed `agent_message` items. It records
all other envelope or item forms as `unknown`; it does not infer paths, file
effects, or tool side effects from them. Command lifecycle observations are
audit events and never evidence of a pre-execution interception boundary.

The official non-interactive-mode documentation describes the JSONL envelope
types and shows command execution and agent-message items:
[OpenAI Developers documentation](https://developers.openai.com/docs/non-interactive-mode).

The importer is library-only. CLI integration should call
`import_codex_jsonl(source, context, max_line_bytes=..., max_records=...)` and
write the returned `Case` only after the caller has independently supplied and
validated its provenance context.
