# Codex task-extraction templates

These files define a human- and Codex-readable authoring package. They are
documentation templates, not executable authority and not a replacement for
Paper2ALE's strict project schemas.

## Recommended per-paper directory

```text
generated_tasks/<paper_slug>/
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

## Template mapping

| Template | Copy to |
| --- | --- |
| `session_manifest.template.yaml` | Session input, outside or inside `authoring/` |
| `source_manifest.template.yaml` | `authoring/source_manifest.yaml` |
| `evidence_map.template.yaml` | `authoring/evidence_map.yaml` |
| `workflow_graph.template.yaml` | `authoring/workflow_graph.yaml` |
| `task_candidates.template.yaml` | `authoring/task_candidates.yaml` |
| `task_spec.template.yaml` | `tasks/<task_slug>/author/task_spec.yaml` |
| `TASK.md.template` | `tasks/<task_slug>/participant/TASK.md` |
| `evaluation_spec.template.yaml` | `tasks/<task_slug>/private/evaluation_spec.yaml` |
| `verification_report.template.md` | `tasks/<task_slug>/author/verification_report.md` |
| `session_report.template.md` | `authoring/session_report.md` |
| `RELEASE_CHECKLIST.md` | Use during final review; copy when useful |

`source_manifest.yaml`, `evidence_map.yaml`, `session_report.md`, the actual
grader, inputs, solvers, mutants and `verify.py` must be generated from the
specific paper.

## Visibility

Never publish `private/` or `author/` to a benchmark participant. A public
review fixture may expose them only after permanently retiring that exact
instance from scoring.

## Verification command

Every task package should provide:

```text
python tasks/<task_slug>/scripts/verify.py
```

The script should run the oracle/reference checks, clean-room solve, evaluator,
valid alternatives, mutants, determinism checks and package leakage checks. It
must exit nonzero on any failed release gate.
