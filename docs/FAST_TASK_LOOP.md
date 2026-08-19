# Fast task loop

This is the default workflow for rapidly screening paper-derived tasks. It is intentionally much smaller than the V1/V2 authoring pipelines.

The goal is not to prove that a task is perfectly packaged or universally hard. The goal is to answer one practical question quickly:

> Can a fresh strong agent solve this task correctly within 10 minutes using only the participant-visible files?

If yes, strengthen the task and try again. If no, keep it as a hard candidate.

## Minimal acceptance rule

A task is a `pilot_hard_candidate` when all three conditions hold:

1. the known-good solution passes the evaluator;
2. a fresh agent receives only `participant/` and fails to produce a passing answer within the time limit;
3. the failure is not obviously caused by a missing file, broken command, or contradictory task statement.

That is the entire screening rule. It is deliberately empirical and lightweight.

## Minimal directory layout

```text
tasks/<paper>/<task>/
  participant/
    TASK.md
    input/
    software/                 # optional starter workspace
  solution/
    solve.py                  # or another simple known-good solution
  evaluator/
    evaluate.py
    hidden/                   # optional small hidden case/reference
  attempts/
    fresh_01/
      output/
      notes.txt
  status.json
```

The fresh agent receives only `participant/`. It does not receive `solution/`, `evaluator/`, the paper, source code, or the authoring conversation.

## The loop

### Step 1: skim the paper

Spend no more than 10 minutes on the first pass.

Identify one workflow that can become a difficult professional task. Prefer:

- debugging or repairing a multi-file scientific workspace;
- adapting a method to a shifted regime;
- selecting or optimizing a method under a budget;
- reproducing one result and then performing a nontrivial extension or ablation;
- running experiments and reconciling conflicting evidence;
- completing an incomplete pipeline where several components interact.

Avoid tasks that mainly ask the agent to transcribe equations, implement a completely disclosed recurrence, call one standard fitting routine, or generate many rows from one formula.

### Step 2: draft one task

Spend no more than 15 minutes on the first draft.

Create only:

- `participant/TASK.md`;
- the necessary public inputs and optional starter workspace;
- one known-good solution;
- one quick evaluator.

The participant task must be clear about the goal, files, outputs, environment, and constraints. It should not reveal the complete solution recipe unless that recipe is unavoidable.

A good task should require at least one consequential choice, diagnosis, or run-inspect-revise loop. More graph nodes do not automatically make a task harder.

### Step 3: run the known-good solution

The known-good solution may use insights learned from the paper and official code, but at runtime it should read the same participant inputs whenever practical.

Run it once and run the evaluator once. The reference solve should normally finish within two minutes and the evaluator within 30 seconds. If the known-good solution does not pass, fix the task or evaluator before testing an agent.

No alternative solver, mutation suite, metamorphic suite, archive reproducibility check, hash manifest, or repeated deterministic run is required in this fast loop.

### Step 4: run one fresh agent

Start a new session with no paper/source context. Give it only `participant/` and the fresh-agent prompt.

Default limits:

```text
wall time: 600 seconds
network: whatever the benchmark intends to allow
attempts: one
```

Save its output under `attempts/fresh_01/output/` and run the evaluator.

### Step 5: decide

- **Fresh agent fails or times out with an incorrect/incomplete result:** keep the task as `pilot_hard_candidate`.
- **Fresh agent passes:** the task is too easy. Strengthen it and rerun the loop.
- **Fresh agent fails because of an obvious missing dependency, broken path, or contradictory specification:** fix the task and rerun; do not count this as hardness.
- **No useful task can be made without disclosing the whole algorithm:** reject the paper for this pipeline.

Use at most three strengthening rounds. Do not spend hours polishing a task that repeatedly remains easy.

## How to strengthen a task

When the fresh agent passes, inspect how it solved the task. Change the structure of the work rather than adding volume.

Good strengthening moves:

1. **Recipe to repair:** provide a partially working multi-file pipeline with realistic interacting faults instead of asking for a clean implementation from formulas.
2. **In-distribution to transfer:** add a hidden regime shift and require the agent to adapt or select a robust method.
3. **Single method to method choice:** provide an inadequate baseline and require the agent to choose, justify, and implement improvements.
4. **One-shot to feedback loop:** require public diagnostics, iteration, and evidence that the final configuration fixed the observed failure.
5. **Reproduction to extension:** require an ablation, robustness study, or controlled comparison after the basic result is reproduced.
6. **Single artifact to coupled deliverables:** require code, results, and a machine-readable evidence summary that must agree.

Bad strengthening moves:

- more rows of the same calculation;
- tighter numerical tolerance without scientific reason;
- larger compute only;
- obscure constants hidden from the participant;
- longer formatting rules;
- more hidden cases that test the same fully disclosed algorithm.

## Quick evaluator guidance

The evaluator should be small and fast. It may return either pass/fail or a score in `[0,1]`.

Use exact checks only for basic structure. Use numerical tolerance for scientific results:

```python
abs(actual - expected) <= atol + rtol * abs(expected)
```

Prefer checking final behavior on one or a few hidden inputs over comparing source code or exact bytes. Do not build a complicated rubric before the task survives the fresh-agent test.

A minimal evaluator output is:

```json
{"passed": false, "score": 0.42, "reason": "hidden-case prediction error"}
```

## What this fast loop intentionally skips

The screening loop does not require:

- source hashes and content-addressed manifests;
- exhaustive evidence maps;
- full claim trees or provenance graphs;
- license reports during initial screening;
- deterministic archive reproduction;
- multiple valid solvers;
- large mutant suites;
- metamorphic test suites;
- complex score-weight contracts;
- cross-platform packaging audits;
- repeated evaluator runs;
- full ALE deployment integration.

Those can be added later to the small subset of tasks that actually survive difficulty screening and are selected for production.

## Recommended commands

The exact commands are task-specific, but keep the interface simple:

```text
python solution/solve.py --input participant/input --output _reference_output
python evaluator/evaluate.py --submission _reference_output

# After the fresh agent run:
python evaluator/evaluate.py --submission attempts/fresh_01/output
```

## Status values

Use only these statuses:

- `draft`
- `reference_failed`
- `ready_for_fresh_agent`
- `too_easy`
- `needs_fix`
- `pilot_hard_candidate`
- `rejected`

A `pilot_hard_candidate` means one fresh agent failed under the recorded time limit. It is a fast screening result, not a universal frontier-hardness claim.
