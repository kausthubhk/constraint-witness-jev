# Related work and positioning

The project occupies a narrow intersection of existing areas: runtime-original explicit coding constraints, ordered coding-agent trajectories, prefix-only evaluation, deterministic oracles, Jev semantic decisions, hybrid routing, and false-alert/cost analysis.

Adjacent work includes:

- ATFD, which benchmarks agent monitors over broad trajectories;
- PrefixGuard and AgentForesight, which study online or prefix failure monitoring;
- OctoBench and adherence-suite, which evaluate coding-agent instruction adherence;
- CodeTraceBench, which annotates coding trajectory errors;
- `jev-agent-failure-benchmark`, `jev-guard`, Foreman, `jevwire`, and related projects, which evaluate or use Jev for agent supervision or gating.

This repository must not claim to be the first monitor benchmark, first prefix monitor, first coding instruction benchmark, first Jev agent benchmark, or first Jev coding guardrail. Its defensible focus is the empirical boundary between constraints ordinary code can check and constraints that may require semantic judgment, measured from evidence available at each trace prefix.

The source handover contains the research snapshot and links. Volatile facts and competitor details should be re-verified before any public research claim.

