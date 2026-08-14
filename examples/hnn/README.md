# Grounded Hamiltonian-dynamics fixture

This fixture compiles exactly three paper-blind ALE tasks:

1. a masked canonical-gradient code completion;
2. scalar spring-model training with safe JSON weight export; and
3. a structured two-body equation/implementation audit.

The author manifest deliberately records three source conflicts instead of
silently blending them: spring scalar scaling and sampling protocol, the
two-body potential sign and distance power, and the latent-coordinate loss
sign. The two-body disagreement is selected as the third task; the latent-loss
disagreement remains provenance only.

Run the fixture with the project compiler:

```text
paper2ale audit examples/hnn/project.json
paper2ale build examples/hnn/project.json --out dist --jobs 3
```

Each task defaults to three deterministic instances. `--seed` changes every
derived instance reproducibly, and `--instances` overrides the count. Agent
packages contain `description.md`, `task_card.json`, `main.py`, public instance
inputs, and starter software. Evaluator packages add hidden targets, the grader,
and reference examples. Author packages additionally contain source provenance,
the evidence graph, and QA notes.

The build also emits one `<task-id>.ale-local.zip` operator bundle per task.
It contains current ALE task-discovery source plus canonical local task data at
`task-data/physical_sciences/<task-id>/<000|001|002>/`. Configure ALE with
`task_data_source: local:<extracted-root>/task-data`; its runtime then withholds
each `reference/` tree until evaluation.

The training grader never imports a submitted model. It accepts only bounded,
finite `tanh-mlp-v1` JSON weights, differentiates the scalar network itself, and
performs its own hidden-state and rollout evaluation.
