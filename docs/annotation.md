# Offline annotation workflow

For a human-facing explanation of the labels and the two current review cases,
see [`annotation-guide.md`](annotation-guide.md).

`contract_eval.annotate` provides a small human-labeling workflow for cases
whose labels need review. It reads the task, initial instruction surfaces,
constraint text, and successive normalized event prefixes. It does not import
an evaluator and does not inspect evaluator results.

Use `annotation_prompts(case, constraint_id)` to render or inspect every
prefix. Use `build_ground_truth(case, constraint_id, answer)` to validate an
independent answer. Supported outcomes are `compliant`, `violated`,
`ambiguous`, and `ungradeable`; `unknown` remains available for schema
compatibility. Event timing fields must reference events in the case, and a
pre-effect warning requires a risk event before an effect event.

`collect_annotation` accepts a callback so a CLI or notebook can own the UI.
The callback receives the final prefix prompt and returns the human answer.
Existing fixture labels require `overwrite=True` explicitly. The source case
is never mutated.

`save_annotations` writes a separate canonical JSON artifact and refuses to
replace an existing output unless `overwrite=True` is supplied. This keeps
human labels separate from source fixtures and from evaluator outputs.
