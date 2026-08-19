# Changelog

## Unreleased

- Added an autonomous fast task loop in which one Windows Codex session creates
  a task, solution, and evaluator, launches fresh ephemeral Codex attempts in
  WSL, grades them, and structurally revises easy tasks without user handoff.
- Added a reusable PowerShell-to-WSL runner with a hard time limit, fresh
  temporary workspaces, participant-only copying, and copied-back outputs/logs.
- Added one concise end-to-end author prompt, one fresh-agent prompt, and minimal
  task, evaluator, and status templates.
- Made the fast loop the recommended candidate-discovery path; V2 remains an
  optional production-hardening path for tasks that survive screening.
- Added a difficulty-first Codex task-extraction V2 workflow that screens
  recipe disclosure, trivial/direct baselines, and frozen-snapshot strong-agent
  pilots before full evaluator hardening.
- Added decision-enriched workflow graphs, method-disclosure budgets, pilot
  evaluator and difficulty-report templates, phase time budgets, and explicit
  rejection statuses for easy recipe tasks.
- Documented why the current verified paper-derived tasks can remain easy even
  after extensive provenance, mutation, metamorphic, and packaging work.
- Retained the V1 authoring kit as a legacy reproducibility path.

## 0.3.0

- Added end-to-end orchestration from locked sources and assets through
  triage, workflow extraction, trusted compilation, audit, and publication.
- Added Workflow IR, task-candidate bindings, content-addressed asset storage,
  and the generic declarative compiler.
- Added separate difficulty, evaluation-power, and benchmark-sampling controls
  with build-bound empirical calibration.
- Added hard HNN examples and strengthened provenance, mutation, leakage,
  reproducibility, packaging, and Windows-path checks.
- Shipped schemas inside the Python package and added Windows/Linux CI.

## 0.2.0

- Added the initial public Paper2ALE compiler, strict project schemas,
  deterministic package projections, difficulty controls, and grounded HNN
  task families.
