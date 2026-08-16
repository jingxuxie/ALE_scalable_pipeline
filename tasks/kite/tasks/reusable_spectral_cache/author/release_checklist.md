# Hard paper-derived task release checklist: reusable-chebyshev-spectral-cache-v1

## Source and legality

- [x] Exact paper bytes are pinned.
- [x] Official code release and commit are pinned.
- [x] Synthetic input versions and hashes are recorded.
- [ ] Redistribution and execution licenses are acceptable. The independently authored participant assets still need an explicit downstream license.
- [x] Paper/code/data disagreements are recorded.
- [x] Untrusted source commands were inspected; provider code was not executed.

## Workflow grounding

- [x] Claim/problem tree exists.
- [x] Execution workflow DAG exists.
- [x] The selected task has a concrete target leaf.
- [x] The task uses a meaningful backward workflow slice.
- [x] Each operation/artifact has provenance.
- [x] Grounded extensions are labeled as extensions.
- [x] No low-confidence inference is a hidden participant requirement.

## Hardness

- [x] At least four meaningful participant operations are present.
- [x] Dependency depth is at least three.
- [x] At least two independent challenge sources are present.
- [x] Difficulty does not primarily come from formatting, volume, hidden trivia, thresholds, or compute.
- [x] Clone-and-run does not trivialize the task.
- [x] One-formula/one-library-call shortcuts do not pass.
- [x] Hard-coded public examples do not pass.
- [x] Intermediate moments are used as private rubrics.
- [x] The task is labeled `structurally_hard_candidate` until calibrated.

## Public specification

- [x] The participant goal is clear.
- [x] Every visible input is documented.
- [x] Required output paths and schemas are explicit.
- [x] Scientific definitions and conventions needed for success are public.
- [x] Environment, tools, network, and resource limits are public.
- [x] Qualitative success criteria are public.
- [x] Exact hidden cases, thresholds, weights, and references remain private.
- [x] The specification-closure table has no invalid hidden dependencies.
- [x] A paper-blind reviewer can restate the task and finds no material missing information.
- [x] Paper/source identifiers and direct answer leakage are removed.

## References and solvability

- [x] Privileged oracle runs successfully.
- [x] Public-input reference solver reads only participant-visible files.
- [x] Public-input solver runs in the declared participant environment.
- [x] Public-input solver fits the participant resource budget by runtime and output-size evidence.
- [x] Public-input solver passes the private evaluator.
- [x] An independent eigensolver implementation passes.
- [x] The reference solution does not read undisclosed constants at runtime.

## Evaluation

- [x] Hard gates cover only structural/security failures.
- [x] Scientific quality receives continuous scoring.
- [x] Evaluator recomputes metrics from artifacts.
- [x] Outputs are evaluated behaviorally through unseen contractions.
- [x] Exact code, pickle bytes, and plot pixels are not required.
- [x] Absolute and relative tolerances are justified.
- [x] The task is deterministic on fixed instances; no stochastic submission aggregation is needed.
- [x] Exact private thresholds and score weights are not participant-visible.
- [x] Metric weights and score contract are internally consistent.
- [x] Repeated evaluator runs are deterministic.

## Adversarial validation

- [x] Fifteen realistic scientific mutants cover more than five categories.
- [x] Every required mutant fails.
- [x] Malformed and partial outputs fail safely.
- [x] NaN/Inf and oversized artifacts fail safely.
- [x] Stale cached outputs are detected.
- [x] Fabricated self-reported metrics do not affect recomputed scores.
- [x] Hard-coded public examples fail hidden tests.
- [x] Applicable metamorphic/invariant tests pass.
- [x] Evaluation is data-only; clean-room solver private/source reads are denied.
- [ ] Dynamic symlink cases could not be created on this Windows host. Static reparse/regular-file checks and hard-link tests pass; capable CI coverage remains pending.

## Hidden instances

- [ ] Production private generation still requires server-secret seed rotation.
- [x] Public review instances are permanently retired.
- [x] Generated variants preserve Hermiticity, spectral containment, and finite-contraction semantics.
- [x] Sparse-recurrence and dense-spectral references pass the private review distribution.
- [x] Hidden cases vary topology, dimension, phase, energy, broadening, sector, and non-power-of-two prefix.
- [x] Public, hidden, and mutation seed domains are separated in the retired review build.

## Execution and packaging

- [x] `python tasks/kite/tasks/reusable_spectral_cache/scripts/verify.py` passes.
- [x] Participant, private, and author projections are separated.
- [x] No private artifact appears in the participant package.
- [x] Dependencies are bounded and reproducible.
- [ ] Runtime and disk use are recorded, but peak resident memory is not yet measured.
- [ ] ALE compiler/publication and target-infrastructure runs remain pending.
- [x] Verification report is complete.
- [x] Final decision and blocking issues are explicit.

## Calibration and release

- [x] Exact task build identity is recorded: `sha256:439d24074b7efc721570f33b64e0433427dfa6488945274a4aedbd78ee4b3f54`.
- [ ] Pinned frontier-agent trials are run before claiming frontier difficulty.
- [ ] Trial results include continuous scores and pass/fail.
- [ ] Difficulty claims include uncertainty and exact agent-system definitions.
- [ ] Independent scientific expert review is complete.
- [x] Release status is the allowed status `needs_agent_calibration`.

## Current disposition

Locally verified and suitable for collaborator review as a `structurally_hard_candidate`; not ready for benchmark release until the unchecked items are resolved.
