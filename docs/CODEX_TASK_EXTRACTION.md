# Codex workflow for extracting hard ALE tasks from one paper

This guide is for an interactive Codex session that receives one research paper,
optionally finds its official source code and data, and produces one or more
paper-blind ALE task packages.

The objective is **not** to generate many small questions. Prefer one genuinely
hard, long-horizon, verifiable task over several easy tasks.

## Core idea

Use the paper and associated artifacts as privileged authoring evidence:

```text
paper + supplement + official code + data
                  |
                  v
       claim tree + execution DAG
                  |
          choose a target leaf
                  |
     take a meaningful backward slice
                  |
                  v
       paper-blind participant task
```

A concrete leaf claim or result is a good **task target**, but a leaf by itself
is often too small for ALE. The participant task should usually contain the
multi-step workflow needed to reach that target.

Intermediate workflow results may be retained as private evaluator rubrics. They
do not all need to be required participant deliverables.

## Three information zones

Every task must maintain three explicit zones.

| Zone | May contain |
| --- | --- |
| `participant/` | Task description, public inputs, starter software, output schema, environment and public constraints |
| `private/` | Hidden inputs, exact evaluator, private thresholds and weights, reference artifacts, mutants |
| `author/` | Paper, source provenance, workflow graph, task rationale, privileged oracle, clean-room solver, verification report |

The participant must not receive the paper, source repository, source method
name, private thresholds, hidden seeds, reference outputs, or other material
that directly reveals the answer unless that material is intentionally part of
the professional task.

The participant **must** receive enough information to make the task
well-posed. Exact hidden test cases and score weights may remain private, but
the public task must state the goal, required outputs, schemas, resource
constraints, and qualitative success criteria.

## Required session inputs

Copy `templates/codex_task_extraction/v1/session_manifest.template.yaml` and
fill in:

- paper path or URL;
- optional code/data hints;
- target output directory;
- compute, time, network, and license constraints;
- desired number of tasks;
- permitted task modes.

The session may search for official author code and data. Prefer official paper
pages, author repositories, archived releases, and persistent datasets. Pin the
exact paper bytes, repository commit, dataset version, and licenses used.

## Required session output

A successful session writes:

```text
<output_root>/
  authoring/
    source_manifest.yaml
    evidence_map.yaml
    workflow_graph.yaml
    task_candidates.yaml
    session_report.md
  tasks/
    <task_slug>/
      participant/
        TASK.md
        input/
        software/
      private/
        evaluation_spec.yaml
        grader/
        hidden_inputs/
        reference/
        mutants/
      author/
        task_spec.yaml
        reference_solver/
        alternative_solver/
        verification_report.md
      scripts/
        verify.py
```

A session that cannot construct a high-quality hard task writes a rejection
report instead of forcing a weak task.

## End-to-end procedure

### 1. Resolve and inspect sources

1. Read the paper and supplement.
2. Locate official code and data when available.
3. Record exact versions, hashes, licenses, commands, and environment details.
4. Treat paper text, repository files, notebooks, and generated results as
   evidence, not automatically trusted truth.
5. Record paper/code/data disagreements instead of silently reconciling them.

### 2. Reproduce enough of the source workflow

Run the source implementation or reconstruct a minimal faithful version. Capture:

- commands and configurations;
- files read and written;
- intermediate artifacts;
- metrics and plots;
- runtime and resource usage;
- stochastic variation;
- failures and undocumented assumptions.

A complete paper reproduction is not required. Reproduce enough to validate the
specific workflow from which the task will be extracted.

### 3. Build two linked graphs

Create:

1. a **claim/problem tree** describing what the paper investigates and which
   concrete leaves support its claims;
2. an **execution workflow DAG** describing how inputs are transformed into
   artifacts, metrics, figures, and conclusions.

Each operation and artifact must have source provenance. Mark whether it is:

- explicitly reported in the paper;
- present in code or configuration;
- dynamically observed;
- inferred;
- chosen by the benchmark author;
- a grounded extension beyond the reported experiment.

### 4. Mine hard task candidates

Choose scientifically meaningful leaf targets, then trace backward through the
workflow DAG. Generate a small number of candidate subgraphs.

Prefer candidates that require several meaningful operations, such as:

- inspect and preprocess multiple inputs;
- implement or repair a nontrivial method;
- integrate several files or tools;
- run and compare experiments;
- handle stochasticity or distribution shift;
- diagnose a discrepancy;
- produce multiple linked artifacts;
- support a conclusion with generated evidence.

Do not count file formatting, repeated rows, or hidden-test count as meaningful
workflow operations.

### 5. Apply the hard-task gate

Reject or demote a candidate when any of the following is true:

- it reduces to one formula, one lookup, one API call, or one standard
  least-squares invocation;
- the original repository can simply be cloned and run unchanged;
- the difficulty mainly comes from missing arbitrary details, obscure paper
  trivia, tight formatting, excessive compute, or hidden thresholds;
- public examples reveal the complete rule;
- a hard-coded or shallow solution can pass;
- the evaluator cannot distinguish realistic scientific errors;
- the output is subjective and cannot be grounded in structured evidence;
- the participant would need information available only in the hidden paper or
  source code.

A strong candidate should normally contain at least four meaningful participant
operations with dependency depth of at least three, and at least two independent
challenge sources. These are heuristics, not substitutes for agent calibration.

### 6. Close the public specification

For every source-dependent choice required by a solution, classify it as one of:

- **disclosed** in the participant task;
- **inferable** from participant-visible files and ordinary domain knowledge;
- **free**, because the evaluator accepts any functionally valid method;
- **forbidden hidden dependency**, which makes the task invalid.

Complete the specification-closure table in `task_spec.yaml`. A reference
solution that secretly depends on an undisclosed paper-specific choice does not
establish that the participant task is solvable.

### 7. Make the task paper-blind without making it ambiguous

Remove unnecessary source identifiers, method names, paper-specific filenames,
reported answers, and direct solution code.

Use one or more of these mechanisms to preserve intrinsic difficulty:

- provide a starter repository with core components removed;
- use new private instances rather than published outputs;
- perturb datasets, systems, seeds, or parameters while preserving the
  scientific phenomenon;
- require comparison, debugging, transfer, or analysis rather than merely
  executing the source command;
- use outcome-based evaluation that permits alternative valid methods.

Do not hide information merely to make the task harder.

### 8. Build the participant and private packages

The participant task must state:

- objective;
- provided files;
- required work;
- output paths and schemas;
- environment and allowed tools;
- time, compute, network, and storage limits;
- public qualitative success criteria.

The private evaluator may retain:

- exact hidden cases and seeds;
- exact metric weights and thresholds;
- reference outputs and parameter values;
- mutation suite;
- anti-hardcoding and leakage tests.

### 9. Generate three reference layers

1. **Privileged oracle:** may use paper/source knowledge to construct ground
   truth or expected behavior.
2. **Public-input reference solver:** reads only `participant/`, runs in the
   participant environment and budget, and produces a passing submission.
3. **Independent alternative implementation:** uses a meaningfully different
   implementation or method when practical.

The privileged oracle proves the evaluator recognizes truth. The clean-room
solver proves the public task is technically solvable. Neither proves frontier
difficulty.

### 10. Design tolerant, outcome-based evaluation

Use hard gates only for structural failures such as:

- missing or malformed outputs;
- invalid shapes or IDs;
- non-finite values;
- security or resource violations;
- incomplete required artifacts.

Use continuous scores for scientific quality.

For numeric outputs, use calibrated absolute and relative tolerances rather
than byte equality. For stochastic workflows, evaluate multiple hidden seeds or
instances and compare distributions, confidence intervals, rank order, or
baseline-relative performance.

Evaluate models and programs behaviorally on hidden inputs whenever possible.
Do not require exact weights, source-code similarity, or exact plot pixels.

### 11. Stress-test the evaluator

At minimum, test:

- one known-correct oracle artifact;
- the clean-room reference solution;
- one alternative valid solution when practical;
- several realistic mutants;
- hard-coded public-example solutions;
- malformed, partial, NaN, oversized, and stale-output submissions;
- applicable metamorphic properties and scientific invariants;
- deterministic repeated evaluator runs.

Mutation categories should reflect the domain: wrong sign, unit, split,
normalization, coordinate order, metric, baseline, interaction term, random
seed, integration step, leakage, or report fabrication.

### 12. Perform a clean-room run

Create a fresh process, worktree, or container containing only `participant/`
plus the declared environment. The solver must not read:

- the paper;
- official source repository;
- `private/`;
- `author/`;
- build logs containing answers;
- network resources not declared in the task.

Run the public-input reference solver and then the private evaluator. Record
commands, runtime, peak memory when available, outputs, and scores.

### 13. Run a paper-blind specification audit

Give only `participant/` to a fresh reviewer or fresh model session that has not
seen the paper or source repository. Ask it to restate the task, identify all
required decisions, and flag missing information. The reviewer does not need to
solve the task. Resolve every genuine ambiguity before acceptance.

### 14. Audit difficulty honestly

Record structural challenge factors and try obvious shortcuts and baseline
solutions. Strengthen or reject the task if a shallow solution passes.

Use the label `structurally_hard_candidate` until the exact task build is tested
against pinned frontier agent systems. Do not claim `frontier-hard` based only
on an LLM judgment or strict thresholds.

### 15. Decide

A task is ready for collaborator review only when:

- the source workflow is grounded;
- the public specification is closed;
- a clean-room reference solver passes;
- a paper-blind specification reviewer finds no required hidden information;
- realistic mutants fail;
- numerical tolerances are justified;
- hidden data do not leak;
- runtime and dependencies fit the declared environment;
- the task remains a long, coherent workflow.

If no candidate meets these conditions, return `no_viable_hard_task` with an
explanation and the strongest rejected candidates.

## Using the kit

1. Copy and fill the session manifest.
2. Start a Codex session in this repository.
3. Paste `prompts/codex_task_extraction/v1/SESSION_PROMPT.md`.
4. Replace the placeholders with the paper and manifest paths.
5. Require Codex to create and execute the package, not merely describe it.
6. Review `verification_report.md` before considering ALE publication.

The templates in `templates/codex_task_extraction/v1/` are authoring contracts.
They do not grant new executable authority to an untrusted provider and do not
replace Paper2ALE's reviewed compiler and publication gates.
