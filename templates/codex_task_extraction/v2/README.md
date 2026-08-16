# Codex task-extraction templates v2

V2 uses **screen, pilot, then harden**. It rejects easy recipe-following tasks
before a Codex session spends hours constructing release-grade provenance,
mutants, metamorphic tests, and packaging.

These files are authoring contracts, not executable trust. A final task must
still pass Paper2ALE's reviewed compiler and publication gates.

## Phase A output

```text
<output_root>/
  screening/
    source_brief.md
    workflow_graph.yaml
    candidate_screen.yaml
    participant_draft/
      TASK.md
      input/
      workspace/
      public_checks/
    pilot_evaluator/
      spec.yaml
      grader_or_runner/
      hidden_cases/
    difficulty_pilot.yaml
```

Use:

- `source_brief.template.md` for the bounded source pass;
- `workflow_graph.template.yaml` for claims, decisions, diagnostics, and loops;
- `candidate_screen.template.yaml` for recipe and shortcut rejection;
- `TASK.md.template` for an outcome-first participant contract;
- `pilot_evaluator_spec.template.yaml` for the lightweight hidden pilot;
- `difficulty_pilot.template.yaml` for baselines and fresh-agent attempts.

Do not build a full evidence map, alternative solver, large mutation suite, or
release package until one candidate reaches `hardening_candidate`.

## Phase B output

For a survivor, reuse the existing V1 source/evidence/task/evaluation and final
verification templates, but preserve the V2 screening files as immutable
lineage. Re-pilot whenever the participant package changes materially.

## Visibility

Never give a pilot or benchmark participant access to:

- `screening/pilot_evaluator/`;
- `screening/difficulty_pilot.yaml`;
- paper/source snapshots;
- final `private/` or `author/` files;
- authoring conversation history.

A pilot without that isolation is invalid.

## Stopping rules

- No pilot harness: `needs_difficulty_pilot` and stop before hardening.
- Recipe/direct baseline succeeds: reject or change the task responsibility.
- Fresh strong agent fully passes or exceeds the configured easy threshold:
  `rejected_pilot_too_easy` or strengthen and re-pilot.
- No valid hard candidate: `no_viable_hard_task`.

More hidden cases, more rows, tighter tolerances, and more mutants do not repair
an intrinsically easy participant workflow.
