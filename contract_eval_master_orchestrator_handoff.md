# Contract-Eval — Master Orchestrator Handoff

## Purpose

This file is the durable handoff for a **new main orchestration session**.

The user will start a new ChatGPT Web orchestration chat and attach:

1. this Markdown handoff file; and
2. the **three newest Repomix XML snapshots** generated from the current live repository.

The new orchestrator must treat this file as the authoritative description of the user's workflow preferences, the division of labor between Web ChatGPT and Codex, the project execution sequence, Repomix snapshot/versioning discipline, work already completed, known protocol findings, current pending work, and the style of prompts to send to Web sub-agents versus Codex.

This handoff converts the user's instructions across the whole prior conversation into persistent operating rules. Do **not** infer the workflow from the most recent agent output alone.

---

# 1. Non-negotiable operating model

## 1.1 Main orchestration happens in ChatGPT Web

The main ChatGPT Web session is the primary orchestrator and reasoning layer.

It is responsible for:

- understanding the project from Repomix snapshots and returned sub-agent outputs;
- deciding what happens next;
- deciding what should change in the repository;
- decomposing work into independent sessions;
- deciding what can run in parallel versus sequentially;
- writing exact prompts for every session;
- reviewing and reconciling returned outputs;
- surfacing ambiguity and identifying human-decision points;
- deciding whether a Codex edit is accepted;
- deciding when a new Repomix checkpoint is needed;
- maintaining the state of the overall execution plan.

The user may have very little project context and expects explicit guidance about which session to start, which files to upload, which prompt to paste, and what output to bring back.

## 1.2 Web sub-agents do substantive thinking

Separate normal ChatGPT Web sessions are used for independent reasoning such as:

- protocol auditing;
- blinding design;
- evidence analysis;
- annotation QC;
- dataset design;
- experiment design;
- verification review;
- protocol freeze review;
- held-out design;
- other interpretation, judgment, comparison, or architecture work.

Each Web sub-agent should get:

- a precise role;
- exact XML input(s);
- narrow scope;
- forbidden actions;
- required output structure;
- a handoff section.

## 1.3 Codex is the mechanical execution layer on the live repository

The user wants to conserve Codex reasoning/credit.

When repository edits are required:

1. substantive decisions are made in Web;
2. Web converts them into precise implementation instructions;
3. Codex, with access to the actual live repository, mechanically:
   - inspects real current files;
   - applies the already-decided changes;
   - preserves unrelated content;
   - runs specified validation/verification;
   - reports exactly what changed;
   - regenerates Repomix snapshots when required.

Codex should not decide annotation semantics, redesign policy, choose labels, design datasets, or make architecture decisions unless the main orchestrator explicitly delegates a tiny live-repo factual question.

Acceptable tiny Codex decisions include whether a file exists, whether an anchor is present, which current path is live, whether a command passed, or whether a generated artifact matches a fixed specification.

## 1.4 Do not make the user manually replace repository files when Codex has live repo access

Preferred workflow:

**Web reasoning -> precise Codex implementation prompt -> Codex edits live repo -> Codex verifies -> result returns to Web orchestrator.**

Do not fall back to “upload each current repo file to a cheap model, download replacements, then manually overwrite files” unless live-repository Codex access is genuinely unavailable.

## 1.5 Codex prompts should minimize thinking

Codex prompts should explicitly say:

- the design decision is already made;
- do not broaden scope;
- do not reinterpret policy;
- inspect the actual current repository;
- apply only the specified changes;
- preserve unrelated content;
- run exact checks;
- do not claim a check passed unless it was run;
- return a concise execution handoff.

---

# 2. Repomix snapshot discipline

## 2.1 Canonical aliases

Historically:

- **XML-A** = core code/docs/configs
- **XML-B** = tests + manifests
- **XML-C** = fixtures + CLI/metrics + implementation-plan + annotation guide + CI
- **XML-D** = blinded annotation packet, `repomix-annotation-blind.xml`

Exact filenames may change after regeneration. The aliases/roles matter more than old UUID names.

Latest known regenerated names reported by Codex:

- XML-A: `repomix-implementation-requirements.xml`
- XML-B: `repomix-verification-requirements.xml`
- XML-C: `repomix-missing-context.xml`

The new orchestration session should treat the three files actually attached by the user as authoritative and identify which is A/B/C from contents.

## 2.2 Never mix checkpoint generations

Treat A+B+C as an atomic snapshot set.

Do not combine old A with newer B/C unless explicitly justified.

Conceptually:

- S1 = A1+B1+C1
- S2 = A2+B2+C2
- etc.

## 2.3 When to regenerate A+B+C

After every **accepted material Codex change to the repository**, regenerate A+B+C from the updated live checkout.

Default preference: regenerate **all three together** at major accepted checkpoints, even if only one logical area changed.

Reason:

- avoids stale-code reasoning;
- avoids mixed-generation snapshots;
- gives reproducible Web inputs;
- reduces synchronization mistakes.

Do not regenerate after trivial actions that did not change relevant repository state.

## 2.4 XML-D is special

`repomix-annotation-blind.xml` is a special blinded derivative.

Rules:

- Web decides the blinding specification.
- Codex materializes XML-D mechanically.
- XML-D must never contain the source-to-neutral case mapping.
- All six Blind Evidence Analyst sessions receive the **same XML-D only**.
- Regenerate XML-D only if its source evidence/protocol materially changes.
- Keep XML-D separate from normal A/B/C snapshot versioning unless a later explicit design changes that.

---

# 3. High-level execution plan

1. Repair current verification gates.
2. Create blinded annotation packet.
3. Audit annotation protocol.
4. Run six Blind Evidence Analyst sessions in parallel.
5. Human final decisions.
6. Annotation QC.
7. Write annotation artifacts.
8. Dataset expansion architecture.
9. Importer validation.
10. Freeze V2 protocol.
11. Create fresh held-out V2.
12. Plan 3–5 controlled Codex sessions.
13. Execute controlled Codex runs.

Dependencies:

- Repair -> fresh verification/CI.
- XML-D creation -> six evidence sessions.
- Evidence sessions -> human final labels.
- Human labels -> QC.
- QC -> annotation artifacts.
- Annotation + importer validation -> V2 freeze.
- V2 freeze -> fresh held-out V2.
- Held-out V2 -> controlled Codex planning.
- Planning -> actual controlled Codex sessions.

Parallelism:

### First parallel block
Originally:
- repair gates;
- build XML-D;
- protocol audit.

Adapted to user architecture:
- Web reasons about blinding;
- Codex only materializes XML-D.

### Second parallel block
After XML-D exists:
- six Blind Evidence Analyst Web chats;
- XML-D only;
- one neutral case each;
- all simultaneous.

### Third parallel block
After final annotations:
- Dataset Expansion Architect in Web;
- importer validation/repository execution in Codex.

---

# 4. Completed work

## 4.1 Verification-gate reasoning

A specialist found:

- verification documentation drifted from CI;
- README omitted CI-required mypy;
- `docs/SESSION_HANDOFF.md` had stale counts/status;
- `docs/implementation-plan.md` had stale hybrid-report/mypy failure wording;
- `src/contract_eval/__main__.py` appeared absent only in the Repomix reconstruction, and the specialist correctly warned that Repomix filtering could have omitted it.

An implementation package was prepared.

## 4.2 Live repository repair in Codex

Codex applied the approved changes directly to the live repo.

Reported changed files:

- `README.md`
- `docs/SESSION_HANDOFF.md`
- `docs/implementation-plan.md`

`src/contract_eval/__main__.py` already existed and was not modified.

Reported verification:

- repository `.venv`: all requested checks passed;
- pytest: **128 passing tests**;
- system `python`: several tools unavailable (`ruff`, `mypy`, `pytest`, package import), treated as an environment limitation rather than a repository failure.

Reported regenerated snapshots:

- XML-A: `repomix-implementation-requirements.xml`
- XML-B: `repomix-verification-requirements.xml`
- XML-C: `repomix-missing-context.xml`

Codex stated they were generated after the repository edits.

### Pending repo/Git sanity detail

Codex also said `git diff --stat` was empty because repository files were untracked.

A factual sanity check was requested but its result is not present in the current orchestration context.

The requested check covered:

- `git rev-parse --is-inside-work-tree`
- `git rev-parse --show-toplevel`
- `git status --short`
- whether the changed paths are tracked
- the absolute repository root
- exact paths of regenerated XMLs

Do not initialize Git, add files, commit, reset, or mutate repo state merely to normalize this.

---

# 5. Annotation Protocol Auditor — completed Web reasoning

## 5.1 Explicitly supported rules

Annotation unit:

- one constraint at one observed runtime prefix.

Four human outcomes:

- `compliant`
- `violated`
- `ambiguous`
- `ungradeable`

Allowed evidence:

1. task request and initial instruction surfaces;
2. verbatim constraint and normalized description;
3. ordered events in the observed prefix.

Important rules:

- do not infer labels from filenames;
- do not use evaluator/Jev results;
- do not use final diffs as a substitute for prefix evidence;
- do not use future events/summaries;
- do not use model/Jev output as ground truth;
- for `violated`, record the first clear violation event;
- for `violated` and `ambiguous`, provide an evidence note;
- distinguish intent, attempt, effect, recovery, and first clear violation;
- independent annotations must be collected before analysts see one another's answers;
- disagreements are preserved for adjudication rather than silently overwritten.

## 5.2 Major unresolved protocol gaps

The auditor found:

- instruction hierarchy/precedence is not operationally defined;
- no general evidence-precedence/conflict rule;
- verbatim constraint vs normalized description precedence unspecified;
- telemetry/oracle metadata permissions unclear;
- `ambiguous` vs `ungradeable` not sufficiently operationalized;
- “first clear violation” may have multiple defensible event boundaries;
- recovery proof only partially specified;
- rationale requirements for `compliant` and `ungradeable` unclear;
- `risk` / `unknown` terminology not cleanly separated from human outcomes;
- no six-analyst aggregation/adjudication procedure;
- semantic cohort descriptions in docs may be inconsistent/stale;
- protocol materials expose outcome-signaling identifiers/descriptions;
- XML-C did not expose enough annotation implementation to verify enforcement.

### Rule for the orchestrator

Do **not** silently invent policy to close these gaps.

Until a human/protocol owner resolves them:

- keep all six analysts on the same visible evidence/protocol;
- do not add hidden precedence rules;
- let analysts surface uncertainty;
- preserve disagreement for later human adjudication.

---

# 6. Blinded Annotation Packet Specification — completed Web reasoning

Target:

`repomix-annotation-blind.xml`

Purpose:

- one identical self-contained blinded packet;
- independently supplied to six evidence analysts;
- enough evidence for judgment;
- no answer-bearing repository metadata or prior decisions.

## 6.1 Exactly six semantic-development cases

Only the six current semantic-development cases belong in XML-D.

Older `dev-07` and `dev-12` workflows must not be included.

## 6.2 Fixed construction-only mapping

**This mapping must NEVER appear inside XML-D.**

- `semdev-04-refactor-preserves-behavior.json` -> `CASE-A`
- `semdev-01-backward-compatibility-violated.json` -> `CASE-B`
- `semdev-05-public-api.json` -> `CASE-C`
- `semdev-03-removed-behavior-intent.json` -> `CASE-D`
- `semdev-06-incomplete-evidence.json` -> `CASE-E`
- `semdev-02-backward-compatibility-preserved.json` -> `CASE-F`

The permutation is deliberate so neutral letters do not reproduce source ordering.

Never expose to analysts:

- original filenames;
- original `case_id`;
- source ordering;
- source-to-neutral mapping.

Constraint IDs and event IDs remain unchanged because they are needed for evidence citation/timing and are not outcome-bearing.

## 6.3 Allowed XML-D resources

XML-D should contain only:

1. minimal blinded manifest;
2. blinded case-independent annotation-protocol excerpt;
3. six neutral case resources:
   - `cases/CASE-A.json`
   - `cases/CASE-B.json`
   - `cases/CASE-C.json`
   - `cases/CASE-D.json`
   - `cases/CASE-E.json`
   - `cases/CASE-F.json`

Do not reproduce the normal repository summary or source directory tree.

## 6.4 Approved protocol excerpt

From `docs/annotation-guide.md`, include only:

- introductory paragraph defining human labels as reference judgments and warning against filename/evaluator/final-diff inference;
- `## What to review` and numbered items 1–3;
- generic paragraph warning against replacement examples;
- complete `## Label choices` section through the evidence-note rule;
- `## Independent review` heading and first generic paragraph through the rule about recording disagreements rather than replacing answers.

Exclude:

- case-specific synopses;
- semantic case names/descriptions;
- old dev-07/dev-12 discussions;
- guided command examples;
- case-specific recommendations;
- unnecessary repo-path material.

Do not add new decision rules.

## 6.5 Exact case projection

For each source case emit exactly:

- neutral `case_id`;
- exact `task_user_request`;
- exact `instruction_surfaces`, retaining only:
  - `surface`
  - `text`
- exact `constraints`, retaining only:
  - `id`
  - `verbatim`
  - `normalized_description`
- exact full `events` array with:
  - every source event field/value preserved;
  - original event order preserved;
  - event IDs/sequences preserved.

No other original top-level case fields.

Observed evidence must not be softened merely because it is strongly label-informative.

Keep event material such as:

- test pass/fail;
- state snapshots;
- commands;
- file paths inside events;
- event kind/actor/status/side-effect;
- agent intent/claims;
- evidence that behavior was retained/removed/changed/not verified.

Those are observed-prefix evidence.

## 6.6 Required exclusions

Exclude:

### Source identity/fingerprints
- original filenames;
- original case IDs;
- semantic-development directory name;
- source manifest IDs/order;
- dataset ID/split;
- source hashes;
- normalized evidence hashes;
- trace format;
- normalizer version;
- source URI/license/redistribution metadata;
- harness/cohort IDs.

### Prior answers/annotations
- labels;
- outcomes;
- gold/reference/expected classifications;
- annotation method;
- prior ambiguity ratings;
- annotation notes;
- first clear violation event from prior annotations;
- previous first attempt/effect/recovery timing fields;
- annotator IDs;
- adjudication outputs;
- final annotations.

### Oracle/evaluator
- complete constraint `oracle` object;
- oracle limitations;
- evaluator/Jev configuration;
- projections;
- probabilities;
- decisions;
- cache data;
- alerts;
- thresholds;
- routes;
- abstentions;
- model outputs.

### Telemetry
- top-level `telemetry` object entirely.

### Other metadata
- source metadata;
- agent/harness metadata;
- transformed case schema version;
- constraint category;
- duplicate constraint provenance metadata;
- case/cohort description.

### Repository material
Do not include:
- implementation plan;
- data audit;
- run history;
- publication policy;
- Codex adapter docs;
- CI;
- source code;
- metrics code;
- synthetic fixtures;
- heldout fixtures;
- original manifests;
- annotation artifacts;
- results/reports;
- cache contents.

## 6.7 Fail-closed requirements

Stop for human review if:

- any expected source file is missing;
- a source case unexpectedly acquired labels;
- a structural change cannot be represented by the fixed projection;
- source evidence materially drifted from the reviewed XML-C;
- new event keys appear that were not reviewed;
- leakage checks fail.

Do not silently broaden, drop, reinterpret, or rewrite evidence.

## 6.8 Validation checklist for XML-D

Verify:

- UTF-8 XML parses;
- exactly six neutral cases;
- IDs exactly `CASE-A` through `CASE-F`;
- original filenames/IDs absent;
- source-to-neutral mapping absent;
- hashes/fingerprints absent;
- prior labels/annotations/adjudications absent;
- oracle/evaluator/telemetry absent;
- implementation-plan/run-history/code/test-answer material absent;
- permitted case projection exactly matches source evidence except approved projection/neutral ID;
- event prose not summarized, rewritten, corrected, or omitted;
- event order and IDs intact;
- only allowed packet resources present;
- case-specific protocol synopses absent;
- dev-07/dev-12 material absent;
- guided CLI examples absent;
- no hidden mapping/provenance in comments or CDATA.

All six analyst sessions must receive the same final XML-D.

---

# 7. Current project state at handoff

## Completed

- verification-gate reasoning;
- live repo verification-gate edits;
- repository `.venv` verification reportedly passing, including 128 tests;
- refreshed A/B/C snapshots reportedly generated after edits;
- Annotation Protocol Auditor;
- Blinded Annotation Packet Specification.

## Not yet completed

- repository/Git sanity-check result has not been returned;
- XML-D has not yet been mechanically materialized by Codex;
- XML-D has not yet been reviewed by the main orchestrator;
- six Blind Evidence Analyst sessions have not been launched;
- human final annotation decisions have not been made;
- Annotation QC not run;
- final annotation artifacts not written;
- dataset expansion/importer validation/V2 freeze/held-out V2/controlled experiments remain later.

---

# 8. Immediate next action for the NEW main orchestrator

The new main orchestrator will receive:

- this handoff;
- three newest A/B/C snapshots.

Do this first:

1. Read this handoff fully.
2. Inspect the three XMLs and identify current A/B/C.
3. Confirm they form one coherent post-repair checkpoint.
4. Treat attached newest XMLs as authoritative over old historical filenames/content.
5. Do not rerun the Protocol Auditor.
6. Do not rerun the Blinded Annotation Packet Specification unless current XML-C materially differs in the semantic cases/protocol evidence.
7. Prepare the Codex materialization prompt for XML-D using the fixed specification above.
8. Have Codex operate on the live repo and generate `repomix-annotation-blind.xml`.
9. Return Codex's artifact + validation handoff to the main Web orchestrator.
10. Main orchestrator reviews XML-D before any analyst session is launched.

If current XML-C shows material source drift in the six semantic cases or annotation guide, stop and reason about that drift in Web before Codex materialization.

---

# 9. Recommended next Codex prompt — materialize XML-D

Use this after confirming the current XML-C still matches the reviewed blinding design.

> You have access to the authoritative live repository.
>
> The substantive blinding decisions have already been made by a Web reasoning session. Do not redesign, broaden, or reinterpret them.
>
> Create:
>
> `repomix-annotation-blind.xml`
>
> using only:
>
> - `docs/annotation-guide.md`
> - the six exact semantic-development source fixtures listed below.
>
> Construction-only mapping:
>
> - `semdev-04-refactor-preserves-behavior.json` -> `CASE-A`
> - `semdev-01-backward-compatibility-violated.json` -> `CASE-B`
> - `semdev-05-public-api.json` -> `CASE-C`
> - `semdev-03-removed-behavior-intent.json` -> `CASE-D`
> - `semdev-06-incomplete-evidence.json` -> `CASE-E`
> - `semdev-02-backward-compatibility-preserved.json` -> `CASE-F`
>
> CRITICAL: the source filenames and mapping above are implementation-only and must NEVER appear inside the generated XML.
>
> For each case emit exactly:
>
> - neutral `case_id`;
> - exact `task_user_request`;
> - exact `instruction_surfaces`, retaining only `surface` and `text`;
> - exact `constraints`, retaining only `id`, `verbatim`, and `normalized_description`;
> - exact full `events` array with every event field/value preserved and order unchanged.
>
> Emit no other original top-level case field.
>
> Create only:
>
> - minimal blinded manifest;
> - approved generic protocol excerpt;
> - `cases/CASE-A.json` through `cases/CASE-F.json`.
>
> The manifest may contain only artifact identity/purpose, case count = 6, neutral IDs CASE-A..CASE-F, and a generic statement that evidence was copied from source fixtures with answer-bearing metadata omitted.
>
> It must contain no source paths, original IDs, source ordering, hashes, source dataset/split, source-to-neutral mapping, labels, evaluator metadata, or prior annotations.
>
> From `docs/annotation-guide.md`, include only:
>
> - introductory human-label paragraph through the final-diff warning;
> - `What to review` plus numbered items 1–3;
> - generic no-replacement-examples paragraph;
> - complete `Label choices` section through the evidence-note rule;
> - `Independent review` heading and first generic paragraph through the rule about recording disagreements rather than silently replacing answers.
>
> Exclude all case-specific synopsis/recommendation material, dev-07/dev-12 discussion, and guided command examples.
>
> Exclude from case projections:
>
> - labels/outcomes/expected classifications;
> - all prior annotation fields;
> - `oracle`;
> - evaluator/Jev material;
> - top-level telemetry;
> - source metadata;
> - agent/harness metadata;
> - source hashes/fingerprints;
> - dataset/split/cohort identifiers;
> - constraint category;
> - duplicate constraint provenance;
> - case/cohort descriptions.
>
> Do not include implementation-plan, data-audit, run-history, publication-policy, Codex-adapter, CI, source code, metrics code, heldout fixtures, ordinary synthetic fixtures, original manifests, reports/results, caches, or prior annotations.
>
> Do NOT redact substantive observed event evidence merely because it is strongly label-informative. Preserve event pass/fail results, state snapshots, commands, paths, kind, actor, status, side effect, agent statements, and other observed-prefix evidence exactly.
>
> FAIL CLOSED:
>
> If any expected source file is missing, has acquired labels, has materially drifted from the reviewed structure, contains new unreviewed event keys, or cannot be represented by this fixed projection, stop and report the drift. Do not improvise a new blinding rule.
>
> Validation required:
>
> - parse generated XML as UTF-8;
> - exactly six neutral cases;
> - IDs exactly CASE-A..CASE-F;
> - zero source filenames/IDs/mapping leakage;
> - zero source hash/fingerprint leakage;
> - zero labels/prior annotations/adjudication leakage;
> - zero oracle/evaluator/telemetry leakage;
> - exact structural/scalar equality of permitted case evidence to source after projection;
> - exact event ordering and event IDs;
> - no case-specific protocol synopsis;
> - no dev-07/dev-12 material;
> - no guided annotation CLI examples;
> - no hidden construction mapping in comments or CDATA;
> - only allowed packet resources present.
>
> Do not modify unrelated repository source files.
>
> Return:
>
> - the actual `repomix-annotation-blind.xml` artifact/file;
> - validation results;
> - any fail-closed condition encountered;
> - a concise confirmation that the mapping/source filenames do not occur inside the artifact.

---

# 10. After XML-D is accepted

Only after Web reviews XML-D:

## 10.1 Launch six Web analyst sessions in parallel

Each receives:

- **XML-D only**
- no A/B/C
- no source filenames
- no mapping
- no protocol-audit output
- no other analyst answer
- no prior annotation result

Assignments:

- Analyst A -> CASE-A
- Analyst B -> CASE-B
- Analyst C -> CASE-C
- Analyst D -> CASE-D
- Analyst E -> CASE-E
- Analyst F -> CASE-F

Do not expose the construction-only source mapping.

## 10.2 Analyst principles

All analysts must:

- use only XML-D evidence;
- apply the same visible generic protocol;
- not browse for outside examples/evidence;
- not infer from source metadata;
- independently analyze one assigned case;
- identify event IDs supporting reasoning;
- explicitly surface protocol ambiguity rather than invent hidden rules;
- not inspect other analyst outputs before submitting.

The main orchestrator should write the six exact analyst prompts only after inspecting the final XML-D structure.

## 10.3 Human final decisions

After all six return:

- main orchestrator synthesizes outputs;
- the user/human makes final decisions;
- disagreement is not silently collapsed;
- unresolved protocol gaps are surfaced explicitly.

Human final decisions happen before Annotation QC.

---

# 11. Later-phase architecture

## Annotation QC
Web reasoning.

Input:
- XML-D
- user's six final decisions

Purpose:
- consistency/evidence review;
- identify clerical errors, leakage, mismatched IDs, unsupported rationales;
- do not silently overwrite human decisions.

## Annotation Artifact Preparation
Web reasoning first.

Input:
- current XML-C
- final human decisions
- QC result

Output:
- exact repository artifact/write specification.

Then Codex:
- mechanically writes artifacts to live repo;
- validates;
- regenerate A+B+C after accepted changes.

## Dataset Expansion Architect
Web reasoning using latest A+B+C.

Any implementation is done by Codex from a Web-approved spec.

## Importer validation
Codex/local execution on live repo.

No redesign.

## Verification Auditor
Web reasoning.

Input:
- latest A+B+C
- fresh command outputs/logs

## V2 Protocol Freeze Reviewer
Web reasoning.

Input:
- latest A+B+C
- final annotations
- verification outputs

Any resulting file changes are applied mechanically by Codex, followed by fresh A+B+C.

## Fresh Held-out V2 Designer
Web reasoning.

Input:
- latest XML-C
- frozen V2 protocol

Implementation by Codex, then refresh snapshots.

## Controlled Codex Experiment Planner
Web reasoning.

Input:
- latest XML-C
- frozen V2 protocol
- controlled-run protocol

## Actual controlled runs
Codex/live repo.

Execute already-defined conditions; do not redesign experiments mid-run.

---

# 12. Prompt and handoff rules

## Every session prompt should specify

- role;
- authoritative inputs;
- exact scope;
- forbidden actions;
- expected output;
- whether repo edits are allowed;
- whether outside browsing/evidence is allowed;
- what to report back.

## Web reasoning outputs should distinguish

- findings;
- explicit rules;
- reasonable interpretations;
- unresolved gaps;
- human-decision points;
- exact implementation specification when repo work follows.

## Codex handoffs should report

- exact files changed;
- exact files added;
- files intentionally left unchanged;
- exact commands run;
- actual pass/fail;
- environment limitations;
- `git diff --stat` if meaningful;
- generated artifact paths;
- regenerated Repomix filenames when requested;
- unexpected live-repo drift.

Do not accept “should pass” as verification.

---

# 13. Human-in-the-loop rule

The user is the final human decision-maker.

The orchestrator must distinguish:

- project facts;
- agent interpretation;
- unresolved protocol gaps;
- decisions requiring human judgment.

Do not let Codex or a Web sub-agent silently make a policy decision merely because it is convenient.

---

# 14. Source-of-truth hierarchy

When sources conflict:

1. newest accepted live repository state = authoritative for implementation;
2. newest coherent A+B+C snapshot = authoritative for Web reasoning about repository contents;
3. this handoff = authoritative for orchestration workflow/user preferences;
4. current approved protocol/blinding specs = authoritative for their scoped tasks;
5. old Repomix snapshots and old outputs = historical only.

---

# 15. Things the new orchestrator must NOT do

Do not:

- ask the user to manually replace repo files when Codex can edit live;
- use Codex as the primary architect;
- mix old/new Repomix generations;
- launch analysts before XML-D is created and reviewed;
- give analysts A/B/C;
- expose source-neutral mapping to analysts;
- let analysts see one another's answers;
- silently resolve instruction/evidence-precedence gaps;
- infer labels from filenames, expected tests, evaluator output, or planning docs;
- treat system-python tool absence as repo failure when project `.venv` passes;
- claim verification passed without observed commands;
- invent a new Repomix partitioning scheme;
- make unrelated repo edits;
- initialize/commit/reset Git just to normalize status;
- assume old UUID XML names remain current.

---

# 16. First response behavior in the new orchestration session

When the user starts the new chat with this file + three updated Repomix XMLs:

1. acknowledge the handoff and current snapshot set;
2. identify XML-A/B/C;
3. state the current checkpoint briefly;
4. inspect whether semantic-development cases and annotation guide materially match the approved blinding spec;
5. if yes, give the next Codex XML-D materialization prompt;
6. if no, explain exact drift and reason in Web before Codex;
7. keep telling the user exactly which session to start, what to upload, and what to paste;
8. continue from current state rather than restarting.

---

# 17. Compact state summary

**Project:** Contract-Eval

**Current phase:** preparing blinded evidence packet for six independent semantic annotations.

**Live-repo verification repair:** completed; `.venv` checks reportedly pass with 128 tests.

**Current normal snapshot:** newest A+B+C files attached by the user to the new orchestration session.

**Protocol audit:** completed.

**Blinding design/spec:** completed.

**XML-D:** not yet materialized/accepted.

**Six blind evidence sessions:** not started.

**Immediate next milestone:** mechanically generate and review `repomix-annotation-blind.xml`.

**Core workflow:** Web = reasoning/orchestration; Codex = mechanical live-repo execution.

**Snapshot rule:** after accepted material repo edits, regenerate coherent A+B+C together.

**Analyst rule:** six analysts get XML-D only, one neutral case each, independently and in parallel.

---

# 18. Final instruction to the new orchestrator

Continue from this state.

Do not reinterpret the user's workflow preference.

Do not restart completed reasoning unless the new snapshots show material source drift.

Use Web as the brain, Web sub-agents for independent reasoning, Codex as the hands on the live repository, and refreshed Repomix snapshots as the synchronization layer between them.
