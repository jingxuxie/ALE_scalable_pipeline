# Hard paper-derived task release checklist

## Source and legality

- [ ] Exact paper/supplement bytes are pinned.
- [ ] Official code commit or release is pinned when used.
- [ ] Dataset versions and hashes are recorded.
- [ ] Redistribution and execution licenses are acceptable.
- [ ] Paper/code/data disagreements are recorded.
- [ ] Untrusted source commands were inspected and sandboxed.

## Workflow grounding

- [ ] Claim/problem tree exists.
- [ ] Execution workflow DAG exists.
- [ ] The selected task has a concrete target leaf.
- [ ] The task uses a meaningful backward workflow slice.
- [ ] Each operation/artifact has provenance.
- [ ] Grounded extensions are labeled as extensions.
- [ ] No low-confidence inference is a hidden participant requirement.

## Hardness

- [ ] At least four meaningful participant operations are present, or a justified exception is documented.
- [ ] Dependency depth is at least three, or a justified exception is documented.
- [ ] At least two independent challenge sources are present.
- [ ] Difficulty does not primarily come from formatting, volume, hidden trivia, thresholds, or compute.
- [ ] Clone-and-run does not trivialize the task.
- [ ] One-formula/one-library-call shortcuts do not pass.
- [ ] Hard-coded public examples do not pass.
- [ ] Intermediate results are used as private rubrics when useful.
- [ ] The task is labeled `structurally_hard_candidate` until calibrated.

## Public specification

- [ ] The participant goal is clear.
- [ ] Every visible input is documented.
- [ ] Required output paths and schemas are explicit.
- [ ] Scientific definitions and conventions needed for success are public.
- [ ] Environment, tools, network and resource limits are public.
- [ ] Qualitative success criteria are public.
- [ ] Exact hidden cases, thresholds, weights and references remain private.
- [ ] The specification-closure table has no invalid hidden dependencies.
- [ ] A paper-blind reviewer can restate the task and finds no material missing information.
- [ ] Paper/source identifiers and direct answer leakage are removed.

## References and solvability

- [ ] Privileged oracle runs successfully.
- [ ] Public-input reference solver reads only participant-visible files.
- [ ] Public-input solver runs in the declared participant environment.
- [ ] Public-input solver fits the participant resource budget.
- [ ] Public-input solver passes the private evaluator.
- [ ] An independent valid solution passes, or the absence is justified.
- [ ] The reference solution does not read undisclosed constants at runtime.

## Evaluation

- [ ] Hard gates cover only structural/security failures.
- [ ] Scientific quality receives continuous scoring where appropriate.
- [ ] Evaluator recomputes metrics from artifacts.
- [ ] Models/programs are evaluated behaviorally when possible.
- [ ] Exact code, weights, pickle bytes and plot pixels are not required without justification.
- [ ] Absolute and relative tolerances are justified.
- [ ] Stochastic tasks use multiple seeds/instances and aggregate rules.
- [ ] Exact private thresholds and score weights are not participant-visible.
- [ ] Metric weights and score contract are internally consistent.
- [ ] Repeated evaluator runs are deterministic.

## Adversarial validation

- [ ] Realistic mutants cover at least five categories, or a justified exception is documented.
- [ ] Every required mutant fails.
- [ ] Malformed and partial outputs fail safely.
- [ ] NaN/Inf and oversized artifacts fail safely.
- [ ] Stale cached outputs are detected.
- [ ] Fabricated self-reported metrics do not affect recomputed scores.
- [ ] Hard-coded public examples fail hidden tests.
- [ ] Applicable metamorphic/invariant tests pass.
- [ ] Participant code cannot read private/author files.
- [ ] Network and path/symlink policies are enforced.

## Hidden instances

- [ ] Private generation uses unpublished randomness or private assets.
- [ ] Public review instances are permanently retired.
- [ ] Generated variants preserve the intended scientific phenomenon.
- [ ] Reference solutions pass across the private distribution.
- [ ] Hidden cases include ordinary and relevant edge/OOD cases.
- [ ] Seeds for public inputs, hidden evaluation and mutations are separated.

## Execution and packaging

- [ ] `python tasks/<task_slug>/scripts/verify.py` passes.
- [ ] Participant, private and author projections are separated.
- [ ] No private artifact appears in the participant package.
- [ ] Dependencies are pinned or otherwise reproducible.
- [ ] Runtime, memory and disk use are measured.
- [ ] A real ALE-compatible environment run has been completed or is explicitly pending.
- [ ] Verification report is complete.
- [ ] Final decision and blocking issues are explicit.

## Calibration and release

- [ ] Exact task build identity is recorded.
- [ ] Pinned frontier-agent trials are run before claiming frontier difficulty.
- [ ] Trial results include continuous scores and pass/fail.
- [ ] Difficulty claims include uncertainty and exact agent-system definitions.
- [ ] Scientific expert review is complete.
- [ ] Release status is one of the allowed statuses in the author instructions.
