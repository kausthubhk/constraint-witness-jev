# Controlled run protocol

This protocol is a future collection gate. Do not run it as part of the
offline implementation task.

1. Use an open-source repository with a known URL and base commit SHA.
2. Verify a clean working tree and record runtime and tool versions.
3. Preserve the exact user, developer, system, repository-policy, and harness
   instruction surfaces supplied at runtime.
4. Record explicit constraints before the run and collect a machine-readable
   `codex exec --json` trace.
5. Record the final repository state and diff only when legally usable.
6. Declare telemetry capabilities, compute the raw source SHA, and compute the
   normalized evidence SHA independently.
7. Annotate the trajectory independently after collection. The annotator must
   not see Jev predictions, provider scores, or cache contents.
8. Replay every scored prefix and verify that its state contains only evidence
   available through that prefix.
9. Begin with 3–5 paired runs only after importer validation, independent
   annotation, and the publication gate pass.

For a paired study, use the same repository and base commit:

- A: normal task request;
- B: the same task with the explicit constraint under study.

Do not infer a verified pre-effect boundary from a lifecycle event alone.
Record unresolved telemetry as incomplete rather than treating missing
evidence as compliance.
