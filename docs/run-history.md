# Run history

The repository contains private Jev result files under `results/private/` and
private cache records under `.jev-cache/`. They are not release artifacts.

The private development smoke and 30-case synthetic heldout result are
historical local records. Their result rows and diagnostic reports preserve
the evaluator specification hash, representations, row counts, and private
operational summaries, but they do not have the typed `RunManifest` contract
introduced by the current hardening work. Treat them as historical claims
until a manifest-aware verifier reconstructs and validates their identities.

The heldout configuration therefore remains pending/unknown for any new
evaluation. Do not rerun or retune against heldout V1. Do not publish scores,
raw provider responses, latency, cost, or comparative claims without resolving
provider permission and validating a release artifact.

No human labels were fabricated. The semantic development cohort remains
unlabeled and requires independent annotation before any new semantic study.
