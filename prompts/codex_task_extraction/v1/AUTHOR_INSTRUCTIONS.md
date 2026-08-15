# Author instructions: hard paper-derived ALE tasks

These instructions govern an interactive Codex authoring session. They are
stricter than a prompt that merely asks for task ideas.

## Mission

Convert one paper and its associated artifacts into at most three high-quality
ALE task candidates. Prefer one excellent task.

The reusable unit is a **verified long workflow**, not a small question. A
concrete leaf claim, table, figure, or result should anchor the target, but the
participant task should normally include the meaningful sequence of operations
needed to reach it.

## Trust model

The authoring session is privileged. It may read the paper, source code, data,
reference outputs, and hidden generation parameters.

The benchmark participant is not privileged. It receives only the public task
package.

Never infer that a task is well-posed merely because the authoring session can
solve it with source access.

Maintain these roles:

- **source evidence:** paper, supplement, official repository, data;
- **author oracle:** may use source evidence;
- **participant solver:** may read only participant-visible files;
- **private evaluator:** may read hidden references and hidden inputs.

## Source resolution

1. Prefer the official paper page, supplement, author repository, archival
   release, and persistent dataset.
2. Record URLs, local paths, exact commits/versions, hashes, licenses, and
   retrieval dates.
3. Inspect source commands before execution.
4. Run source code in a bounded environment.
5. Record dependency and environment details.
6. Never silently merge conflicting paper, code, configuration, and observed
   behavior.
7. If redistribution is prohibited, do not place those bytes in the participant
   task. Use a legally sound derived/synthetic artifact or reject the candidate.

## Evidence extraction

Create evidence records for:

- research questions and hypotheses;
- concrete claims and finding leaves;
- data and splits;
- preprocessing;
- methods and equations;
- training/simulation procedures;
- baselines and ablations;
- metrics and statistical tests;
- figures, tables, and conclusions;
- limitations and failure conditions;
- code entry points and configuration values;
- dynamically observed inputs, outputs, and commands.

Every record needs an exact locator and an origin class:

- `paper_reported`;
- `code_present`;
- `config_present`;
- `dynamically_observed`;
- `author_inferred`;
- `benchmark_choice`;
- `grounded_extension`.

Low-confidence inference must not become a hidden requirement.

## Graph construction

Create two linked structures.

### Claim/problem tree

Represent the semantic hierarchy from broad research question to concrete
finding leaves. Each useful leaf should identify:

- claim/result;
- supporting dataset or system;
- metric or evidence;
- reported artifact such as a table or figure;
- scientific importance;
- whether it can generate private variants.

### Execution workflow DAG

Represent artifacts and operations separately. An operation record should
include:

- purpose;
- inputs;
- outputs;
- parameters;
- tool/environment;
- stochasticity;
- runtime estimate;
- provenance;
- claims supported.

Link each candidate leaf to the operations and artifacts that produce its
evidence.

## Candidate construction

For each promising leaf:

1. take a backward slice through the execution DAG;
2. choose a public boundary and a private evaluation boundary;
3. decide which intermediate artifacts are participant outputs and which are
   private rubric evidence;
4. consider reproduction, completion, repair, comparison, transfer, audit, or
   optimization variants;
5. prefer a coherent end-to-end workflow over disconnected subtasks.

Generate no more than six rough candidates. Fully build no more than three.

## Hard-task screen

A final candidate should normally satisfy all of the following:

- at least four meaningful participant operations;
- dependency depth at least three;
- multiple files or artifacts;
- at least two independent sources of challenge;
- at least one hidden generalization, robustness, or anti-hardcoding test;
- multiple required output artifacts when professionally natural;
- a trusted, outcome-based evaluator;
- a public-input solution path;
- bounded participant runtime and resources.

Meaningful challenge sources include:

- nontrivial implementation or repair;
- multi-stage data handling;
- integration across modules or tools;
- experimental iteration or model selection;
- baseline/ablation comparison;
- stochastic aggregation;
- distribution shift;
- long-horizon simulation;
- diagnosis using intermediate evidence;
- evidence-linked reporting.

These do not count as primary challenge:

- more rows with the same operation;
- more benchmark instances;
- exact formatting;
- tighter tolerance without scientific basis;
- an obscure constant hidden in the paper;
- excessive compute;
- copying a long but already complete script.

## Shortcut audit

Actively try to break the candidate with:

- clone-and-run of the official source;
- one-line library calls;
- direct linear regression or lookup;
- hard-coding public examples;
- copying reported values;
- ignoring major workflow stages;
- outputting fabricated self-reported metrics;
- exploiting predictable seeds or filenames.

If a shallow strategy passes, strengthen the task or reject it.

## Specification closure

Complete a table with one row per solution-critical decision:

| Decision | Publicly disclosed | Inferable from public assets | Evaluator method-agnostic | Invalid hidden dependency |
| --- | --- | --- | --- | --- |

Exactly one of the first three must hold. No row may remain in the last column
for an accepted task.

The task may intentionally hide the source method only when any valid method can
pass the evaluator. If one exact method is required, disclose the necessary
method specification without revealing the source paper identity or final
answer.

## Participant information policy

The participant should know:

- what professional outcome is required;
- what files are provided;
- what outputs must be produced;
- output schemas and paths;
- allowed software and tools;
- runtime, hardware, storage and network constraints;
- qualitative evaluation dimensions;
- relevant scientific definitions and conventions.

The participant should not know:

- source paper identity when avoidable;
- exact hidden inputs or seeds;
- exact reference values;
- exact thresholds and weights;
- mutation suite;
- oracle parameters;
- source code that contains the core solution.

Do not withhold the meaning of success. Withhold private tests, not necessary
task semantics.

## Input construction

Inputs may come from:

- public source data, if redistribution and leakage are acceptable;
- transformed or subsampled source data;
- new synthetic data from a trusted generator;
- new systems or parameters that preserve the paper's phenomenon;
- starter code with the core solution removed;
- deliberately faulty code for a repair task.

Use neutral filenames and task titles. Remove paper names, acronyms, citations,
comments, configuration names, and metadata that reveal the source unnecessarily.

## Output contracts

Prefer structured and behaviorally evaluable outputs:

- JSON or YAML parameters;
- CSV/Parquet metrics and figure data;
- NumPy arrays with documented shapes;
- safe model formats;
- executable code with a narrow interface;
- generated trajectories or predictions;
- structured claims linked to evidence;
- a report accompanied by machine-readable supporting data.

Do not grade exact source code, exact neural weights, pickle bytes, or image
pixels when a functional representation is possible.

## Oracle and reference generation

### Privileged oracle

May use hidden source parameters and official code. Use it to produce independent
expected behavior and private references.

### Clean-room public-input solver

Must:

- reside under `author/reference_solver/`;
- read only `participant/`;
- use only declared dependencies;
- run under participant resource and network policy;
- produce exactly the participant output contract;
- pass the private evaluator.

A source-informed algorithm is allowed, but no hidden file or undisclosed
constant may be read at runtime.

### Alternative solver

When feasible, implement a second solution with different numerical or
algorithmic structure. This tests evaluator completeness and reduces common-mode
bugs.

## Evaluation design

Separate hard gates and scientific metrics.

### Hard gates

Use only for:

- required artifact existence;
- parseability and schema;
- IDs, shapes and completeness;
- finite values;
- bounded execution and artifact sizes;
- prohibited file/reference/network access;
- unsafe files or code.

### Scientific metrics

Use continuous scores for:

- prediction or reconstruction error;
- rollout behavior;
- conservation/invariants;
- task-specific success;
- comparison with a baseline;
- robustness across hidden instances;
- report/evidence consistency;
- efficiency under the declared budget.

The evaluator must recompute metrics from submitted artifacts. Never trust
self-reported numbers.

## Tolerance policy

For deterministic numeric values, define:

```text
allowed_error = max(abs_tolerance, rel_tolerance * reference_scale)
```

Choose tolerances from:

- numerical conditioning;
- integration or solver accuracy;
- repeated reference implementations;
- acceptable scientific equivalence.

For stochastic workflows:

- use multiple private seeds or instances;
- evaluate distributions or aggregate statistics;
- compare with a baseline or minimum effect;
- use confidence intervals, quantiles, or required success fractions;
- avoid one exact seed or one exact weight checkpoint.

Document tolerance derivation in the verification report. Checksums protect
artifact identity; they are not scientific correctness criteria.

## Hidden evaluation and variants

Hidden evaluation should include at least one of:

- unseen data split;
- new physical/system parameters;
- different initial conditions;
- distribution shift;
- longer horizon;
- perturbed noise;
- hidden code tests;
- adversarial edge cases.

Private instance generation must preserve the intended scientific phenomenon.
Verify that reference rankings or qualitative conclusions remain valid on the
generated distribution.

## Evaluator stress testing

Test realistic invalid solutions across several categories:

- wrong sign, unit, axis, index or coordinate convention;
- incorrect data split or leakage;
- omitted normalization;
- wrong metric;
- missing baseline or ablation;
- omitted interaction term;
- unstable solver/integrator;
- overfit to public examples;
- stale cached output;
- fabricated report metrics;
- malformed/partial/NaN/oversized output;
- private-file or network access.

Add metamorphic tests when applicable, such as:

- permutation equivariance;
- translation/rotation invariance;
- conservation laws;
- monotonicity;
- unit scaling;
- regenerating a figure from submitted data.

Require deterministic evaluator output on repeated runs.

## Clean-room execution

Create a clean directory or container with only:

- `participant/`;
- declared system and package dependencies;
- the public-input solver for validation only.

Ensure the solve process cannot read `private/`, `author/`, the paper, the source
repository, or hidden logs.

Record:

- full commands;
- environment;
- exit status;
- runtime;
- peak memory if available;
- output inventory;
- evaluator metrics and score.

## Paper-blind specification review

After specification closure, give only the participant package to a fresh
reviewer or fresh model context that has not seen the source paper or code. Ask
it to:

- restate the task and success criteria;
- enumerate necessary scientific conventions and decisions;
- identify missing files, definitions or constraints;
- distinguish genuine ambiguity from intended open-ended method choice.

The reviewer does not have to solve the task. Record and resolve every material
ambiguity. This review complements, but does not replace, the clean-room
reference solver.

## Difficulty reporting

Report:

- operation count and dependency depth;
- number of branches, tools and required artifacts;
- major unknowns and decision points;
- public-input volume;
- source of intrinsic challenge;
- shortcut audit outcomes;
- baseline and clean-room solver performance;
- expected human expert workflow;
- empirical agent calibration status.

`structurally_hard_candidate` means the workflow is plausibly hard and all
verification gates pass. It does not mean frontier agents have been shown to
fail.

## Acceptance statuses

Use exactly one:

- `accepted_for_collaborator_review`;
- `needs_scientific_review`;
- `needs_agent_calibration`;
- `no_viable_hard_task`;
- `rejected_verification_failure`;
- `rejected_specification_gap`;
- `rejected_resource_or_license`.

A verified but uncalibrated task will normally be
`needs_agent_calibration`.

## Session completion

Do not finish with task ideas alone. Finish only after:

- all required files exist;
- the privileged oracle runs;
- the clean-room solver runs;
- a paper-blind specification review is completed;
- the private evaluator runs;
- mutants are tested;
- the verification report and checklist are complete;
- the final status is explicit.

Do not modify unrelated repository files.
