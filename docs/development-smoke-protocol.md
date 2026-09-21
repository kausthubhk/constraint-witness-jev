# Jev development smoke protocol

This protocol defines the first authorized live development run. It is a
development diagnostic, not held out evaluation and not a publication result.
The cohort and request accounting are pinned in
`configs/evaluators/jev-development-smoke-v1.json`.

## Cohort

Use the 13 named synthetic cases in the config. They provide 14
case/constraint units and 19 observed event prefixes. The cohort contains
protected read and write controls, single file compliant and violating cases,
a new file violation, a harmless forbidden action mention, a git push
violation, recovery after a write, a multi constraint case, a semantic human
label case, a protected tests and git status control, and a genuine adversarial
state where repository text conflicts with the user constraint. The repository
file is read only and its independent label is compliant.

The independent labels in each fixture are the grading source. Jev responses
must never be used to create or revise those labels. The semantic pending case
and any `ungradeable`, `unknown`, or `ambiguous` label are retained for
diagnostic review and excluded from primary gradeable denominators.

## Requests and representations

For every selected case event prefix, submit one request containing all
constraints for that case. Run both `normalized_raw` and
`policy_projection_v1` over the same prefix set. This is 19 batched requests
per representation and 38 requests for the complete comparison. Record cache
key, evaluator specification hash, prefix state hash, requested and resolved
model IDs, response schema status, usage, latency, and any error or abstention.

The exact request question, model, threshold, state serializer, and event
selection policy come from the pinned Jev adapter specification. The threshold
is descriptive for this development smoke and must not be tuned on a held out
set. Raw responses and cache entries remain private.

## Preflight checks

Before network access, verify:

1. the synthetic manifest and every selected case validate;
2. all selected case IDs match the config, with no duplicate IDs;
3. the expected counts are 13 cases, 14 constraint units, and 19 prefixes;
4. each prefix state is generated from events through that event only, using
   the existing prefix purity invariant and test;
5. record the exact `evaluator_state_sha256` for every case, event, and
   representation;
6. raw and projected state hashes differ when free form payload fields exist;
7. no labels, future events, source metadata, or raw references occur in either state;
8. the API key is available to the process without printing or recording it;
9. the planned request count is 19 per representation, with cache hits shown separately.

## Decision checks

Compare same prefix and same constraint across representations. At minimum,
inspect protected read versus protected write, forbidden mention versus git
push, and the multi constraint case. A representation difference is a finding
to record, not a reason to silently choose the better looking result.

Stop live work if the provider is unavailable, responses do not satisfy the
pinned schema, state hashes do not match the submitted prefix, or obvious
compliant and violating controls do not separate under both representations.
One development iteration is allowed for a question or projection change.
Record the change and rerun only this development cohort; do not touch held
out data until the evaluator specification and hash are frozen.

## Reporting boundary

Generate a private machine readable run artifact and a private diagnostic
summary. Do not publish Jev scores, raw responses, latency, cost, or benchmark
claims until TypeSafe terms and publication permission are resolved. The smoke
run can complete while the publication gate remains closed.
