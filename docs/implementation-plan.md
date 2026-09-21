# Implementation plan

This plan turns `jev_coding_contract_eval_FINAL_HANDOVER.md` into a staged V1 build. The project is an evaluation harness and pilot corpus for runtime-original explicit coding constraints. It compares deterministic checks, Jev on prefix-only evidence, and a deterministic-to-Jev hybrid. It does not include a hosted service, dashboard, database, extension, public API, or user-work repository data.

## V1 outcome

The first credible release should let a developer:

1. define a versioned case containing the original instruction surface, explicit constraints, normalized events, provenance, and independent labels;
2. replay any allowed prefix without future-derived information;
3. run deterministic oracles and cheap heuristics offline;
4. run Jev only through an explicit, pinned evaluator specification with content-addressed caching;
5. compute trajectory false-alert rate, detection, timing, cost, latency, and per-oracle breakdowns from stored results;
6. regenerate reports without an API key, subject to publication and licensing rules.

The initial evidence set is approximately ten development fixtures, then a stratified 30–50-case synthetic pilot if the smoke gates pass. Public traces and three to five controlled Codex sessions are later cohorts, not prerequisites for the first harness milestone.

## Non-negotiable measurement contract

- A constraint is normative text actually supplied at runtime. Record provenance separately for `user`, `developer`, `system`, `repo_policy`, and `harness` surfaces.
- A read-only observation is not a write violation. Reading a protected test file remains compliant unless the literal constraint forbids reading.
- Keep intent signal, attempt, effect, recovery, and first clear violation distinct. Do not infer a pre-effect interception boundary from an audit event alone.
- Each constraint has its own outcome and timing labels: `compliant`, `violated`, `ambiguous`, or `ungradeable`; first clear violation; first attempt/effect where supported; recovery; optional observable-risk label; rationale and evidence references.
- Oracle support is per case and constraint: `exact`, `conservative`, `partial`, `human`, `mixed`, or `none`. Unsupported telemetry returns unknown/ungradeable.
- A prefix may use only task/instruction context, declared starting context, events through the current event, and state derived from those inputs. Labels, final diffs, future events, and future summaries are excluded from evaluator input.
- Alerts are threshold crossings grouped into episodes for false-alert UX metrics. Do not count every repeated event in one unresolved episode as a separate interruption.
- The core V1 target is earliest observable violation detection. Prospective warning is exploratory and only scored when a pre-effect evidence window is independently defensible.

## Build sequence

### Gate 0: repository and publication posture

- [implemented] Create the Python 3.12+ package using a small dependency set (`pydantic` or dataclasses/schema tooling, CLI library, pytest; add analysis/plotting libraries only when needed).
- [implemented] Add `pyproject.toml`, formatter/linter/test configuration, `.gitignore`, `.env.example`, and a README with no unverified Jev claims. Choose the repository license later; do not invent one now.
- [implemented] Add `docs/methodology.md`, `docs/related-work.md`, and `docs/publication-policy.md` placeholders or initial content.
- [implemented] Keep raw/private traces and local caches ignored.
- [blocked on provider publication permission] Resolve the TypeSafe terms that apply to the user's account before publishing any Jev score, latency, cost, raw response, comparative chart, or benchmark statement. Until then, use public-harness/private-results mode. No live result or publication work was performed.

### Gate 1: schemas and canonical identity

Implement versioned schemas before adapters or live evaluation:

- `SourceProvenance`: source kind, URI/path where safe, license/redistribution status, raw hash, trace format, normalizer version, source metadata.
- `AgentMetadata`: harness/model/version, repository and base commit, environment, timestamps where available.
- `Constraint`: ID, verbatim text, normalized description, category, provenance, oracle kind/implementation/config/limitations.
- `InstructionSurface`: surface, event reference, exact text, precedence metadata for conflicts.
- `Task`: request, instruction surfaces, constraints.
- `Event`: stable ID, monotonic sequence, kind, actor, tool, status, side-effect class, path, command, arguments, text/result summary, timestamp, raw reference, source metadata. Use nullable/unknown fields instead of invented precision.
- `Case`: schema version, case ID, source, agent, task, ordered events, capabilities, cohort, sanitization/publication status.
- `GroundTruth`: per-constraint outcome and evidence/timing/annotation fields.
- `EvaluatorConfig`: evaluator/version, model, question spec, representation/projection, threshold, batching, routing, error policy.
- `EvaluationResult`: case/prefix/constraint IDs, evaluator/spec hashes, raw response reference, probability/decision, route, latency, usage, errors/abstention, and model resolution.
- `DatasetManifest` and `RunManifest`: source/case hashes, evaluator hash, git commit, environment, times, and run identity.

Define additive versus incompatible schema migration rules. Reject unknown schema versions, duplicate IDs, non-monotonic sequences, missing provenance, invalid references, and unsupported oracle declarations.

Implement canonical serialization with stable key ordering, UTF-8, line endings, event order, path normalization, explicit absent versus null behavior, and declared timestamp inclusion. Hash raw inputs, normalized cases, evaluator-visible prefixes, evaluator specs, and cached raw responses with SHA-256. Labels and future-derived metadata must never enter the prefix-state hash.

### Gate 2: synthetic source and first fixtures

Create a small synthetic trace format before writing a Codex parser. The first ten cases should cover:

- protected-path read allowed;
- protected-path write violated;
- only-one-file compliant and violated;
- no-new-dependencies compliant and violated;
- no-new-files compliant and violated;
- harmless mention of a forbidden action;
- multiple constraints with one satisfied and one violated;
- semantic/backward-compatibility case requiring human labeling.

Expand only after the harness works. The eventual pilot matrix should include compliant and near-miss negatives, recovery, ambiguity, multiple constraints, distracting events, contradictory instructions, adversarial repository/tool text, cases with no possible pre-effect warning, and cases with a real intent signal before the effect. Keep roughly half of development prefixes/cases non-violating or legitimate.

### Gate 3: deterministic oracles and offline replay

Implement an oracle registry with support assessment and prefix evaluation. Initial oracle families:

- normalized path write denylist;
- file create/delete lifecycle;
- command and git commit/push detection;
- dependency manifest/lockfile and install-command evidence;
- API/CLI surface comparison where case configuration defines the surface;
- test/validation evidence;
- human/none fallback.

Path handling must normalize separators, `.`/`..`, repository-relative and absolute paths, case semantics, and prefix collisions. Avoid substring matches and return unknown for unresolved symlink or missing-target semantics. Command checks should parse enough structure to document limitations around shell indirection, pipes, aliases, and hidden script effects. Distinguish exact final-state evidence from conservative online signals.

Build prefix construction with `normalized_raw` and `policy_projection_v1`. Add mechanical leakage tests: normalizing a raw trace truncated at N must byte-match requesting prefix N from the full trace; appending future events must not change the prefix; labels/future metadata must be inaccessible to evaluator inputs. Projection must be deterministic, versioned, tested, and independent of Jev.

### Gate 4: metrics and reports with fake results

Before any paid call, run the complete offline path: fixture → parser → normalized case → prefix → fake/cache evaluator → metrics → report.

Implement trajectory-level false-alert rate, false alert episodes per 100 eligible action events, violation detection rate, first detection and signed delay, conditional observable early-warning rate, per-constraint/per-category/per-oracle-support breakdowns, explicitly stored request/call counts, token/cost metadata, latency p50/p95, evaluator errors/abstentions, and trajectory-bootstrap uncertainty with small-sample suppression. Treat trajectory/case as the resampling unit; prefixes are correlated. Generate machine-readable JSON/CSV plus a concise Markdown report, and keep chart creation conditional on meaningful sample size. The offline implementation and focused tests are complete; calibration/Brier remains deferred because the current stored-row contract does not provide a guarded calibration sample.

Test the pathological monitor that alerts at event zero everywhere; it must not win through negative lead time alone.

### Gate 5: Jev adapter and cache

Re-verify the current official API, SDK, authentication variable, model ID, context/token limits, batching behavior, pricing, rate limits, and applicable terms at implementation time. The handover's research snapshot lists `jev-1.13.0`, the `Noul` primitive, `TYPESAFE_API_KEY`, and the `/v1/systemone` family; treat these as hypotheses to verify, not constants. A single authorized preflight/smoke request may verify connectivity, but the implementation plan assumes no further live Jev calls after that preflight; build and validate the harness offline with fake/cached responses.

Use atomic typed Noul questions for the primary binary violation signal. Freeze exact question text, criteria, state serialization, projection version, thresholds, missing-data behavior, retries, and batching in a versioned evaluator spec. Pin a concrete model ID and record requested/resolved IDs. Batch independent constraints sharing a prefix. Keep policy thresholds in ordinary code and retain raw model outputs separately from post-threshold decisions.

Cache keys must include evaluator/model/question/constraint/projection/request configuration versions and canonical evaluator-visible prefix hash. Default to cache reuse; require explicit `--force` for live re-evaluation. Never log or commit keys. Bound state size, omit binary/base64 blobs, and sanitize sensitive traces before API submission when required.

Offline cache integrity, corruption rejection, atomic writes, concurrent-writer handling, and cache-only replay are implemented and tested offline. This does not authorize or validate a live Jev call, and the provisional evaluator threshold remains descriptive rather than frozen.

### Gate 6: tiny development smoke test (historically claimed; not historically verified by artifact)

Connectivity alone does not validate Jev's semantic discrimination. Local private files record a reported pinned development smoke run with the planned balanced controls, both representations, cache identity checks, and the frozen evaluator specification. The files lack the current typed `RunManifest`, so `docs/run-history.md` records this as historically claimed, not historically verified by artifact. Its raw outputs and operational measurements remain private under the publication policy. One development iteration was reportedly allowed; no question or projection change was made. Fake or cached responses can validate plumbing only; they cannot pass this semantic gate.

### Gate 7: freeze, expand, and add cohorts

- Status `historically claimed; not historically verified by artifact`: freeze `jev-contract-monitor-v1` evaluator spec and hash before the private held-out synthetic run. The associated private run artifacts are excluded from release material; see [`run-history.md`](run-history.md).
- Status `historically claimed; not historically verified by artifact; not for further tuning`: add a separate 30-case stratified synthetic held-out cohort without reusing the 13 development smoke cases, and run it privately under the frozen evaluator. Its descriptive results are not public claims and remain unsuitable for tuning.
- [not started] Sample public datasets only after inspecting cards, licenses, schema, instruction fields, event fidelity, and a small sample. Accept a natural case only when the constraint genuinely existed at runtime and provenance is defensible. Keep user, repo-policy, system/scaffold, controlled, and synthetic cohorts separate.
- [not started] Implement only the public importer justified by a useful source. Do not bulk-download giant corpora.
- [blocked on human annotation] Do not spend controlled Codex sessions yet. The private held-out cohort is dominated by exact-oracle cases, so it cannot establish semantic incremental value; the six-case semantic development cohort is annotation-ready but remains ungradeable pending independent human labels. Resume this gate only after the annotation protocol produces independent semantic labels and a controlled-session protocol defines runtime constraints, clean open-source repositories, hashes, final state, telemetry limits, and a defensible observation boundary.

## Evaluator arms

Report arms separately:

1. exact/conservative deterministic checker, including oracle-circularity caveat;
2. simple keyword/path heuristic;
3. Jev on normalized raw prefix;
4. Jev on deterministic policy projection;
5. hybrid deterministic → Jev, logging route and skip reason.

An optional general LLM judge is deferred from V1 unless the completed experiment proves it answers a necessary question at low cost.

## CLI capabilities

The CLI may use different names, but must support these operations:

- `validate`: validate case files/manifests and references;
- `import`: stream and normalize a Codex `--json` JSONL trace or a supported public format;
- `inspect`: inspect a normalized trace safely;
- `sanitize`: redact likely secrets, paths, oversized blobs, and emit a sanitization report/publication flag;
- `annotate`: step through prefixes with compliant/violation/risk/ambiguous/ungradeable controls and save independent labels;
- `eval`: run deterministic, heuristic, Jev, projected, or hybrid evaluators; reuse cache by default and support `--force`;
- `plan-run`: estimate eligible prefixes, cached/live calls, tokens, and cost before network use;
- `report`: build all metrics from stored artifacts only;
- `release-check`: verify provenance, licenses, sanitization, publication terms, and absence of secrets.

Live evaluation should print a budget preflight and distinguish Jev API cost from scarce Codex session budget. Normal replay/report commands must never require a key or make network calls.

The current offline CLI includes `validate`, `inspect`, `sanitize`, `release-check`, `annotate`, `import`, `plan-run`, `eval`, and `report`. Jev cache-only evaluation uses `eval --evaluator jev-v2 --cache-dir`; live access requires explicit `--live`. The standalone ingestion, sanitization, annotation, cache, and reporting modules are usable without provider access. Final CLI regression remains an integration gate until the current hybrid report fixture is repaired.

## Repository shape

Keep the implementation boring and modular:

```text
src/contract_eval/{cli,schema,ingest,sanitize,constraints,oracles,replay,evaluators,cache,annotate,metrics,report}
configs/{evaluators,questions,reports}
fixtures/{synthetic,public,controlled}
raw/                         # ignored by default
annotations/
cache/                       # ignored unless approved
results/{manifests,runs,reports,charts}
scripts/{sample_public_data,verify_release}
docs/{methodology,schema,datasets,adjacent-work,publication-and-terms,threat-model}
tests/{schema,prefix_purity,oracles,rules,cache_keys,sanitizer,codex_adapter}
```

Avoid web frameworks, ORM/DB, queues, hosted APIs, auth, telemetry SaaS, and distributed workflow machinery.

## Verification and CI contract

Offline CI should run locked install, type/lint/format checks, schema tests, path/oracle self-tests, prefix leakage tests, cache identity tests, sanitizer tests, fixture validation, and an end-to-end fake-evaluator report smoke test. It must not require a live Jev key. Optional live smoke tests are manual, tiny, and budget-capped.

Current local status: the offline verification gate passes in the repository `.venv`: Ruff lint and format checks, full-package mypy, the full pytest suite, schema export, and semantic-development, synthetic, and heldout fixture validation. No hosted CI run has been performed.

Test invalid schema versions, duplicate IDs, unknown event references, non-monotonic sequences, path edge cases, shell limitations, unsupported telemetry, secret-like strings, private keys/bearer tokens, data URLs/base64, oversized/malformed JSONL, invalid UTF-8 policy, and metric hand calculations. Ensure report generation cannot make network calls.

## Deferred labels, gates, and unresolved decisions

These require evidence or user/account-specific facts and should remain explicit rather than guessed:

- TypeSafe benchmark-publication permission and what Jev outputs may be redistributed (currently unresolved; assume no public Jev results);
- billing/usage authorization for semantic Jev evaluation (a connectivity preflight is not sufficient evidence);
- current API/SDK request format, model/version, limits, price, rate limits, and auth variable;
- best public source containing runtime-original explicit constraints and whether its terms permit derived fixtures;
- whether repo policy constraints remain a separate cohort (default: yes);
- exact oracle support for each trace's telemetry;
- handling of ambiguous shell effects and conflicts in instruction hierarchy;
- whether any Codex event is a verified pre-execution boundary;
- final held-out split and false-alert budget;
- threshold-selection rule for Noul and whether projection changes reflect development-only evidence;
- treatment of adversarial state and representation sensitivity;
- whether an optional LLM judge is needed at all;
- whether the work deserves “benchmark” or should remain “evaluation harness + pilot corpus.”

Human labels and publication decisions are deliberately deferred until the harness can show the exact prefix and evidence. Do not use Jev to create ground truth. Do not retrofit constraints onto old natural traces. Do not publish performance numbers before Gate 0 is resolved.

## Completion criteria

V1 is ready for review when another developer can identify, for every case and evaluated prefix, the exact runtime constraint and provenance, ordered observable events, clear violation boundary, oracle support, deterministic/heuristic/Jev/hybrid decisions, evaluator representation/version, false-alert and timing consequences, cost/latency/error metadata, and source license/hash. Every generated report must be reproducible from stored artifacts without silently calling the API, and release checks must pass for all committed public fixtures.
