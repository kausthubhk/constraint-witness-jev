# Jev API contract

Verified on 2026-09-20 against TypeSafe's official documentation.

- Evaluation endpoint: `POST https://api.typesafe.ai/v1/systemone`.
- Authentication: `Authorization: Bearer <API_KEY>` and JSON request bodies.
- Required request fields: `state`, `model`, and a map of typed `questions`.
- This evaluator sends one atomic Noul question per constraint in a single request so every question shares the same evaluator-visible prefix state.
- Noul answers have `type: "noul"` and a `noul` probability in `[0, 1]`.
- The evaluated model is pinned to `jev-1.13.0`; a response resolving to another model is rejected as model drift and recorded only when it matches the pin.
- Model documentation on this date lists $0.042 per million input tokens and free output tokens. Account credits and future prices are not inferred from that price.

The adapter is offline by default. It only makes a request when a caller provides a transport and explicitly enables network access. Its private cache stores the exact evaluator request, raw response, request/response hashes, and an executable evaluator-spec hash. It is independent of the provisional `0.70` alert threshold, so thresholds can be recomputed offline. The caller must sanitize evaluator state before calling the adapter; these private request artifacts can contain trace content.

`configs/evaluators/jev-v2.json` is a descriptive development snapshot, not executable adapter configuration. The adapter exposes its actual request specification through `evaluator_spec()` and records its hash with every cache entry.

Sources: [API reference](https://docs.typesafe.ai/api), [models reference](https://docs.typesafe.ai/models).
