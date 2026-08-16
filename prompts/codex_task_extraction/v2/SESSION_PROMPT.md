# Copy-paste prompt: Codex hard-task extraction v2

Replace every `<...>` placeholder before starting.

```text
You are working in the Paper2ALE repository. Extract at most one fully hardened,
genuinely difficult, paper-blind, self-contained, automatically verifiable ALE
task from the supplied research paper.

Paper and assets:
- Paper path or URL: <PAPER_PATH_OR_URL>
- Supplement: <SUPPLEMENT_PATH_OR_URL_OR_NONE>
- Official code hint: <CODE_URL_OR_NONE>
- Data hint: <DATA_URL_OR_NONE>

Session:
- Filled V2 manifest: <PATH_TO_V2_SESSION_MANIFEST>
- Output root: <OUTPUT_ROOT>
- Pilot-agent command(s) or harness: <COMMANDS_OR_NONE>
- Target participant hardware/runtime: <HARDWARE_AND_RUNTIME>
- Benchmark network policy: <OFF_OR_EXPLICIT_POLICY>

Read these files before doing work:
1. docs/CODEX_TASK_EXTRACTION_V2.md
2. docs/TASK_DIFFICULTY_FAILURE_ANALYSIS.md
3. prompts/codex_task_extraction/v2/PILOT_SOLVER_PROMPT.md
4. templates/codex_task_extraction/v2/session_manifest.template.yaml
5. templates/codex_task_extraction/v2/candidate_screen.template.yaml
6. templates/codex_task_extraction/v2/difficulty_pilot.template.yaml
7. templates/codex_task_extraction/v2/TASK.md.template
8. templates/codex_task_extraction/v2/RELEASE_CHECKLIST.md

Follow the V2 phase order exactly.

PHASE A — SCREEN AND FALSIFY DIFFICULTY

- Spend only the configured screening budget before deciding whether a candidate
  deserves full hardening.
- Inspect enough of the paper/code/data to identify the main claims, source
  workflow, and hard-task opportunities. Do not first build an exhaustive
  paper-wide evidence dossier.
- Propose at most three candidates and prefer one.
- Treat a concrete claim/result leaf as the target, but include a meaningful
  backward workflow with consequential decisions, diagnostics, and feedback.
- Reject final tasks that mainly ask the participant to translate disclosed
  equations, pseudocode, or a fully specified numerical recipe into one script.
- Do not use operation count, output count, hidden-case count, mutant count,
  task-description length, or compute cost as evidence of difficulty.
- Prefer debugging/repair, transfer under shift, method selection/optimization,
  reproduction plus extension, experiment design, or multi-module completion.
- Build only a minimal participant draft and lightweight hidden pilot evaluator.
- Run B0 unchanged/trivial and B1 direct-recipe baselines.
- Freeze and hash the participant draft.
- Run at least two fresh strong-agent solve attempts when commands are available.
  They receive only the participant draft and PILOT_SOLVER_PROMPT.md. They must
  not receive the paper, source code, author discussion, reference solver,
  private files, or hints.
- Reject or strengthen any candidate that is fully solved, receives median score
  >= the manifest threshold, or collapses to a short direct implementation.
- If no pilot-agent command is available, stop with `needs_difficulty_pilot`.
  Do not spend hours hardening an untested candidate.
- If no candidate survives, produce `no_viable_hard_task`.

PHASE B — HARDEN ONE SURVIVOR

Only after a candidate passes Phase A:

- Complete task-relevant source provenance and workflow grounding.
- Build the final participant/private/author package.
- Prefer a multi-file runnable workspace or coupled experiment suite over an
  empty single-file coding task.
- Keep the public contract complete, but do not publish the reference recipe
  when the evaluator can be method-agnostic.
- Build and run the privileged oracle.
- Build and run a clean-room reference solver that reads only participant files.
- Build the private evaluator with numerical tolerances and hidden shifts.
- Add targeted realistic mutants and scientifically relevant metamorphic tests.
- Run paper-blind specification review, leakage checks, repeated evaluator runs,
  and resource checks.
- Keep exact cases, thresholds, weights, references, and mutants private.
- Do not claim frontier difficulty without full exact-build calibration. A
  surviving hardened task is `verified_hard_candidate` or
  `needs_full_agent_calibration`.

Required output layout:
- Use the V2 directory layout in docs/CODEX_TASK_EXTRACTION_V2.md.
- Create screening/source_brief.md, screening/workflow_graph.yaml,
  screening/candidate_screen.yaml, screening/participant_draft/,
  screening/pilot_evaluator/, and screening/difficulty_pilot.yaml.
- Only for a survivor, create the final task package and verification records.
- Create a cross-platform task-local scripts/verify.py for the hardened task.
- Keep participant, private, author, and screening-only information separated.
- Do not modify unrelated repository files.

At the end, report:
1. phase timing by source pass, candidate design, pilot construction, pilot runs,
   and hardening;
2. each candidate and why it was rejected or selected;
3. recipe-disclosure audit and consequential decision nodes;
4. B0/B1 baseline scores;
5. every fresh-agent pilot system, budget, runtime, score, and failure mode;
6. exact participant snapshot hash used by the pilot;
7. what the participant sees and what remains hidden;
8. clean-room reference command and score for a hardened task;
9. tolerance, mutant, and metamorphic results;
10. final status and unresolved scientific/evaluation risks.

Do not call a task hard merely because you spent a long time generating it.
```
