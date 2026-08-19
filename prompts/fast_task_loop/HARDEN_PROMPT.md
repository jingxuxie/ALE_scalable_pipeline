# Fast hardening prompt

Use this in the original authoring session only when the fresh agent passed.

```text
The fresh agent solved the current task within the time limit, so the task is too easy.

Inputs:
- Current task directory: <TASK_DIRECTORY>
- Fresh-agent attempt: <ATTEMPT_DIRECTORY>
- Evaluator result: <EVALUATOR_RESULT>

Inspect how the fresh agent solved the task. Identify the shortcut or missing source of difficulty. Strengthen the task by changing the participant's reasoning and workflow, not by adding more rows, tighter tolerances, obscure constants, or raw compute.

Choose one major structural change:
1. turn a clean implementation task into diagnosis and repair of a partially working multi-file workspace;
2. add a meaningful hidden regime shift that requires adaptation or method selection;
3. replace a disclosed algorithm with an outcome target that permits multiple methods;
4. require an experiment, ablation, or robustness comparison after the basic result;
5. add a run-inspect-revise feedback loop using public diagnostics;
6. require coupled code, numerical results, and evidence that must agree.

Keep the task self-contained and clear. Do not create missing-information difficulty.

Update only:
- participant/;
- solution/;
- evaluator/;
- status.json.

Then:
- rerun the known-good solution;
- rerun the quick evaluator;
- set status to ready_for_fresh_agent;
- summarize what changed and why the old solution path should no longer be sufficient.

Do not add hashes, manifests, evidence graphs, alternative solvers, mutant suites, metamorphic suites, or production packaging.

Use at most three total hardening rounds. If the task repeatedly remains easy, reject it and move to another paper or workflow.
```
