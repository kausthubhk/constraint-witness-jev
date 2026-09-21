# Offline publication safety

The publication safety helpers are deliberately library-only so importing or
sanitizing a trace cannot make a network request or read a credential file.

## Bounded ingestion

`contract_eval.ingest.iter_jsonl_records(source, ...)` reads a binary JSONL
source one line at a time. It enforces `max_line_bytes` and `max_records`,
rejects malformed JSON and non-object records, and rejects invalid UTF-8 by
default. Callers may explicitly use `invalid_utf8="skip"`; replacement
decoding is not supported because it would change evidence. Each yielded
`JsonlRecord` includes its original one-based line number.

The CLI `import` command can stream these records into normalization without
materializing the raw trace. `read_jsonl_bounded` is available for small,
already-approved fixtures and retains the same limits.

## Sanitization

`contract_eval.sanitize.sanitize_value` returns a JSON-compatible copy and
records redactions in `SanitizationReport`. It detects bearer/private-key and
common credential assignments, absolute paths, data URLs, long base64-like
values, oversized strings, and oversized collections. The report retains
finding categories but never retains the original sensitive value.

The sanitizer is a conservative publication filter, not a proof that a trace
contains no personal or proprietary information. Human review remains needed
for publication decisions.

## Release check

`check_publication_value` fails when sanitization would change the candidate.
`check_case_publication` additionally fails when source redistribution
permission is not explicitly `true` or when a source license is absent. A raw
hash is evidence identity and does not grant publication rights.

The future CLI `release-check` command should return a nonzero exit status for
any `ReleaseCheck` with `passed == False`, and should print issue codes plus
paths/categories only. It should not print raw candidate values.
