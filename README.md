# Jev Coding-Contract Evaluation

This repository is an evaluation harness and pilot corpus for explicit coding-agent constraints such as “do not modify tests,” “only change `src/`,” or “ask before pushing.” It replays ordered traces prefix by prefix and is designed to compare deterministic checks, semantic Jev decisions, and a hybrid policy.

The project asks which constraints ordinary code can enforce exactly, and where semantic judgment may add useful signal under a practical false-alert and cost budget. Ground truth is independent of Jev, and evaluator prefixes cannot see future events. The six-case semantic development cohort is annotation-ready, but it has no finalized human labels.

The initial release is a local, GitHub-first Python project. It does not require a hosted service, dashboard, database, public API, or private work repository. The current build focuses on schemas, canonical serialization, synthetic fixtures, deterministic oracles, prefix-purity tests, and offline reporting. Jev calls are optional and governed by the publication policy.

## Development

Python 3.12+ is supported. CI runs Python 3.12; Python 3.14.2 is the current local workspace runtime.

```text
python -m pip install -e ".[dev]"
python -m contract_eval --help
```

The current offline development slice is usable without provider credentials. It can be exercised with:

```text
python -m pytest
python -m ruff check src tests
python -m ruff format --check src tests
python -m contract_eval.schema_export --check
python -m contract_eval validate fixtures/synthetic
python -m contract_eval validate fixtures/heldout
python -m contract_eval validate fixtures/semantic-development-v1
python -m contract_eval inspect fixtures/synthetic/dev-01-read-protected.json
python -m contract_eval plan-run fixtures/synthetic --evaluator jev-v2 --representation normalized_raw --cache .jev-cache/jev-contract-monitor-v1
python -m contract_eval eval fixtures/synthetic --evaluator rules-v1 --out results/runs/rules-v1.jsonl
python -m contract_eval import trace.jsonl --context runtime-context.json --out case.json
python -m contract_eval annotate case.json --constraint C1 --annotator-id annotator-1 --out labels.json
python -m contract_eval eval fixtures/synthetic --evaluator jev-v2 --cache-dir .jev-cache/jev-contract-monitor-v1 --out results/runs/jev-cache-only.jsonl
python -m contract_eval report --run results/runs/jev-cache-only.jsonl --cases fixtures/semantic-development-v1 --annotations labels.json --out-dir results/reports/annotated
python -m contract_eval release-check fixtures/synthetic
```

Regenerate the checked-in public JSON Schema bundle after changing a record:

```text
python -m contract_eval.schema_export
```

The rules evaluator writes an immutable local JSONL run and performs no network calls. Use a new output path for each run, then build an offline report with `python -m contract_eval report --run <run.jsonl> --cases fixtures/synthetic --out-dir <report-dir>`. Cache-only Jev uses the standard path and never falls back to the network: `python -m contract_eval eval fixtures/synthetic --evaluator jev-v2 --cache-dir .jev-cache/jev-contract-monitor-v1 --out <jev-run.jsonl>`. Add `--live` only for a separately authorized provider run. The held-out V1 material is historical/possibly consumed and is not available for further tuning. The semantic-development cohort is annotation-ready, but independent human labels are still required. Jev smoke and heldout files present locally do not establish a new semantic claim. Public Jev results remain gated by [`docs/publication-policy.md`](docs/publication-policy.md).

`plan-run` estimates prefixes, constraints, potential semantic calls, and cache hits without network access or provider authorization. `sanitize <candidate.json> --out <sanitized.json>` applies the offline redaction filter. `release-check <case-or-directory>` fails closed when content or redistribution permission is unresolved. See [`docs/annotation-guide.md`](docs/annotation-guide.md), [`docs/controlled-run-protocol.md`](docs/controlled-run-protocol.md), and [`ACTION_REQUIRED.md`](ACTION_REQUIRED.md) for the human-gated steps.

`annotate <case.json> --constraint <id> --annotator-id <id> --out <labels.json>` starts the separate human annotation workflow. It writes a label artifact and never edits the source fixture or evaluator results. Reports can consume overlays with `python -m contract_eval report --run <run.jsonl> --cases fixtures/semantic-development-v1 --annotations <labels.json> --out-dir <report-dir>`; heldout quality notes can be supplied with `--dataset-quality configs/datasets/heldout-v1-quality.json`.

`import <trace.jsonl> --context <runtime-context.json> --out <case.json>` imports a bounded Codex JSONL trace only when the caller supplies the original task, instruction surfaces, and constraints. It never infers labels or publication rights and refuses to overwrite an existing case.

`release-check <case-or-directory>` checks case provenance and sensitive content. Provider-derived run/report artifacts remain private until their publication permission is explicitly resolved.

## Scope and status

The handover specification is in [`jev_coding_contract_eval_FINAL_HANDOVER.md`](jev_coding_contract_eval_FINAL_HANDOVER.md). The implementation sequence and acceptance criteria are in [`docs/implementation-plan.md`](docs/implementation-plan.md).

The repository currently makes no real-world or Jev performance claim. Any future result must use a pinned evaluator specification, preserved provenance, independently labeled cases, and the publication gate described in [`docs/publication-policy.md`](docs/publication-policy.md).
