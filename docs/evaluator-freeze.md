# Evaluator freeze

`configs/evaluators/jev-contract-monitor-v1.json` freezes the executable Jev
evaluator identity used for the first held-out evaluation. Its SHA-256 value
is calculated from `contract_eval.jev.evaluator_spec()` and binds the adapter
ID, model, endpoint, Noul question template and criteria, and state
serialization version.

The frozen configuration carries both evaluator-visible representations,
`normalized_raw` and `policy_projection_v1`, the `all-observed-v1` event
selection policy, and the 0.7 development threshold. A change to the question
or either projection requires a new evaluator ID and another development
protocol; it must not be made against held-out cases.

The Gate 6 development protocol has been executed and its diagnostic record is
private. This document intentionally contains no live performance, latency,
cost, or provider-output data.

The associated development outputs, provider responses, cache records, and
cost and latency information remain private. Publication rights are still
governed by `docs/publication-policy.md`.
