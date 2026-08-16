# Codex workflow v2: extract genuinely hard ALE tasks from one paper

This guide replaces the v1 **build-everything-first** workflow for interactive
Codex authoring. V1 remains available for reproducibility, but it can spend
hours hardening a task whose public specification already contains the complete
solution recipe.

V2 has one governing rule:

> **Falsify difficulty before investing in full verification.**

The default outcome is one high-quality task, not several tasks.

## 1. What V2 means by hard

A hard task is not defined by:

- the number of graph nodes;
- the number of output rows;
- the length of `TASK.md`;
- the number of hidden cases;
- the number of mutants;
- strict numerical tolerances;
- machine runtime alone.

A strong candidate should require several of the following:

- consequential choices whose best answer depends on supplied evidence;
- diagnosis of an incomplete, inconsistent, or faulty workspace;
- integration across multiple modules, tools, or artifact types;
- experiment design, comparison, or model selection;
- at least one run-inspect-revise feedback loop;
- hidden-regime generalization;
- coupled code, result, and evidence deliverables;
- robust behavior rather than exact imitation of the source method.

Most importantly, fresh strong agents must not solve the immutable participant
draft quickly.

## 2. Two-phase pipeline

```text
paper + code + data
        |
        v
  Phase A: screen and falsify difficulty
        |
        +--> reject recipe/easy candidates
        |
        v
  one surviving hardening candidate
        |
        v
  Phase B: build, verify, and package
```

### Phase A — screen

Target: tens of minutes, not hours.

Create only:

```text
<output_root>/
  screening/
    source_brief.md
    candidate_screen.yaml
    workflow_graph.yaml
    participant_draft/
    pilot_evaluator/
    difficulty_pilot.yaml
```

Phase A does not require:

- an exhaustive paper-wide evidence map;
- a complete source reproduction;
- an alternative valid solver;
- a large mutation suite;
- all metamorphic tests;
- release manifests and deterministic archives;
- a long final verification report.

The phase ends when one candidate survives difficulty falsification or all
candidates are rejected.

### Phase B — harden

Only a surviving candidate is expanded into the normal participant/private/
author package. Build at most one task by default.

Phase B adds:

- task-relevant source provenance;
- final inputs and starter workspace;
- privileged oracle;
- clean-room public-input reference solver;
- private evaluator and hidden cases;
- calibrated numerical tolerances;
- targeted mutants;
- relevant metamorphic tests;
- paper-blind specification review;
- deterministic verification and release records.

## 3. Phase A procedure

### 3.1 Rapid source pass

Read enough of the paper, supplement, and official code to identify:

- central claims and concrete result leaves;
- input artifacts and outputs;
- source workflow stages;
- unresolved or fragile parts;
- possible transfer, repair, comparison, and optimization tasks;
- reliable outcome metrics.

Do not yet document every paper claim. Use lazy provenance: record exact
locators only for facts needed by the top candidates.

### 3.2 Build a decision-enriched workflow graph

The graph must contain more than operations and artifacts. Add:

- **decision nodes:** choices the participant must make;
- **diagnostic nodes:** evidence that informs those choices;
- **feedback loops:** run, inspect, revise;
- **failure states:** plausible but inadequate paths;
- **claim leaves:** scientifically meaningful endpoints.

A linear graph with fully prescribed operations is usually a recipe task even
when it is long.

### 3.3 Prefer hard task archetypes

Rank these highly:

1. **Debugging and repair**
   - provide a realistic multi-file pipeline with latent scientific/software
     faults;
   - require diagnosis, repair, rerun, and evidence.

2. **Transfer under shift**
   - provide a source-grounded method or baseline in one regime;
   - require adaptation to new data, geometry, parameter range, or system size.

3. **Method selection or optimization**
   - provide a runnable baseline that falls below the target;
   - let the participant choose or design improvements under a compute budget.

4. **Reproduction plus extension**
   - reproduce a bounded result, then run an ablation, robustness test, or
     generalization experiment that is not a direct source lookup.

5. **Experiment and evidence audit**
   - require the participant to design comparisons, aggregate stochastic runs,
     diagnose conflicting evidence, and support a structured conclusion.

6. **Multi-module completion**
   - provide an incomplete research workspace, not an empty single-file
     submission;
   - remove or corrupt components that require integration and testing.

Disfavor as final hard tasks:

- implement a fully disclosed formula;
- translate detailed pseudocode into one script;
- compute a table from explicit equations;
- reproduce one figure with supplied source code;
- emit many rows from one deterministic mapping;
- submit data generated by a completely specified recurrence;
- solve a standard regression or library-call problem.

Such tasks may remain unit tests or private rubric components.

### 3.4 Enforce a method-disclosure budget

The participant must receive enough information to understand:

- input semantics;
- required behavior;
- deliverables;
- constraints;
- public success dimensions.

The participant should not receive the complete reference algorithm unless the
task's difficulty lies elsewhere and a fresh-agent pilot confirms that.

For each candidate, enumerate the major steps in the reference solver and mark
each as:

- `public_definition`: a domain convention required to interpret the task;
- `public_recipe`: an algorithmic step explicitly instructed;
- `inferable`: ordinary technical knowledge;
- `method_free`: one of many valid choices;
- `hidden_dependency`: invalid.

Compute:

```text
recipe_disclosure_ratio =
    public_recipe_steps / max(1, total_reference_algorithm_steps)
```

The default screening maximum is `0.55`. This is a warning threshold rather
than a mathematical law, but a higher value requires strong empirical evidence
that the remaining task is genuinely hard.

A long `TASK.md` that mirrors the reference solver should be rejected.

### 3.5 Require decision and feedback burden

A hardening candidate should normally include:

- at least two consequential decision nodes;
- at least one feedback loop;
- at least one hidden generalization axis;
- at least two coupled deliverable types;
- an existing workspace or multi-stage experiment when natural.

A decision is consequential only when:

- multiple plausible actions exist;
- the public data or experiment distinguishes them;
- choosing poorly materially hurts hidden performance;
- the task description does not state the correct choice.

Choosing a filename, tie rule, or serialization format is not a decision node.

### 3.6 Build a minimal pilot package

Construct the smallest draft that preserves the proposed challenge:

```text
participant_draft/
  TASK.md
  input/
  workspace/
```

Build a lightweight hidden pilot evaluator with:

- one or two ordinary hidden cases;
- one meaningful distribution shift;
- the primary outcome metric;
- a minimal structural gate.

Do not harden security, packaging, or mutation coverage yet. The pilot
evaluator is a difficulty-falsification instrument, not a release evaluator.

### 3.7 Run baselines

At minimum run:

1. **trivial baseline**
   - no-op, unchanged starter, constant prediction, or source-free minimum;

2. **recipe baseline**
   - the most direct interpretation of the public instructions using standard
     libraries and no research iteration;

3. **source-clone baseline**, when relevant
   - demonstrate that unchanged source code cannot directly pass.

If the recipe baseline passes, reject the candidate. More hidden cases or
mutants will not make it hard.

### 3.8 Run fresh-agent difficulty pilots

Freeze the participant draft and its hash. Launch fresh contexts that receive:

- only the participant draft;
- the pilot solver prompt;
- declared tools and resource budget;
- no paper, source repository, author messages, reference solver, private files,
  or hints.

Use at least two independent attempts by default. When available, use the same
frontier agent family that the benchmark intends to challenge.

Record:

- exact agent system;
- immutable participant hash;
- wall-clock and token/tool budgets;
- score and pass status;
- time to first valid artifact;
- strategy used;
- failure mode;
- whether the agent needed iteration.

Default falsification policy:

- reject or strengthen if any fresh attempt fully passes;
- reject or strengthen if median score is at least `0.70`;
- reject if the task collapses to a short direct implementation;
- investigate rather than accept if all attempts score zero;
- keep only candidates showing meaningful but incomplete progress.

These thresholds are configurable. They are intended as an early filter, not
the final ALE calibration.

If no fresh-agent command is available, stop at `needs_difficulty_pilot`.
Do not spend hours producing a release-grade package for an untested
structural candidate.

## 4. Phase B procedure

### 4.1 Targeted source grounding

Expand provenance only for the selected task:

- exact paper/code/data versions;
- task-relevant equations and protocols;
- source conflicts;
- observed commands and artifacts when execution is needed;
- benchmark-authored transformations.

Avoid exhaustive paper-wide documentation unless it directly supports the
task.

### 4.2 Final participant workspace

Prefer a professional workspace:

```text
participant/
  TASK.md
  input/
  workspace/
    package_or_project_files
  tests_or_public_checks/
```

The final task should usually ask the participant to modify or extend the
workspace and produce linked deliverables, for example:

```text
output/
  code_changes_or_entrypoint
  predictions_or_trajectories
  metrics.json
  figure_data.csv
  claims.json
  report.md
```

Multiple files are not inherently hard, but a real workspace reduces the
single-function synthesis bias.

### 4.3 Specification closure without recipe leakage

For every solution-critical item, require one of:

- publicly defined scientific semantics;
- inferable information from public assets;
- method freedom under an outcome-based evaluator.

No hidden dependency is allowed.

Do not close the specification by disclosing the complete source solution.
If one exact algorithm is mandatory, either:

- make the challenge about repair, transfer, optimization, or integration
  around that algorithm; or
- classify the result as an implementation task rather than a hard-tier task.

### 4.4 Reference layers

Keep the three-layer model:

1. privileged oracle;
2. clean-room public-input reference solver;
3. independent alternative implementation when useful.

The reference solver proves solvability, not difficulty. Run it only after the
difficulty screen has passed.

### 4.5 Private evaluation

Use:

- hard gates for structure, safety, completeness, and resources;
- continuous outcome metrics for scientific quality;
- hidden data, regimes, and perturbations;
- private intermediate rubrics when they improve diagnosis or partial credit;
- structured evidence checks for reports and conclusions.

Do not require exact source code, exact weights, exact plot pixels, or one
canonical algorithm when behavioral equivalence is possible.

### 4.6 Tolerances

For deterministic quantities:

```text
allowed_error = max(abs_tolerance, rel_tolerance * reference_scale)
```

Calibrate from:

- conditioning;
- independent implementations;
- solver/integrator accuracy;
- repeated runs;
- acceptable scientific equivalence.

For stochastic tasks use multiple hidden seeds or instances and evaluate
aggregate performance, confidence intervals, quantiles, ranks, or
baseline-relative effects.

### 4.7 Targeted evaluator hardening

After the candidate survives the pilot:

- add realistic mutants covering distinct failure categories;
- add metamorphic tests only where scientifically relevant;
- add malformed/security/resource probes;
- run evaluator determinism checks;
- perform a fresh paper-blind specification review.

Five useful mutants are better than fifteen variants of a simple formula error.
Mutation coverage validates the evaluator; it still does not certify difficulty.

## 5. Time and artifact budgets

The v2 manifest has explicit phase budgets. Recommended defaults:

| Phase | Default |
| --- | ---: |
| rapid source pass | 20 minutes |
| candidate design | 20 minutes |
| minimal package and baselines | 30 minutes |
| each fresh-agent pilot | 30 minutes |
| full hardening | only after survival; up to 180 minutes |

Other efficiency rules:

- screen at most three candidates;
- fully harden at most one;
- keep the screening source brief concise;
- defer alternative solvers and large mutant suites;
- reuse downloaded source snapshots across sessions;
- parallelize independent source, code-map, and critic work when safe;
- record phase timing so authoring overhead is visible.

Long source builds or simulations can exceed these defaults when justified, but
the pipeline must not spend four hours hardening a candidate that has never
survived a 30-minute fresh-agent solve attempt.

## 6. Final statuses

Use one:

- `screen_candidate`;
- `rejected_recipe_task`;
- `rejected_shortcut`;
- `rejected_pilot_too_easy`;
- `rejected_specification_gap`;
- `rejected_reference_failure`;
- `needs_difficulty_pilot`;
- `hardening_candidate`;
- `verified_hard_candidate`;
- `needs_scientific_review`;
- `needs_full_agent_calibration`;
- `frontier_challenging`;
- `no_viable_hard_task`.

`verified_hard_candidate` requires:

- passed difficulty-falsification pilots;
- clean-room solvability;
- valid private evaluation;
- no specification gap;
- justified tolerances;
- targeted evaluator stress tests.

`frontier_challenging` additionally requires statistically meaningful trials
against pinned frontier agent systems on the exact task build.

## 7. Using the V2 kit

1. Copy `templates/codex_task_extraction/v2/session_manifest.template.yaml`.
2. Fill the source, output, pilot-agent, and resource fields.
3. Start Codex at the repository root.
4. Paste `prompts/codex_task_extraction/v2/SESSION_PROMPT.md`.
5. Require Phase A results before allowing Phase B.
6. Review `screening/difficulty_pilot.yaml`.
7. Permit full hardening only for a surviving candidate.
8. Reuse the existing V1 source/evidence/task/evaluation/verification templates
   for Phase B, adding the V2 candidate and pilot records as immutable lineage.
9. Review the final verification report and exact-build calibration separately.
