# Difficulty-first paper-derived task checklist v2

A task may not enter full hardening merely because it has many operations,
hidden cases, or mutants. Complete Phase A first.

## Phase A — difficulty screen

- [ ] Rapid source pass stayed within its budget or documents a justified overrun.
- [ ] At most three candidates were screened.
- [ ] At most one candidate was selected for hardening.
- [ ] Candidate target is a meaningful paper-grounded claim/result.
- [ ] Final task boundary is not an easy leaf or disclosed-formula transcription.
- [ ] Decision-enriched workflow graph includes artifacts and operations.
- [ ] Consequential decision nodes list plausible alternatives and observable evidence.
- [ ] At least one real run-inspect-revise feedback loop exists, or pilot evidence justifies an exception.
- [ ] Recipe-disclosure audit covers every major reference-solver step.
- [ ] No `hidden_dependency` remains.
- [ ] Recipe-disclosure ratio is at or below policy, or exceptional pilot evidence is documented.
- [ ] `TASK.md` does not mirror the reference solver.
- [ ] Candidate is not primarily one formula, pseudocode transcription, deterministic row generation, one standard fit, or clone-and-run.
- [ ] Minimal pilot evaluator has an ordinary case and a hidden shift/anti-hardcoding case.
- [ ] Participant draft and pilot evaluator are frozen and hashed.
- [ ] B0 unchanged/trivial baseline is below threshold.
- [ ] B1 direct-recipe baseline is below threshold.
- [ ] B2 source clone/lookup fails or is inapplicable by construction.
- [ ] At least two isolated fresh strong-agent attempts were run.
- [ ] Pilot attempts received no authoring context, paper, source solution, reference, or evaluator details.
- [ ] No pilot fully passed or triggered the configured easy-task rejection policy.
- [ ] Zero/low pilot scores were checked for specification and infrastructure failure.
- [ ] Candidate status is `hardening_candidate` before Phase B begins.

When pilot agents cannot be run, stop at `needs_difficulty_pilot`. When every
candidate fails, return `no_viable_hard_task`.

## Participant difficulty quality

- [ ] Difficulty comes from decisions, diagnosis, integration, experimentation, feedback, or hidden-regime generalization.
- [ ] Difficulty does not come mainly from missing arbitrary facts, formatting, tighter tolerances, more rows, or excessive compute.
- [ ] A runnable but inadequate or incomplete multi-file workspace is used when appropriate.
- [ ] Public success dimensions are clear while exact tests/weights/thresholds remain private.
- [ ] The evaluator permits alternative valid methods when exact source imitation is unnecessary.
- [ ] Required reports or claims are linked to machine-readable generated evidence.

## Phase B — targeted grounding and solvability

- [ ] Exact provenance is completed only for the selected task-relevant workflow.
- [ ] Paper/code/configuration/observed conflicts are recorded.
- [ ] Benchmark-authored transformations and grounded extensions are explicit.
- [ ] Participant, private, author, and screening files are separated.
- [ ] Privileged oracle passes.
- [ ] Clean-room public-input reference reads only participant files and passes under participant limits.
- [ ] Reference solver is not used as task-difficulty evidence.
- [ ] Alternative valid solution is added when it materially tests evaluator generality.
- [ ] Paper-blind specification review finds no required hidden information.
- [ ] Final participant changes after pilots were re-piloted or explicitly invalidate Phase A evidence.

## Private evaluator

- [ ] Hard gates cover only structure, completeness, safety, and resources.
- [ ] Scientific quality receives continuous or behaviorally meaningful scores.
- [ ] Ordinary, shifted, and anti-hardcoding/adversarial cases are present as appropriate.
- [ ] Primary outcome is recomputed, not self-reported.
- [ ] Intermediate workflow rubrics improve partial credit or diagnosis where useful.
- [ ] Evidence-linked conclusions are checked against generated artifacts.
- [ ] Absolute/relative tolerances are justified by conditioning and valid implementations.
- [ ] Stochastic workflows use multiple hidden seeds or instances.
- [ ] Targeted mutants cover distinct realistic failure categories.
- [ ] Relevant metamorphic/invariant tests pass.
- [ ] Malformed, NaN, partial, oversized, stale, leakage, and security probes fail safely.
- [ ] Repeated evaluator runs are deterministic.

Mutation count and hidden-case count are recorded only as evaluator evidence,
never as task-hardness evidence.

## Resources, deployment, and claims

- [ ] Reference and participant resource usage is measured in the target environment.
- [ ] Network, filesystem, process, link, and private-reference isolation are enforced.
- [ ] Public review instances are retired from scoring.
- [ ] Private instance generation preserves the intended phenomenon.
- [ ] Generated assets and dependencies pass license review.
- [ ] Real ALE packaging and sandbox integration pass.
- [ ] Final task build has an immutable identity.
- [ ] Full frontier claim is withheld until exact-build calibration across pinned agent systems.

## Allowed final statuses

- `rejected_recipe_task`
- `rejected_shortcut`
- `rejected_pilot_too_easy`
- `rejected_specification_gap`
- `needs_difficulty_pilot`
- `hardening_candidate`
- `verified_hard_candidate`
- `needs_scientific_review`
- `needs_full_agent_calibration`
- `frontier_challenging`
- `no_viable_hard_task`
