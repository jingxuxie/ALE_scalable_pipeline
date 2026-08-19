# Fast end-to-end task loop

This is the default workflow for rapidly extracting and screening hard paper-derived tasks.

The user supplies one prompt to a main Codex session on Windows. That session performs the entire loop:

```text
paper/code
   ↓
create one task + one solution + one evaluator
   ↓
reference solution passes
   ↓
copy participant files to a clean WSL workspace
   ↓
launch a fresh ephemeral Codex session
   ↓
evaluate its output
   ↓
fail → keep hard candidate
pass → structurally strengthen and repeat
```

There is no manual fresh-agent handoff.

## Acceptance rule

A task is a `pilot_hard_candidate` when:

1. the known-good solution passes;
2. a fresh strong agent receives only `participant/`;
3. that agent does not produce a passing output within the configured time limit; and
4. the failure is not obviously caused by a missing file, broken command, or contradictory task statement.

This is intentionally a fast empirical screen. It is not a claim that every frontier agent will fail.

## Default speed settings

Recommended defaults:

```text
source skim:            3–5 minutes
candidate construction: 10–15 minutes
fresh-agent timeout:    360 seconds
maximum total rounds:   2
quick evaluator:        under 30 seconds
```

The fresh timeout may be raised to 600 seconds, but the helper rejects larger values. If a paper does not quickly yield a promising non-recipe task, reject it rather than spending hours forcing one.

## Minimal task directory

```text
tasks/<paper>/<task>/
  participant/
    TASK.md
    input/
    software/                 # optional
  solution/
    solve.py                  # one known-good solution
  evaluator/
    evaluate.py
    hidden/                   # optional small hidden case/reference
  attempts/
    fresh_01/
      output/
      run.json
      evaluation.json
      agent_stdout.txt
      agent_stderr.txt
    fresh_02/
      ...
  status.json
```

Only `participant/` is copied into WSL for the fresh attempt.

## Prerequisites

The Windows authoring machine needs:

- WSL;
- a Linux Codex CLI installation inside WSL;
- Codex already authenticated/configured inside WSL;
- GNU `timeout`, normally provided by coreutils;
- Windows PowerShell.

Codex CLI supports non-interactive runs through `codex exec`. The helper uses a new ephemeral session, a workspace-write sandbox, no approval prompts, and a fresh temporary workspace for every round.

## One-prompt workflow

Paste:

```text
prompts/fast_task_loop/AUTHOR_PROMPT.md
```

into the main Windows Codex session and fill in the paper, optional code/data, output directory, model, timeout, and WSL distro.

The main session must not stop after proposing or building a task. It must continue through the fresh WSL attempt, evaluation, and any required hardening rounds.

## Authoring loop

### 1. Pick one non-recipe workflow

Prefer:

- diagnosis and repair of a partially working multi-file scientific workspace;
- transfer or adaptation under a shifted regime;
- method selection or optimization under a budget;
- reproduction followed by an ablation, robustness study, or extension;
- experiment design and reconciliation of conflicting evidence;
- a run–inspect–revise feedback loop.

Avoid:

- formula transcription;
- a fully disclosed recurrence or algorithm;
- one standard fit, optimizer, or library call;
- clone-and-run reproduction;
- large repetitive outputs;
- difficulty created by missing arbitrary facts.

### 2. Build only the essentials

Create:

- a clear participant task and public inputs;
- one known-good solution;
- one quick evaluator.

The evaluator prints one JSON object:

```json
{"passed": false, "score": 0.42, "reason": "hidden-case error"}
```

Use exact checks only for basic file/schema validity. Use ordinary absolute/relative tolerance for numerical results:

```python
abs(actual - expected) <= atol + rtol * abs(expected)
```

### 3. Verify the known-good path once

Run the solution and evaluator once. If the reference cannot pass after one obvious fix, reject or defer the task. Do not start a large debugging or verification campaign.

### 4. Launch the fresh WSL attempt automatically

The main Windows session runs:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools/fast_task_loop/run_fresh_wsl.ps1 `
  -TaskDirectory <TASK_DIRECTORY> `
  -Round 1 `
  -TimeoutSeconds 360 `
  -Model gpt-5.6-sol
```

Use `-Distro <name>` when a non-default WSL distribution is required.

The helper:

1. creates `attempts/fresh_NN/`;
2. copies only `participant/` into a new `/tmp/paper2ale-fast/...` directory;
3. pipes the fresh-agent prompt into `codex exec --ephemeral`;
4. terminates the process at the configured deadline;
5. copies `output/` and small run logs back to Windows;
6. deletes the temporary WSL workspace unless `-KeepWorkspace` is supplied.

The helper does **not** decide task correctness. `codex exec` may exit without a correct submission, so the task evaluator is authoritative.

### 5. Grade and iterate

Run the evaluator on:

```text
attempts/fresh_NN/output/
```

Then:

- **Evaluator fails or the attempt times out:** keep the task as `pilot_hard_candidate`, unless the failure is clearly an infrastructure/specification problem.
- **Evaluator passes:** inspect how the agent solved it, make one structural hardening change, update the solution/evaluator, rerun the reference, and launch a new fresh WSL session.
- **Setup/specification failure:** fix automatically and rerun; do not count it as hardness.
- **Still easy after the maximum rounds:** mark `rejected` with reason `remains_too_easy`.

Good hardening changes alter the reasoning workflow:

- clean implementation → interacting diagnosis/repair;
- in-distribution behavior → hidden regime shift;
- disclosed method → method choice under outcome-based evaluation;
- one-shot execution → public diagnostics and revision;
- reproduction → extension or ablation;
- one output → coupled code, results, and evidence.

Do not harden through more rows, obscure constants, stricter formatting, unjustified tolerance, or raw compute.

## What is intentionally omitted

Initial screening does not require:

- source hashes or manifests;
- evidence/claim/workflow graphs;
- exhaustive provenance or license reports;
- alternative solvers;
- mutant or metamorphic suites;
- archive reproducibility;
- complicated scoring contracts;
- repeated grader runs;
- production security packaging;
- full ALE integration.

Those may be added later only to the small subset of tasks selected for release.

## Status values

Use only:

- `draft`
- `reference_failed`
- `blocked`
- `too_easy`
- `pilot_hard_candidate`
- `rejected`

The main Codex session should update `status.json` after every round and finish without requesting a manual fresh-agent action.
